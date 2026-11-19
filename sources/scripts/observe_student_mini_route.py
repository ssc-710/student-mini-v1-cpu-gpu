"""Copy source-bound final route reports for portable PASS-stage/HOLD inspection."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.audit_student_mini_route import check_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    args = parser.parse_args(); placement = args.placement.resolve()
    parent = json.loads((placement/'completion.json').read_text())
    source = json.loads((placement/'inputs.json').read_text())
    route = json.loads((placement/'route/completion.json').read_text())
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('finished source-fresh route required')
    verify(source['files'])
    logs = Path(parent['metrics_directory']); results = Path(parent['result_directory'])
    reports = logs.parents[3]/'reports/sky130hd'/logs.parent.name/logs.name
    paths = [logs/'5_2_route.json', logs/'6_report.json', results/'6_final.sdc',
             reports/'drt_antennas.log', reports/'5_route_drc.rpt']
    for path in paths:
        if route['artifacts'].get(str(path)) != sha(path): raise ValueError('raw route evidence changed')
    bindings = {str(p): sha(p) for p in paths + [Path(__file__),
        ROOT/'scripts/audit_student_mini_route.py', ROOT/'scripts/retry_student_mini_route.py',
        placement/'inputs.json', placement/'completion.json', placement/'route/completion.json']}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    out = ROOT/'grading/evidence/student-mini-v1/route-observations'/identity
    out.mkdir(parents=True, exist_ok=False)
    detailed = json.loads(paths[0].read_text()); finish = json.loads(paths[1].read_text())
    status = 'ROUTE_STAGE_PASS'; reason = 'Route-stage measurements only; complete physical/package validation remains'
    try: check_metrics(detailed, finish, paths[2].read_text())
    except ValueError as error: status = 'HOLD'; reason = str(error)
    copies = {}
    for path in paths:
        target = out/path.name; target.write_bytes(path.read_bytes()); copies[path.name] = sha(target)
    record = dict(status=status, physical_evidence_complete=False, formal_baseline=False,
        reason=reason, wns_ns=finish['finish__timing__setup__ws'],
        hold_wns_ns=finish['finish__timing__hold__ws'],
        drc=detailed['detailedroute__route__drc_errors'],
        antenna_nets=detailed['detailedroute__antenna__violating__nets'],
        antenna_pins=detailed['detailedroute__antenna__violating__pins'],
        bindings=bindings, artifacts=copies)
    path = out/'observation.json'; path.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(dict(path=str(path), sha256=sha(path), status=status, reason=reason)))


if __name__ == '__main__': main()
