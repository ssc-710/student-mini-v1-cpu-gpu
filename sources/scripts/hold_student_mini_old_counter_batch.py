"""Gracefully stop our superseded 17-cycle diagnostic batch, preserving evidence."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',type=int,required=True)
    args=parser.parse_args()
    parent=ROOT/'build/student-mini/gpu/f01b705f2fe4034b78088e3761c0e9c9b37c3c1f95937a170807da8078f44f83'
    script=ROOT/'scripts/run_student_mini_gpu_synth_counters.py'
    run=ROOT/'build/student-mini/gpu-counters/6c93c0aa4d6ea2ebbfcb505793deb581ec67bc25de83d937f969a72b80b584d3/cases-600-100'
    prefix=ROOT/'grading/evidence/student-mini-v1/results/f5924a7bb5ff22f4a0f55993467849b2a40d73400b329bff633f434385c66e01/results.json'
    cut=ROOT/'build/student-mini/gpu-divsqrt-step-cut/af2dfb0341276c7a193e0b0a1c9eac78e75b1cefa5635594fe196ac2dff50113/completion.json'
    if (json.loads(prefix.read_text())['rtl_counter_records']!=600 or
        json.loads(cut.read_text())['old_counters_reusable'] is not False):
        raise ValueError('verified prefix or superseding latency evidence differs')
    if (run/'completion.json').exists():raise ValueError('already completed; do not touch')
    process=Path('/proc')/str(args.pid);descriptor=os.pidfd_open(args.pid)
    try:
        command=[p.decode() for p in (process/'cmdline').read_bytes().split(b'\0') if p]
        if command[1:]!=[str(script),'--parent',str(parent),'--start','600','--count','100']:
            raise ValueError('not the exact owned obsolete batch')
        if (process/'cwd').resolve()!=ROOT or (process/'exe').resolve()!=Path('/usr/bin/python3').resolve():
            raise ValueError('unexpected process executable or workspace')
        report=dict(status='SUPERSEDED_DIAGNOSTIC_HOLD_STOP_REQUESTED',created_at=datetime.now(timezone.utc).isoformat(),
            pid=args.pid,command=command,reason='17-cycle counters cannot qualify the independently tested 30-cycle candidate; prioritize whole-system repair and physical closure',
            preserved_verified_records=600,final_candidate_requires_full_1000_records=True,
            source_modified=False,completed_evidence_modified=False,
            bindings={str(p):sha(p) for p in (Path(__file__),script,prefix,cut,run.parent/'inputs.json')})
        output=ROOT/'grading/evidence/student-mini-v1/interventions'/('old-gpu-counter-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        output.mkdir(parents=True,exist_ok=False)
        receipt=output/'stop-request.json';receipt.write_text(json.dumps(report,indent=2)+'\n')
        # Collector has a SIGTERM handler that records HOLD and reaps only its own tool group.
        signal.pidfd_send_signal(descriptor,signal.SIGTERM)
        print(json.dumps(dict(path=str(receipt),status=report['status'])))
    finally:os.close(descriptor)


if __name__=='__main__':main()
