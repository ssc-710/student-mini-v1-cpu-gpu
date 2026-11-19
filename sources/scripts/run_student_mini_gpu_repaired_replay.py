"""Full representative replay of the exact private 30-cycle repaired GPU."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source,root):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'from scripts.student_mini_gpu_constant_calls import lower_scheduler_constants':
        'from scripts.student_mini_gpu_constant_calls import lower_scheduler_constants\nfrom scripts.student_mini_gpu_host_handshake import drain_read_response',
        "top,_=rename_modules((ROOT/'shared/rtl/vortex_physical_top.sv').read_text(),mapping)":
        "top,_=rename_modules((boundary/'vortex_physical_top.sv').read_text(),mapping)",
        "extra.extend(ROOT/'shared/rtl'/name for name in ('vortex_command_adapter.sv','vortex_memory_adapter.sv','vortex_banked_large_sram_wrappers.sv'))":
        "extra.append(boundary/'vortex_command_adapter.sv')\n    extra.extend(ROOT/'shared/rtl'/name for name in ('vortex_memory_adapter.sv','vortex_banked_large_sram_wrappers.sv'))",
        "(private/'processor.cpp').write_text(timing_processor((source/'sim/rtlsim/processor.cpp').read_text()))":
        "(private/'processor.cpp').write_text(drain_read_response(timing_processor((source/'sim/rtlsim/processor.cpp').read_text())))",
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/run_student_mini_gpu_repaired_replay.py',ROOT/'scripts/run_student_mini_gpu_physical_replay.py',ROOT/'scripts/student_mini_gpu_host_handshake.py',boundary/'vortex_physical_top.sv',boundary/'vortex_command_adapter.sv',",
        "THREADS='2',VORTEX_PROFILING='0')":"THREADS='2',VORTEX_PROFILING='0',VORTEX_CP_POLL_TIMEOUT_S='120')",
        'plan=dict(bindings=bindings,ordinals=':"plan=dict(candidate='private 30-cycle core with scoped SRAM/DCR/port corrections and host response handshake',bindings=bindings,ordinals=",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('repaired replay source seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('boundary','functional-parent','functional-report'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();boundary=args.boundary.resolve();parent=json.loads((boundary/'completion.json').read_text())
    if parent['status']!='GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS' or parent['arithmetic_latency']!=30 or parent['boundary_complete'] is not True:
        raise ValueError('all scoped repairs must be bound to the 30-cycle physical RTL')
    bindings=dict(parent['bindings'])
    for name,digest in parent['artifacts'].items():
        path=boundary/name
        if sha(path)!=digest:raise ValueError('repaired boundary artifact changed')
        bindings[str(path)]=digest
    original=ROOT/'scripts/run_student_mini_gpu_physical_replay.py'
    paths=[Path(__file__),original,boundary/'completion.json',ROOT/'scripts/student_mini_gpu_host_handshake.py',
        ROOT/'tests/test_student_mini_gpu_host_handshake.py',ROOT/'tests/rtl/student_mini_gpu_host_read.sv',ROOT/'tests/rtl/student_mini_gpu_port_packing.sv']
    bindings.update({str(p):sha(p) for p in paths});verify(bindings)
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,inputs={k:str(v.resolve()) for k,v in vars(args).items()}),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-repaired-replay-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings,arithmetic_latency=30,old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),stage='REPAIRED_GPU_REPLAY_QUEUED')),flush=True)
    with (work/'regression.log').open('x') as log:code=subprocess.call([sys.executable,'-m','pytest','-q','tests/test_student_mini_gpu_host_handshake.py'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if code:raise ValueError('host handshake regression failed')
    verify(bindings);command=[sys.executable,str(producer)]
    for name in ('boundary','functional_parent','functional_report'):command+=['--'+name.replace('_','-'),str(getattr(args,name).resolve())]
    with (work/'replay.log').open('x') as log:code=subprocess.call(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    lines=[json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
    if lines:result['replay']=lines[-1]
    verify(bindings)
    if code==0 and result.get('replay',{}).get('status')=='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS':result['status']='REPAIRED_30_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS'
    result['reason']='Actual repaired RTL; three representative outputs only, not all counters, protocol, physical or release acceptance'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'])),flush=True)
    return 0 if result['status']=='REPAIRED_30_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
