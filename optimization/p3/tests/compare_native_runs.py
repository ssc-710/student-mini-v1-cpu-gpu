"""Compare executed native tokens/states, binding the real experiment files."""
import argparse
import hashlib
import json
from pathlib import Path
import re

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
p=argparse.ArgumentParser();p.add_argument('--cpu',action='store_true');args=p.parse_args()
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
def read(path,platform):
    text=path.read_text(errors='replace')
    records=[]
    for line in text.splitlines():
        if line.startswith('STUDENT_NATIVE_TOKEN '):
            fields=dict(re.findall(r'(\w+)=([^ ]+)',line))
            records.append({k:fields[k] for k in ['step','token','hidden','logits']})
    assert len(records)==11 and [int(r['step']) for r in records]==list(range(11))
    assert text.count('STUDENT_NATIVE_'+platform+'_COMPLETE count=11 p1=1 p2=10 p3=40')==1
    assert len(re.findall(r'\bhidden=',text))==11
    assert all(len(r['hidden'].split(','))==16 and len(r['logits'].split(','))==256 for r in records)
    assert text.count('STUDENT_NATIVE_'+platform+' status=0 count=11')==1
    result=dict(records=records,log_sha256=sha(path))
    if platform=='CPU':
        m=re.search(r'STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+)',text);assert m
        result['generation_cycles']=(int(m[1])<<32)+int(m[2])
        m=re.search(r'STUDENT_NATIVE_OPERATOR op=3 cycles=(\d+):(\d+)',text);assert m
        result['p3_cycles']=(int(m[1])<<32)+int(m[2])
    else:
        m=re.search(r'P3_HOST_TIMING kernel_sync_seconds=([\d.]+) qa_compute_readback_seconds=([\d.]+)',text);assert m
        result.update(kernel_sync_seconds=float(m[1]),qa_compute_readback_seconds=float(m[2]))
        m=re.search(r'PERF: instrs=(\d+), cycles=(\d+)',text);assert m
        result.update(aggregate_instrs=int(m[1]),aggregate_cycles=int(m[2]))
    return result
platform='CPU' if args.cpu else 'GPU'
if args.cpu:
    baseline=BASE/'runs/cpu-baseline-diagnostic.log';candidate=BASE/'runs/cpu-algorithm-diagnostic.log'
    files=[BASE/'build/cpu-algorithm/bios/student_mini_native_nano.c',BASE/'build/cpu-algorithm/bios/student_mini_native_session.c',
        BASE/'build/cpu-algorithm/soc/software/bios/bios.bin',BASE/'build/cpu-algorithm/soc/gateware/obj_dir/Vsim']
else:
    baseline=BASE/'runs/gpu-baseline-driver-retry/execute.log';candidate=BASE/'runs/gpu-algorithm-abs-fix/execute.log'
    files=[BASE/'build/gpu-algorithm'/n for n in ['native_nano.cu','native_nano','Makefile','device_compat.cc']]
    files.append(BASE/'build/gpu-baseline/vortex-build/sw/runtime/libvortex-simx.so')
    files.extend(BASE/'build/gpu-baseline'/n for n in ['native_nano.cu','native_nano','Makefile','device_compat.cc'])
a=read(baseline,platform);b=read(candidate,platform)
assert a['records']==b['records'],'Native token/hidden/logits mismatch'
files+=[baseline,candidate,BASE/'src/p3_native_candidate.c',ROOT/'rerun_sqrt5/image/image.bin']
result=dict(status='NATIVE_DIAGNOSTIC_EXACT_PASS',platform=platform,token_ids=[int(r['token']) for r in b['records']],
    executed_candidate_input_sha256='587d8f52eecd9e180757a06b4ba0c946b5489dbac29c5782e607064bb842bb0d',
    source_note='Current private helper has a domain-only comment change after these runs; exact executed overlay/CU are independently bound below.',
    baseline={k:v for k,v in a.items() if k!='records'},candidate={k:v for k,v in b.items() if k!='records'},
    bindings={str(path.relative_to(ROOT)):sha(path) for path in files},
    limitation='One diagnostic run, not repeated clean-mode performance or full 330-case/protocol/physical qualification. GPU aggregate cycles include runtime, not isolated P3.')
if args.cpu:
    result['generation_speedup']=a['generation_cycles']/b['generation_cycles']
    result['p3_speedup']=a['p3_cycles']/b['p3_cycles']
else:result['aggregate_cycle_ratio']=a['aggregate_cycles']/b['aggregate_cycles']
out=BASE/'runs'/('native-'+platform.lower()+'-comparison.json')
out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
