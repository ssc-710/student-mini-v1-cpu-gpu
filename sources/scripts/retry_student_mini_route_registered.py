"""Register a bounded blocking route waiter; preserve existing bound producers.

The original nonblocking retry is retained as historical evidence. This distinct
entry binds itself and the unchanged checkpoint/execution helper into a new hash.
It neither preempts the active job nor promises FIFO ordering from Linux flock.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import signal
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import checked_parent, execute_locked_route, verify, TARGETS


def acquire_registered(lock, timeout):
    import fcntl
    if type(timeout) is not int or not 1 <= timeout <= 43200:
        raise ValueError('bounded queue timeout required')
    def expired(signum,frame): raise TimeoutError('registered queue wait expired')
    previous=signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM,expired)
    signal.alarm(timeout)
    try: fcntl.flock(lock,fcntl.LOCK_EX)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,previous)


def prepare(placement,timeout,output_root):
    source,parent,route,checkpoint=checked_parent(placement,timeout)
    bindings=dict(source['files'],**checkpoint)
    for path in (Path(__file__),ROOT/'scripts/retry_student_mini_route.py',
                 placement/'inputs.json',placement/'completion.json',
                 placement/'config.mk',placement/'route/completion.json'):
        bindings[str(path)]=sha(path)
    inputs=dict(source,files=bindings,stage='registered-route-retry-from-global-route',
        recovery=dict(parent_input_sha256=placement.name,previous_reason=route['reason'],
            timeout_seconds=timeout,targets=list(TARGETS),queue_mode='bounded blocking flock',
            unchanged_design_config_sha256=sha(placement/'config.mk')))
    identity=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    work=output_root/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    shutil.copyfile(placement/'config.mk',work/'config.mk')
    variant='student-mini-registered-'+identity[:16]
    result_dir=Path(parent['result_directory']).parent/variant
    log_dir=Path(parent['metrics_directory']).parent/variant
    derived=dict(status='HOLD',physical_evidence_complete=False,profile='mini',operator=parent['operator'],
        input_sha256=identity,clock_period_ns=10.,placement_wns_ns=parent['placement_wns_ns'],
        placement_reused_from=str(placement),reason='Unchanged placement; registered route retry pending',
        result_directory=str(result_dir),metrics_directory=str(log_dir),
        artifacts={str(p):sha(p) for p in (work/'inputs.json',work/'config.mk')})
    (work/'completion.json').write_text(json.dumps(derived,indent=2)+'\n')
    return work,inputs,result_dir,log_dir,checkpoint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=10800)
    parser.add_argument('--queue-timeout',type=int,default=43200)
    args=parser.parse_args()
    work,inputs,result_dir,log_dir,checkpoint=prepare(args.placement.resolve(),args.timeout,ROOT/'build/student-mini/registered-route-retries')
    out=work/'route';out.mkdir()
    orfs=log_dir.parents[4]
    reports=orfs/'flow/reports/sky130hd'/result_dir.parent.name/result_dir.name
    tools={Path(p).name:p for p in inputs['files'] if Path(p).name in ('openroad','yosys')}
    command=['make','-C',str(orfs/'flow'),*TARGETS,f'DESIGN_CONFIG={work}/config.mk',f'COURSE_ROOT={ROOT}',
        f'FLOW_VARIANT={result_dir.name}',f'OPENROAD_EXE={tools["openroad"]}',f'YOSYS_EXE={tools["yosys"]}','NUM_CORES=2']
    (out/'inputs.json').write_text(json.dumps(dict(command=command,timeout_seconds=args.timeout,parent_input_sha256=work.name,
        bindings={str(p):sha(p) for p in (work/'inputs.json',work/'completion.json',work/'config.mk')}),indent=2)+'\n')
    result=dict(status='HOLD',physical_evidence_complete=False,parent_input_sha256=work.name,clock_period_ns=10.,
        previous_hold=str(args.placement.resolve()/'route/completion.json'))
    started=time.monotonic()
    def heartbeat(stage):
        (out/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=time.monotonic()-started))+'\n')
    def interrupted(signum,frame): raise InterruptedError('registered retry termination requested')
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_REGISTERED_QUEUE')
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_REGISTERED_QUEUE')),flush=True)
            acquire_registered(lock,args.queue_timeout)
            result['queue_seconds']=time.monotonic()-started
            verify(inputs['files'])
            for directory in (result_dir,log_dir,reports):directory.mkdir(parents=True,exist_ok=False)
            for path,digest in checkpoint.items():
                destination=result_dir/Path(path).name;shutil.copyfile(path,destination)
                if sha(destination)!=digest:raise ValueError('checkpoint copy differs')
            begin=time.monotonic()
            code=execute_locked_route(command,out/'route.log',args.timeout,heartbeat)
            result.update(exit_code=code,route_elapsed_seconds=time.monotonic()-begin,
                reason='Route finished; independent signoff remains' if code==0 else 'Route failed; inspect bound log')
            metrics=log_dir/'6_report.json'
            if metrics.is_file():result['metrics']=json.loads(metrics.read_text())
            verify(inputs['files']);result['source_freshness_verified']=True
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    finally:
        signal.signal(signal.SIGTERM,previous)
        result['elapsed_seconds']=time.monotonic()-started
        heartbeat('FINISHED' if result.get('exit_code')==0 else 'HOLD')
        result['artifacts']={str(p):sha(p) for folder in (out,result_dir,log_dir,reports) if folder.exists() for p in folder.iterdir() if p.is_file()}
        (out/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(work=str(work),exit_code=result.get('exit_code'),reason=result['reason'])),flush=True)
    return result.get('exit_code',1)


if __name__=='__main__':raise SystemExit(main())
