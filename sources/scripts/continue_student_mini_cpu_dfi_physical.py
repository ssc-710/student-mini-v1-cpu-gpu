"""Continue only from a complete newly executed DFI-latency CPU replay."""
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
from scripts.continue_student_mini_cpu_request_physical import synthesis_source as request_synthesis


def synthesis_source(source,root):
    value=request_synthesis(source,root)
    old="parent['status']!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'"
    if value.count(old)!=1:raise ValueError('DFI synthesis status seam changed')
    value=value.replace(old,"parent['status']!='CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS' or parent.get('dfi_output_latency_cycles')!=1")
    old='paths=[Path(__file__),'
    if value.count(old)!=1:raise ValueError('DFI synthesis binding seam changed')
    return value.replace(old,old+"ROOT/'scripts/continue_student_mini_cpu_dfi_physical.py',")


def derive(source,root):
    # Preserve the actual original main workflow; replace its imported synthesis
    # projector instead of text-rewriting string literals inside that projector.
    begin=source.index('def synthesis_source(');end=source.index('def main():',begin)
    value=source[:begin]+'from scripts.continue_student_mini_cpu_dfi_physical import synthesis_source\n\n\n'+source[end:]
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/continue_student_mini_cpu_dfi_physical.py',ROOT/'scripts/continue_student_mini_cpu_request_physical.py',",
        "'build/student-mini/cpu-request-physical-continuation'":"'build/student-mini/cpu-dfi-physical-continuation'",
        'read_latency_cycles=2)':'read_latency_cycles=2,dfi_output_latency_cycles=1)',
        "'CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS'":"'CPU_DFI_OUTPUT_FULL_REPLAY_STAGE_PASS'",
        "'CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS'":"'CPU_DFI_OUTPUT_PHYSICAL_PREFLIGHT_STAGE_PASS'",
        'Independently replayed two-edge ROM CPU passed synthesis and 100 MHz placement; route, power and protocol remain':
        'Independently replayed two-edge ROM and one-edge complete DFI output CPU passed synthesis and 100 MHz placement; route, power and protocol remain',
    }
    for old,new in changes.items():
        expected=2 if old=="'CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS'" else 1
        if value.count(old)!=expected:raise ValueError('DFI physical continuation seam changed: '+old)
        value=value.replace(old,new)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-continuation',type=Path,required=True);args=parser.parse_args()
    original=ROOT/'scripts/continue_student_mini_cpu_request_physical.py'
    paths=[Path(__file__),original,args.replay_continuation.resolve()/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-physical-launch'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_COMPLETE_DFI_REPLAY')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--replay-continuation',str(args.replay_continuation.resolve())],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='CPU_DFI_OUTPUT_PHYSICAL_PREFLIGHT_STAGE_PASS':
        result['status']='CPU_DFI_PHYSICAL_LAUNCH_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
