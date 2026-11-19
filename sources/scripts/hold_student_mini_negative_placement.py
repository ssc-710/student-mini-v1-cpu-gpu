"""Stop this owned GPU preflight after post-repair negative 100 MHz WNS.

The existing producer's SIGTERM handler reaps its tool process group and writes
its normal HOLD receipt. No files or other jobs are removed or terminated.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def check_request(command,parent,metrics):
    expected='scripts/recover_student_mini_gpu_macro_names.py'
    if len(command)!=4 or command[1]!=expected or command[2]!='--failed-preflight':
        raise ValueError('not the owned GPU macro-name preflight')
    if Path(command[3]).resolve()!=Path(parent).resolve():raise ValueError('producer parent differs')
    wns=metrics.get('placeopt__timing__setup__ws')
    if type(wns) not in (int,float) or not math.isfinite(wns) or wns>=0:
        raise ValueError('post-repair negative WNS required')
    return wns


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True);parser.add_argument('--pid',type=int,required=True)
    args=parser.parse_args();work=args.work.resolve()
    if (work/'completion.json').exists():raise ValueError('already completed; do not signal')
    inputs=json.loads((work/'inputs.json').read_text())
    if inputs['clock_period_ns']!=10:raise ValueError('different clock')
    proc=Path('/proc')/str(args.pid)
    command=proc.joinpath('cmdline').read_bytes().decode().rstrip('\0').split('\0')
    if proc.joinpath('cwd').resolve()!=ROOT:raise ValueError('producer cwd differs')
    variant='student-mini-gpu-names-'+work.name[:16]
    metric=Path('/home/soclab/src/orfs-clean-aabf2a/flow/logs/sky130hd/vortex_physical_top')/variant/'3_4_place_resized.json'
    report=Path('/home/soclab/src/orfs-clean-aabf2a/flow/reports/sky130hd/vortex_physical_top')/variant/'3_resizer.rpt'
    wns=check_request(command,inputs['parent'],json.loads(metric.read_text()))
    producer=ROOT/command[1]
    if inputs['bindings'].get(str(producer))!=sha(producer):raise ValueError('producer source differs')
    status=proc.joinpath('status').read_text()
    caught=int(next(line.split()[1] for line in status.splitlines() if line.startswith('SigCgt:')),16)
    if not caught & (1<<(signal.SIGTERM-1)):raise ValueError('producer has no cleanup signal handler')
    start=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]
    files=[Path(__file__),work/'inputs.json',metric,report,producer]
    record=dict(status='NEGATIVE_TIMING_HOLD_REQUESTED',pid=args.pid,start_tick=start,
        command=command,wns_ns=wns,clock_period_ns=10,files_deleted=False,
        reason='Post-repair placement WNS fails frozen 100 MHz; stop further legalization, do not route',
        created_at=datetime.now(timezone.utc).isoformat(),bindings={str(p):sha(p) for p in files})
    identity=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
    out=ROOT/'grading/evidence/student-mini-v1/interventions'/identity;out.mkdir(parents=True,exist_ok=False)
    (out/'request.json').write_text(json.dumps(record,indent=2)+'\n')
    # Recheck process identity immediately before signalling this one process.
    if proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]!=start:raise ValueError('PID reused')
    os.kill(args.pid,signal.SIGTERM)
    for _ in range(50):
        if (work/'completion.json').exists():break
        time.sleep(1)
    if (work/'completion.json').exists():
        done=json.loads((work/'completion.json').read_text())
        if done.get('preflight_complete') is not False:raise ValueError('unexpected preflight result')
        record.update(status='NEGATIVE_TIMING_HOLD_RECORDED',completion_sha256=sha(work/'completion.json'),
            producer_reason=done.get('reason'))
    (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(output=str(out),status=record['status'],wns_ns=wns)),flush=True)
    return 0 if record['status']=='NEGATIVE_TIMING_HOLD_RECORDED' else 1


if __name__=='__main__':raise SystemExit(main())
