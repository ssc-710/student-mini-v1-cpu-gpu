"""Prepare ASIC reset/storage only after the same-ROM CPU boundary completes.

Does not claim reset equivalence, SRAM mapping, physical signoff, or baseline.
The reset producer takes the shared serial EDA lock itself.
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


def check_boundary(parent,root):
    if parent.get('extraction_complete') is not True:
        raise ValueError('same-ROM boundary extraction incomplete')
    bindings=parent.get('bindings',{})
    if not bindings or any(sha(Path(p))!=value for p,value in bindings.items()):
        raise ValueError('boundary source changed')
    for name in ('boundary.v','boundary.json'):
        if parent.get('artifacts',{}).get(name)!=sha(root/name):
            raise ValueError('boundary artifact changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=43200)
    args=parser.parse_args()
    if not 0<=args.wait_seconds<=43200:raise ValueError('bounded wait required')
    boundary=args.boundary.resolve()
    producer=ROOT/'scripts/prepare_student_mini_cpu_reset_boundary.py'
    paths=(Path(__file__),producer,ROOT/'scripts/student_mini.py',ROOT/'scripts/export_student_mini_combined_cpu_boundary.py')
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(dict(boundary=str(boundary),bindings=bindings),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-reset-continuation'/identity
    work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,
        reset_equivalence=False,bindings=bindings,parent=str(boundary))
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('reset continuation source changed')
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SAME_ROM_BOUNDARY')),flush=True)
        while not (boundary/'completion.json').exists():
            heartbeat('WAITING_FOR_SAME_ROM_BOUNDARY')
            if time.monotonic()-started>args.wait_seconds:raise TimeoutError('boundary wait expired')
            time.sleep(10)
        fresh()
        parent=json.loads((boundary/'completion.json').read_text())
        check_boundary(parent,boundary)
        result['parent_completion_sha256']=sha(boundary/'completion.json')
        heartbeat('RESET_PRODUCER_SERIAL_QUEUE')
        # The outer resource guard bounds this process tree, including the EDA wait.
        with (work/'reset-producer.log').open('x') as log:
            code=subprocess.run([sys.executable,str(producer),'--boundary',str(boundary)],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=43800).returncode
        if code:raise RuntimeError('reset projection failed; see reset-producer.log')
        record=json.loads((work/'reset-producer.log').read_text().splitlines()[-1])
        output=Path(record['work'])/'completion.json'
        completed=json.loads(output.read_text())
        if completed.get('boundary_complete') is not True or completed.get('reset_equivalence') is not False:
            raise ValueError('unexpected reset producer result')
        fresh();check_boundary(parent,boundary)
        if sha(boundary/'completion.json')!=result['parent_completion_sha256']:raise ValueError('parent completion changed')
        result.update(status='RESET_STORAGE_PROJECTION_STAGE_PASS',output=str(output),output_sha256=sha(output),
            reason='Exact executed-ROM ASIC reset entry and storage inventory prepared; equivalence, mapping and physical gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status'])
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='RESET_STORAGE_PROJECTION_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
