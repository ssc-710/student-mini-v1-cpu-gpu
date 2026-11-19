"""Collect numerical evidence after the exact combined CPU replay completes.

No physical or model-quality gate is granted by this lightweight continuation.
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('cpu-run','image-dir','candidate','vectors'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=43200)
    args=parser.parse_args()
    if not 0<=args.wait_seconds<=43200:raise ValueError('bounded wait required')
    run=args.cpu_run.resolve();image=args.image_dir.resolve()
    paths=[Path(__file__),run/'inputs.json',image/'manifest.json',args.candidate.resolve(),args.vectors.resolve()]
    paths += [ROOT/'scripts'/name for name in ('assemble_student_mini_combined_cpu_results.py',
        'assemble_student_mini_cpu_results.py','assemble_student_mini_native_session.py','export_student_mini_combined_cpu_boundary.py','student_mini.py')]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-evidence-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',formal_baseline=False,accepted_nano_session=False,bindings=bindings,records=[])
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('evidence source changed')
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_CPU_REPLAY')),flush=True)
        while not (run/'completion.json').is_file():
            heartbeat('WAITING_FOR_CPU_REPLAY')
            if time.monotonic()-started>args.wait_seconds:raise TimeoutError('CPU evidence wait expired')
            time.sleep(10)
        fresh()
        if json.loads((run/'completion.json').read_text()).get('target_run_complete') is not True:
            raise ValueError('actual combined CPU replay did not complete')
        commands={
            'baseline':[sys.executable,str(ROOT/'scripts/assemble_student_mini_combined_cpu_results.py'),
                '--vectors',str(args.vectors.resolve()),'--work',str(run),'--image-dir',str(image)],
            'nano':[sys.executable,str(ROOT/'scripts/assemble_student_mini_native_session.py'),
                '--platform','cpu','--run',str(run),'--image-dir',str(image),'--candidate',str(args.candidate.resolve())],
        }
        for name,command in commands.items():
            heartbeat('VERIFYING_'+name.upper())
            with (work/(name+'.log')).open('x') as log:
                code=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
            if code:raise RuntimeError(name+' numerical join failed')
            output=json.loads((work/(name+'.log')).read_text().splitlines()[-1])
            if sha(Path(output['path']))!=output['sha256']:raise ValueError('numerical result changed')
            result['records'].append(dict(stage=name,**output))
        fresh();result.update(status='SINGLE_ROM_NUMERICAL_EVIDENCE_STAGE_PASS',reason='Baseline and full-state Nano joins completed; correctness gaps, physical and quality gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='SINGLE_ROM_NUMERICAL_EVIDENCE_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
