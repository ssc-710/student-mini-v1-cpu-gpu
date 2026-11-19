"""Fresh physical preflight bound to the replayed three-stage integer multiplier."""
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
from scripts.continue_student_mini_gpu_sign_chain import derive as sign_chain


def derive(source,root):
    value=sign_chain(source,root)
    changes={
        "parent['status'] != 'GPU_SIGN_REPRESENTATIVE_REPLAY_STAGE_PASS'":"parent['status'] != 'GPU_MULTIPLIER_REPRESENTATIVE_REPLAY_STAGE_PASS' or parent.get('integer_multiplier_latency') != 3",
        "'build/student-mini/gpu-sign-physical-continuation'":"'build/student-mini/gpu-multiplier-physical-continuation'",
        "'GPU_SIGN_PHYSICAL_PREFLIGHT_STAGE_PASS'":"'GPU_MULTIPLIER_PHYSICAL_PREFLIGHT_STAGE_PASS'",
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_gpu_multiplier_physical.py',",
        'physical_evidence_complete=False, arithmetic_latency=57)':'physical_evidence_complete=False, arithmetic_latency=57, integer_multiplier_latency=3)',
    }
    for old,new in changes.items():
        expected=2 if old=="'GPU_SIGN_PHYSICAL_PREFLIGHT_STAGE_PASS'" else 1
        if value.count(old)!=expected:raise ValueError('multiplier physical seam changed: '+old)
        value=value.replace(old,new)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-continuation',type=Path,required=True);args=parser.parse_args()
    original=ROOT/'scripts/continue_student_mini_gpu_nrm_physical.py'
    paths=[Path(__file__),original,ROOT/'scripts/continue_student_mini_gpu_sign_chain.py',args.replay_continuation.resolve()/'completion.json']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-multiplier-physical-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private=work/'producer.py';private.write_text(derive(original.read_text(),ROOT));bindings[str(private)]=sha(private)
    result=dict(status='HOLD',bindings=bindings,arithmetic_latency=57,integer_multiplier_latency=3,
                physical_evidence_complete=False,formal_baseline=False,old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='MULTIPLIER_PHYSICAL_QUEUED')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--replay-continuation',str(args.replay_continuation.resolve())],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='GPU_MULTIPLIER_PHYSICAL_PREFLIGHT_STAGE_PASS':
        result['status']='GPU_MULTIPLIER_PHYSICAL_LAUNCH_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
