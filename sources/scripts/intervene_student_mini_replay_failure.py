"""Stop an owned DFI replay after its actual firmware reports Nano failure."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def failure(line):
    match=re.fullmatch(r'STUDENT_NATIVE_CPU status=(-?\d+) count=(\d+) cycles=\d+:\d+ instructions=\d+:\d+ ibus_bytes=\d+:\d+ dbus_bytes=\d+:\d+ dma_bytes=\d+:\d+',line)
    if not match or int(match[1])==0 or int(match[2])!=0:raise ValueError('actual explicit failed Nano execution required')
    return int(match[1])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,required=True);parser.add_argument('--continuation',type=Path,required=True)
    args=parser.parse_args();replay=args.replay.resolve();continuation=args.continuation.resolve()
    if (replay.parent!=ROOT/'build/student-mini/cpu-boundary-replay'
        or continuation.parent!=ROOT/'build/student-mini/cpu-dfi-replay-continuation'
        or (replay/'completion.json').exists()):raise ValueError('owned active DFI replay only')
    inputs=json.loads((continuation/'inputs.json').read_text());verify(inputs['bindings'])
    producer=continuation/'producer.py'
    if inputs['bindings'].get(str(producer))!=sha(producer):raise ValueError('actual producer not bound')
    rows=[json.loads(x) for x in (continuation/'replay.log').read_text().splitlines() if x.startswith('{')]
    if not rows or rows[0].get('work')!=str(replay):raise ValueError('actual child directory differs')
    witness=None
    with (replay/'console.log').open(errors='replace') as stream:
        for line in stream:
            if line.startswith('STUDENT_NATIVE_CPU status='):
                failure(line.rstrip('\n'));witness=line.rstrip('\n');break
    if witness is None:raise ValueError('no terminal failure witness; no signal sent')
    matches=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():continue
        try:argv=(process/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        if len(argv)>2 and argv[1].decode(errors='replace')==str(producer):matches.append((int(process.name),argv))
    if len(matches)!=1:raise ValueError('unique live owned producer required')
    pid,argv=matches[0]
    if b'--mapping' not in argv or b'--cpu-run' not in argv:raise ValueError('unexpected process arguments')
    bindings={str(p):sha(p) for p in (Path(__file__),continuation/'inputs.json',producer)}
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,witness=witness,pid=pid),sort_keys=True).encode()).hexdigest()
    work=ROOT/'grading/evidence/student-mini-v1/interventions'/('cpu-dfi-replay-failure-'+key);work.mkdir(parents=True,exist_ok=False)
    record=dict(status='ACTUAL_NANO_FAILURE_STOP_REQUESTED',created_at=datetime.now(timezone.utc).isoformat(),
        bindings=bindings,replay=str(replay),producer_pid=pid,witness=witness,
        active_log_is_not_immutable=True,formal_baseline=False,physical_evidence_complete=False,
        reason='Firmware returned nonzero Nano status; stop owned producer, whose handler reaps its tool and writes HOLD')
    (work/'intervention.json').write_text(json.dumps(record,indent=2)+'\n');verify(bindings)
    if (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')!=argv:raise ValueError('process identity changed')
    os.kill(pid,signal.SIGTERM)
    print(json.dumps(dict(path=str(work/'intervention.json'),pid=pid,signal_sent=True)))


if __name__=='__main__':main()
