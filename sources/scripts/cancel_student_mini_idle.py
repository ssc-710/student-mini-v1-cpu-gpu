"""Cancel one explicitly identified, childless prerequisite waiter with receipt."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--script',required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--stage',required=True)
    parser.add_argument('--require-missing',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reason',default='Failing real-firmware transcript regression; replace only this newly created idle continuation')
    args=parser.parse_args()
    if args.pid<=1 or args.output.exists():raise ValueError('explicit live task and new receipt required')
    proc=Path('/proc')/str(args.pid)
    command=(proc/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    if len(command)<2 or command[0]!='python3' or command[1]!=args.script:
        raise ValueError('PID is not the exact selected producer')
    state=json.loads((args.work/'heartbeat.json').read_text())
    if state['stage']!=args.stage or not args.stage.startswith('WAITING_FOR_'):
        raise ValueError('producer is not the expected idle waiter')
    if args.require_missing.exists() or (args.work/'completion.json').exists():
        raise ValueError('prerequisite/producer completed; do not cancel')
    if (proc/'task'/str(args.pid)/'children').read_text().strip():raise ValueError('producer has active descendants')
    record=dict(status='CANCELLATION_REQUESTED',pid=args.pid,command=command,
        observed_idle_stage=state,reason=args.reason,
        created_at=datetime.now(timezone.utc).isoformat(),files_deleted=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as handle:json.dump(record,handle,indent=2)
    os.kill(args.pid,signal.SIGTERM)
    for _ in range(30):
        if not proc.exists():break
        time.sleep(.1)
    if proc.exists():raise RuntimeError('termination not yet observed')
    record['status']='IDLE_PRODUCER_TERMINATED';record['confirmed_at']=datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))


if __name__=='__main__':main()
