"""Snapshot an in-progress congestion report; explicitly not final route evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def summarize(text):
    chunks = text.split('violation type: ')
    if chunks[0].strip() or len(chunks) < 2: raise ValueError('complete congestion report required')
    rows = []
    for chunk in chunks[1:]:
        kind = re.match(r'(Horizontal|Vertical) congestion\n', chunk)
        data = re.findall(r'comment: capacity:(\d+) usage:(\d+) congestion:(\d+)', chunk)
        box = re.findall(r'bbox = \(([\d.]+), ([\d.]+)\) - \(([\d.]+), ([\d.]+)\) on Layer -', chunk)
        if not kind or len(data) != 1 or len(box) != 1: raise ValueError('incomplete congestion entry')
        cap, used, excess = map(int, data[0])
        if excess <= 0 or used-cap != excess: raise ValueError('congestion arithmetic mismatch')
        rows.append(dict(direction=kind[1], capacity=cap, usage=used, overflow=excess, bbox=list(map(float, box[0]))))
    return dict(entries=len(rows), zero_capacity_entries=sum(r['capacity']==0 for r in rows),
                total_overflow=sum(r['overflow'] for r in rows),
                directions={k:sum(r['direction']==k for r in rows) for k in ('Horizontal','Vertical')},
                largest_overflows=sorted(rows, key=lambda r:r['overflow'], reverse=True)[:20])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(); route = args.route.resolve(); report = args.report.resolve()
    packet = route/'qualified-inputs.json'; parent = json.loads(packet.read_text())
    if report.parent != Path(parent['reports_directory']) or not re.fullmatch(r'congestion-\d+\.rpt', report.name):
        raise ValueError('actual selected route report required')
    before = sha(report); data = report.read_bytes()
    if hashlib.sha256(data).hexdigest() != before or sha(report) != before: raise ValueError('report changed during snapshot; retry observation')
    observed = summarize(data.decode('utf-8'))
    bindings = {str(p):sha(p) for p in (Path(__file__), packet, route/'inputs.json')}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, report_sha256=before), sort_keys=True).encode()).hexdigest()
    work = ROOT/'grading/evidence/student-mini-v1/congestion-observations'/key; work.mkdir(parents=True, exist_ok=False)
    snapshot = work/'congestion.rpt'; snapshot.write_bytes(data)
    result = dict(status='DIAGNOSTIC_CONGESTION_SNAPSHOT', diagnostic_only=True, formal_baseline=False,
                  physical_evidence_complete=False, route_completed=False, clock_period_ns=parent['clock_period_ns'],
                  observed_at=datetime.now(timezone.utc).isoformat(), original_mutable_report=str(report),
                  snapshot_sha256=sha(snapshot), bindings=bindings, **observed)
    output = work/'observation.json'; output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(path=str(output), sha256=sha(output), entries=observed['entries'],
                         zero_capacity_entries=observed['zero_capacity_entries'], total_overflow=observed['total_overflow'])))


if __name__ == '__main__': main()
