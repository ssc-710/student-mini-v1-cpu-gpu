"""Strengthen the actual-width adapter proof to preserve Vortex read selectors.

First requires the original adapter to fail the new property, then proves the
private repair and checks nine mutations. This is not whole-core acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.run_student_mini_gpu_adapter_formal import MUTATIONS,mutate
from scripts.student_mini_gpu_command_payload import preserve_read_payload,preserve_read_contract,drop_read_payload


def main():
    import fcntl
    names=['shared/rtl/vortex_command_adapter.sv','shared/rtl/vortex_memory_adapter.sv','shared/formal/student_mini_gpu_adapters_harness.sv']
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    paths=[ROOT/name for name in names]+[Path(__file__),ROOT/'scripts/run_student_mini_gpu_adapter_formal.py',ROOT/'scripts/student_mini_gpu_command_payload.py']
    paths += [tools/name for name in ('yosys','sby','yosys-smtbmc','boolector')]
    # Bind the actual consumer that interprets nonzero read payload bits.
    paths.append(Path('/mnt/d/open-soc-ai-labs-vortex/hw/rtl/core/VX_dcr_data.sv'))
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-payload-formal'/identity;work.mkdir(parents=True,exist_ok=False)
    original={Path(name).name:(ROOT/name).read_text() for name in names}
    original['student_mini_gpu_adapters_harness.sv']=preserve_read_contract(original['student_mini_gpu_adapters_harness.sv'])
    fixed=dict(original);fixed['vortex_command_adapter.sv']=preserve_read_payload(original['vortex_command_adapter.sv'])
    env=dict(os.environ,PATH=str(tools)+':/usr/local/bin:/usr/bin:/bin')
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,whole_core_qualified=False,depth=32,
        ports=2,data_width=512,address_width=26,tag_width=10,bindings=bindings,records=[],
        scope='Preserve complete command read/write payload plus existing actual-width skid adapter properties; no external DMA-fault or core/SRAM proof')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');start=time.monotonic()
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True);fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('formal source changed')
            for tag in ['original-regression','baseline',*[row[0] for row in MUTATIONS],'read-payload']:
                content=original if tag=='original-regression' else fixed if tag=='baseline' else mutate(fixed,tag) if tag!='read-payload' else dict(fixed,**{'vortex_command_adapter.sv':drop_read_payload(fixed['vortex_command_adapter.sv'])})
                folder=work/tag;folder.mkdir()
                for name,text in content.items():(folder/name).write_text(text)
                for mode in (['bmc','cover'] if tag=='baseline' else ['bmc']):
                    config=f'[options]\nmode {mode}\ndepth 32\n[engines]\nsmtbmc boolector\n[script]\nread -formal '+' '.join(content)+'\nprep -top student_mini_gpu_adapters_harness\ndelete t:$print\n[files]\n'+'\n'.join(content)+'\n'
                    source=folder/(mode+'.sby');source.write_text(config)
                    with (folder/(mode+'.log')).open('x') as log:
                        code=subprocess.run([str(tools/'sby'),'-d',str(folder/mode),str(source)],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
                    path=folder/mode/'status';status=path.read_text().split()[0] if path.is_file() else 'ERROR'
                    expected='PASS' if tag=='baseline' else 'FAIL'
                    record=dict(name=tag,mode=mode,status=status,expected=expected,exit_code=code,accepted=status==expected)
                    result['records'].append(record);print(json.dumps(record),flush=True)
                    if not record['accepted']:raise ValueError('proof/regression/mutation did not match: '+tag)
            if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('formal source changed during proof')
        result.update(status='GPU_READ_PAYLOAD_PROTOCOL_STAGE_PASS',reason='Original read-payload bug reproduced; isolated correction passes strengthened 32-step contract, cover and nine mutations')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='GPU_READ_PAYLOAD_PROTOCOL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
