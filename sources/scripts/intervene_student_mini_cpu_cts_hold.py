"""Stop only the identified owned route producer after a measured negative CTS.

The producer's existing SIGTERM handler reaps its tool process group and writes
its own immutable HOLD. This audit never edits physical results or statuses.
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def negative_cts(metrics):
    value=metrics.get('cts__timing__setup__ws')
    if type(value) not in (int,float) or not math.isfinite(value) or value>=0:
        raise ValueError('completed negative finite CTS measurement required')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route',type=Path,required=True)
    parser.add_argument('--producer',type=Path,required=True)
    args=parser.parse_args();route=args.route.resolve();producer=args.producer.resolve()
    if route.parent!=ROOT/'build/student-mini/platform-route' or (route/'completion.json').exists():
        raise ValueError('active scoped route only')
    if producer.name!='producer.py' or producer.parent.parent!=ROOT/'build/student-mini/cpu-read-buffer-route-launch':
        raise ValueError('exact owned CPU producer required')
    packet=route/'qualified-inputs.json';parent=json.loads(packet.read_text());verify(parent['bindings'])
    if parent['platform']!='cpu' or parent['clock_period_ns']!=10 or parent['bindings'].get(str(producer))!=sha(producer):
        raise ValueError('actual producer/platform/source differs')
    metrics=Path(parent['metrics_directory'])/'4_1_cts.json'
    report=Path(parent['reports_directory'])/'4_cts_final.rpt'
    checkpoint=Path(parent['result_directory'])/'4_1_cts.odb'
    wns=negative_cts(json.loads(metrics.read_text()))
    paths=[Path(__file__),packet,producer,metrics,report,checkpoint,route/'do-4_1_cts.log']
    bindings={str(p):sha(p) for p in paths}
    matches=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try: argv=(process/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,PermissionError,ProcessLookupError): continue
        if len(argv)>2 and argv[1].decode(errors='replace')==str(producer):
            matches.append((int(process.name),argv))
    if len(matches)!=1: raise ValueError('owned live producer is not unique')
    pid,argv=matches[0]
    if b'--platform' not in argv or b'cpu' not in argv or b'--placement' not in argv:
        raise ValueError('wrong live operation')
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,pid=pid),sort_keys=True).encode()).hexdigest()
    work=ROOT/'grading/evidence/student-mini-v1/interventions'/('cpu-negative-cts-'+key);work.mkdir(parents=True,exist_ok=False)
    record=dict(status='NEGATIVE_CTS_STOP_REQUESTED',created_at=datetime.now(timezone.utc).isoformat(),bindings=bindings,
        route=str(route),producer_pid=pid,wns_ns=wns,clock_period_ns=10,signal='SIGTERM',
        formal_baseline=False,physical_evidence_complete=False,
        reason='Stop the exact route producer after negative CTS; existing cleanup handler writes HOLD and reaps its own tool group')
    (work/'intervention.json').write_text(json.dumps(record,indent=2)+'\n')
    verify(bindings)
    if (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')!=argv:
        raise ValueError('process identity changed; no signal sent')
    os.kill(pid,signal.SIGTERM)
    print(json.dumps(dict(path=str(work/'intervention.json'),pid=pid,wns_ns=wns,signal_sent=True)))


if __name__=='__main__': main()
