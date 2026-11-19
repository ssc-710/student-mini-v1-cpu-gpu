"""One preregistered training-budget retry, never automatic model replacement.

Only FP32 step budget changes (1500 -> 3000). Seed, dataset, architecture,
quantization, QAT budget and validation-based checkpoint selection stay fixed.
The previously observed test report is a regression set, not a fresh blind test.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route


def validate_parent(candidate,inputs):
    if (inputs.get('steps'),inputs.get('qat_steps'),inputs.get('seed'),inputs.get('device'))!=(1500,500,1,'cpu'):
        raise ValueError('unexpected parent training configuration')
    if candidate.get('parameters')!=11344 or candidate.get('target_execution') is not False:
        raise ValueError('unexpected native reference parent')
    if candidate.get('bindings')!=inputs.get('bindings'):raise ValueError('training source binding mismatch')


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--teacher-python',type=Path,required=True)
    args=parser.parse_args()
    parent=args.parent.resolve();python=args.teacher_python.absolute()
    previous=json.loads((parent/'candidate.json').read_text());original=json.loads((parent/'inputs.json').read_text())
    validate_parent(previous,original)
    bindings=dict(previous['bindings'])
    paths=(Path(__file__),ROOT/'scripts/retry_student_mini_route.py',parent/'candidate.json',parent/'inputs.json',python,
        ROOT/'build/student-mini/teacher-cpu-env-20261007/teacher-lock.json',
        ROOT/'build/student-mini/teacher-qualification-20261008/qualification.json')
    bindings.update({str(p):sha(p) for p in paths})
    plan=dict(bindings=bindings,parent=str(parent),changed_variable='fp32_step_budget',
        parent_steps=1500,steps=3000,qat_steps=500,seed=1,
        checkpoint_selection='Existing validation-only rule, unchanged; no test-driven candidate choice',
        test_disclosure='Prior twelve-question results already inspected. Retest is regression, not new blind generalization evidence.',
        maximum_attempts=1,automatic_platform_model_replacement=False)
    identity=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/training-budget-retry'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'preregistered-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    result=dict(status='HOLD',accepted_nano_session=False,release_complete=False,bindings=bindings)
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('training retry source changed')
    try:
        fresh()
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            command=[str(python),str(ROOT/'scripts/train_student_mini_native_nano.py'),'--steps','3000','--qat-steps','500']
            code=execute_locked_route(command,work/'training.log',1200,lambda _:heartbeat('TRAINING_REFERENCE_CANDIDATE'))
            if code:raise RuntimeError('single training attempt failed; see training.log')
            record=json.loads((work/'training.log').read_text().splitlines()[-1])
            candidate_path=Path(record['work'])/'candidate.json';new=json.loads(candidate_path.read_text())
            new_inputs=json.loads((candidate_path.parent/'inputs.json').read_text())
            if any(new_inputs.get(key)!=original.get(key) for key in ('bindings','seed','device','torch_version','dataset','tokenizer')):
                raise ValueError('training changed more than the declared budget')
            if (new_inputs['steps'],new_inputs['qat_steps'])!=(3000,500):raise ValueError('wrong retry budget')
            fresh()
            result.update(status='REFERENCE_TRAINING_ATTEMPT_COMPLETE',candidate=str(candidate_path),candidate_sha256=sha(candidate_path),
                regression_counts={key:sum(row['passed'] for row in values) for key,values in new['quality'].items()},
                reason='Single declared budget experiment recorded; no automatic selection or target/quality acceptance')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='REFERENCE_TRAINING_ATTEMPT_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
