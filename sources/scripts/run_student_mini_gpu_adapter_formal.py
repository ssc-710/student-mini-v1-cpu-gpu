"""Bounded mini-width GPU adapter proof plus eight mutation checks; not a B0."""
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

MUTATIONS=[
 ('request-address','vortex_memory_adapter.sv','req_addr_q <= vx_req_addr_i;','req_addr_q <= vx_req_addr_i ^ 1;'),
 ('request-data','vortex_memory_adapter.sv','req_data_q <= vx_req_data_i;','req_data_q <= vx_req_data_i ^ 1;'),
 ('request-mask','vortex_memory_adapter.sv','req_byteen_q <= vx_req_byteen_i;','req_byteen_q <= vx_req_byteen_i ^ 1;'),
 ('response-tag','vortex_memory_adapter.sv','rsp_tag_q <= mem_rsp_tag_i;','rsp_tag_q <= mem_rsp_tag_i ^ 1;'),
 ('busy-start','vortex_command_adapter.sv','(host_cmd_kind_i != CMD_START || !busy_i)',"1'b1"),
 ('missing-error','vortex_command_adapter.sv',"response_error_q <= 1'b1;","response_error_q <= 1'b0;"),
 ('unstable-response','vortex_command_adapter.sv','host_rsp_valid_o = state_q == RESP;','host_rsp_valid_o = state_q == RESP && host_rsp_ready_i;'),
 ('dcr-address','vortex_command_adapter.sv','dcr_req_addr_o <= host_cmd_addr_i;','dcr_req_addr_o <= host_cmd_addr_i ^ 1;'),
]


def mutate(files,name):
    row=next(row for row in MUTATIONS if row[0]==name);_,filename,old,new=row
    expected=2 if name=='dcr-address' else 1
    if files[filename].count(old)!=expected:raise ValueError('mutation target multiplicity differs')
    result=dict(files);result[filename]=result[filename].replace(old,new)
    return result


def main():
    import fcntl
    names=['shared/rtl/vortex_command_adapter.sv','shared/rtl/vortex_memory_adapter.sv',
           'shared/formal/student_mini_gpu_adapters_harness.sv']
    toolroot=Path('/home/soclab/tools/oss-cad-suite/bin')
    paths=[ROOT/name for name in names]+[Path(__file__),ROOT/'shared/rtl/vortex_physical_top.sv']
    paths += [toolroot/name for name in ('yosys','sby','yosys-smtbmc','boolector')]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-adapter-formal'/identity;work.mkdir(parents=True,exist_ok=False)
    files={Path(name).name:(ROOT/name).read_text() for name in names}
    env=dict(os.environ,PATH=str(toolroot)+':/usr/local/bin:/usr/bin:/bin')
    result=dict(status='HOLD',formal_baseline=False,depth=32,ports=2,data_width=512,address_width=26,tag_width=10,
        scope='Physical command and memory skid adapters only; not Vortex core, SRAM equivalence or external DRAM fault injection',
        bindings=bindings,records=[])
    started=time.monotonic()
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('formal source changed while queued')
            for tag in ['baseline',*(row[0] for row in MUTATIONS)]:
                directory=work/tag;directory.mkdir()
                content=files if tag=='baseline' else mutate(files,tag)
                for name,text in content.items():(directory/name).write_text(text)
                for mode in (['bmc','cover'] if tag=='baseline' else ['bmc']):
                    config=f'[options]\nmode {mode}\ndepth 32\n[engines]\nsmtbmc boolector\n[script]\nread -formal '+' '.join(files)+'\nprep -top student_mini_gpu_adapters_harness\ndelete t:$print\n[files]\n'+'\n'.join(files)+'\n'
                    source=directory/(mode+'.sby');source.write_text(config)
                    with (directory/(mode+'.log')).open('x') as log:
                        code=subprocess.run([str(toolroot/'sby'),'-d',str(directory/mode),str(source)],
                            cwd=directory,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
                    status_path=directory/mode/'status'
                    status=status_path.read_text().split()[0] if status_path.is_file() else 'ERROR'
                    expected='PASS' if tag=='baseline' else 'FAIL'
                    record=dict(name=tag,mode=mode,status=status,expected=expected,exit_code=code,accepted=status==expected)
                    result['records'].append(record);print(json.dumps(record),flush=True)
                    if not record['accepted']:raise ValueError('formal or mutation expectation not met: '+tag)
            if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('formal source changed during proof')
            result.update(status='ADAPTER_PROTOCOL_STAGE_PASS',reason='32-step actual-width safety and reachability proved; eight mutations killed; whole-platform qualification remains separate')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='ADAPTER_PROTOCOL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
