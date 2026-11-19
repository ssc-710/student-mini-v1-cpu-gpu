"""Portable, source-bound route-stage audit; never a complete physical package."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def check_metrics(detailed, finish, sdc):
    setup = finish.get('finish__timing__setup__ws')
    if type(setup) not in (int, float) or not math.isfinite(setup) or setup < 0:
        raise ValueError('10 ns timing not closed')
    periods = re.findall(r'^create_clock[^\n]*?-period[ \t]+(\S+)', sdc, re.M)
    try:
        valid_clock = len(periods) == 1 and Decimal(periods[0]) == Decimal(10)
    except InvalidOperation:
        valid_clock = False
    if not valid_clock:
        raise ValueError('exactly one 10 ns clock required')
    for key in ('detailedroute__route__drc_errors', 'detailedroute__antenna__violating__nets',
                'detailedroute__antenna__violating__pins'):
        if type(detailed.get(key)) is not int or detailed[key] != 0:
            raise ValueError('route signoff failed: '+key)
    return dict(clock_period_ns=10, wns_ns=setup, drc=0, antenna_nets=0, antenna_pins=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    args = parser.parse_args()
    work = args.placement.resolve()
    route_path = work/'route/completion.json'
    route = json.loads(route_path.read_text())
    source = json.loads((work/'inputs.json').read_text())
    parent = json.loads((work/'completion.json').read_text())
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('route did not complete with fresh sources')
    for name, digest in source['files'].items():
        if sha(Path(name)) != digest:
            raise ValueError('route source changed: '+name)
    paths = dict(detailed=Path(parent['metrics_directory'])/'5_2_route.json',
                 finish=Path(parent['metrics_directory'])/'6_report.json',
                 sdc=Path(parent['result_directory'])/'6_final.sdc')
    for path in paths.values():
        if route['artifacts'].get(str(path)) != sha(path):
            raise ValueError('raw signoff artifact not bound by route completion')
    # OpenROAD appends repeated metric keys for successive repair iterations;
    # its final emitted value is the final-stage measurement. Preserve raw
    # bytes alongside the derived audit so every earlier failure stays visible.
    metrics = check_metrics(json.loads(paths['detailed'].read_text()),
                            json.loads(paths['finish'].read_text()), paths['sdc'].read_text())
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in
                (route_path, work/'inputs.json', work/'completion.json', Path(__file__))}
    originals = {str(path): sha(path) for path in paths.values()}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, raw=originals), sort_keys=True).encode()).hexdigest()
    out = ROOT/'grading/evidence/student-mini-v1/route-audits'/identity
    out.mkdir(parents=True, exist_ok=False)
    for name, path in paths.items():
        destination = out/(name+path.suffix)
        destination.write_bytes(path.read_bytes())
        bindings[destination.relative_to(ROOT).as_posix()] = sha(destination)
    result = dict(status='ROUTE_STAGE_PASS', physical_evidence_complete=False, formal_baseline=False,
        operator=source['design']['top'], metrics=metrics, bindings=bindings, original_sources=originals,
        reason='Timing/DRC/antenna stage only; pin-access closure, gate workloads, power, toolchain and whole-package qualification remain separate')
    path = out/'audit.json'
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(path=str(path), sha256=sha(path), metrics=metrics)))


if __name__ == '__main__':
    main()
