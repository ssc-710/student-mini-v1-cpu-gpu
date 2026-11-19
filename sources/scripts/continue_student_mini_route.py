"""Continue a hash-verified mini placement, preserving its original evidence."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def main(work,timeout=1800):
    # 14400 s: a fresh P1 route (detailed route + antenna iterations + finish) does not fit in 7200 s (clean-20261014)
    if not 60<=timeout<=14400:raise ValueError('route timeout outside bounded range')
    parent=json.loads((work/'completion.json').read_text());inputs=json.loads((work/'inputs.json').read_text())
    if parent.get('placement_wns_ns',-1)<0 or inputs['clock_period_ns']!=10.:raise ValueError('placement preflight not passed at 10 ns')
    for name,digest in {**inputs['files'],**parent['artifacts']}.items():
        if sha(Path(name))!=digest:raise ValueError('stale placement/source artifact: '+name)
    out=work/'route';out.mkdir(exist_ok=False)
    result_dir=Path(parent['result_directory']);log_dir=Path(parent['metrics_directory'])
    # log_dir = <orfs>/flow/logs/sky130hd/<design>/<variant>
    orfs=log_dir.parents[4]
    tools={Path(name).name:Path(name) for name in inputs['files'] if Path(name).name in ('openroad','yosys')}
    command=['make','-C',str(orfs/'flow'),'route','do-finish',f'DESIGN_CONFIG={work}/config.mk',f'COURSE_ROOT={ROOT}',f'FLOW_VARIANT={result_dir.name}',f'OPENROAD_EXE={tools["openroad"]}',f'YOSYS_EXE={tools["yosys"]}','NUM_CORES=2']
    bindings={str(work/'completion.json'):sha(work/'completion.json'),str(Path(__file__)):sha(Path(__file__))}
    (out/'inputs.json').write_text(json.dumps(dict(command=command,bindings=bindings,timeout_seconds=timeout,parent_input_sha256=parent['input_sha256']),indent=2)+'\n')
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2]);child=None;started=time.monotonic()
    result=dict(status='HOLD',physical_evidence_complete=False,parent_input_sha256=parent['input_sha256'],clock_period_ns=10.)
    try:
        Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').parent.mkdir(parents=True,exist_ok=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(out),status='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(p))!=digest for p,digest in inputs['files'].items()):raise ValueError('source changed while queued')
            with (out/'route.log').open('w') as log:
                child=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                print(json.dumps(dict(work=str(out),status='ROUTING',pid=child.pid)),flush=True)
                result['exit_code']=child.wait(timeout=timeout)
            result['reason']='Route finished; inspect final timing/DRC/antenna and collect per-load activity power' if not result['exit_code'] else 'Route failed; see bound route.log'
            metrics=log_dir/'6_report.json'
            if metrics.is_file():result['metrics']=json.loads(metrics.read_text())
            if any(sha(Path(p))!=digest for p,digest in inputs['files'].items()):raise ValueError('source changed during route')
            result['source_freshness_verified']=True
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
        result['elapsed_seconds']=time.monotonic()-started
        report_dir=orfs/'flow/reports/sky130hd'/result_dir.parent.name/result_dir.name
        result['artifacts']={str(p):sha(p) for folder in (out,result_dir,log_dir,report_dir) if folder.exists() for p in folder.iterdir() if p.is_file()}
        (out/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(work=str(out),**{k:v for k,v in result.items() if k not in ('artifacts','metrics')})),flush=True)
    return result.get('exit_code',1)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--placement',type=Path,required=True);parser.add_argument('--timeout',type=int,default=1800);args=parser.parse_args();raise SystemExit(main(args.placement.resolve(),args.timeout))
