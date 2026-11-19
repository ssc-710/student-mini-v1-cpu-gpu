"""Wait for independent model audit, then export, C-check and run the GPU.

All expensive child producers own the common serial queue. Completion means
only a selected-model numerical session, never a complete student release.
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


def checked_audit(path):
    value=json.loads(path.read_text())
    if value.get('status')!='REFERENCE_QUALITY_STAGE_PASS' or value.get('accepted_sessions')!=0:
        raise ValueError('independent reference audit has not passed')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--quality-audit',type=Path,required=True)
    args=parser.parse_args();candidate=args.candidate.resolve();audit=args.quality_audit.resolve()
    names=('export_student_mini_selected_image.py','preflight_student_mini_selected_nano.py',
        'prepare_student_mini_native_gpu.py','run_student_mini_native_gpu.py','assemble_student_mini_selected_session.py')
    paths=[Path(__file__),candidate,*[ROOT/'scripts'/name for name in names]]
    bindings={str(p):sha(p) for p in paths};plan=dict(bindings=bindings,audit=str(audit))
    identity=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-nano-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(plan,indent=2)+'\n')
    start=time.monotonic();result=dict(status='HOLD',bindings=bindings,accepted_nano_session=False,release_complete=False,stages=[])
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('continuation input changed')
    def execute(index,arguments,label):
        fresh();heartbeat(label);log_path=work/(label+'.log')
        with log_path.open('x') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts'/names[index]),*map(str,arguments)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            try:
                while child.poll() is None:
                    if time.monotonic()-start>50000:raise TimeoutError('bounded continuation expired')
                    heartbeat(label);time.sleep(10)
            except BaseException:
                child.terminate()
                try:child.wait(timeout=30)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                raise
        if child.returncode:raise RuntimeError(label+' failed')
        value=json.loads(log_path.read_text().splitlines()[-1])
        result['stages'].append(dict(stage=label,receipt=value,log_sha256=sha(log_path)))
        print(json.dumps(dict(stage=label,receipt=value)),flush=True)
        return value
    try:
        heartbeat('WAITING_FOR_INDEPENDENT_QUALITY')
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_INDEPENDENT_QUALITY')),flush=True)
        while not audit.is_file():
            if time.monotonic()-start>43200:raise TimeoutError('quality audit wait expired')
            time.sleep(10)
        checked_audit(audit);bindings[str(audit)]=sha(audit)
        image=Path(execute(0,['--candidate',candidate,'--quality-audit',audit],'export')['work'])
        preflight=execute(1,['--candidate',candidate,'--image-dir',image],'c-preflight')
        if preflight['status']!='SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS':raise ValueError('C preflight not qualified')
        prepared=Path(execute(2,['--image-dir',image],'gpu-prepare')['work'])
        run=Path(execute(3,['--work',prepared],'gpu-execute')['work'])
        session=execute(4,['--run',run,'--image-dir',image,'--candidate',candidate,'--platform','gpu'],'gpu-join')
        fresh();result.update(status='SELECTED_GPU_NUMERICAL_STAGE_COMPLETE',image=str(image),session=session,
            reason='Actual SimX session joined to selected model; CPU/accelerator, hardware performance and final release gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='SELECTED_GPU_NUMERICAL_STAGE_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
