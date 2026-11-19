"""Spatial diagnosis of an actual CTS checkpoint and frozen congestion snapshot."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route


def classify(report, geometry):
    units = re.findall(r'^MINI_GEOMETRY_UNITS (\d+)$', geometry, re.M)
    if len(units) != 1 or geometry.count('MINI_GEOMETRY_COMPLETE ') != 1:
        raise ValueError('complete actual database observation required')
    unit = int(units[0])
    macros = []
    for line in geometry.splitlines():
        if line.startswith('MINI_GEOMETRY_MACRO '):
            _, name, *box = line.split()
            macros.append(dict(name=bytes.fromhex(name).decode(), bbox=[int(x)/unit for x in box]))
    if len(macros) != 29:
        raise ValueError('exact 29-macro CPU required')
    counts = Counter(); by_macro = Counter(); supply_bins = {}
    for line in geometry.splitlines():
        if line.startswith('MINI_GEOMETRY_SUPPLY '):
            _, layer, *box = line.split(); box = [int(x)/unit for x in box]
            for ix in range(math.floor(box[0]/100), math.floor(box[2]/100)+1):
                for iy in range(math.floor(box[1]/100), math.floor(box[3]/100)+1):
                    supply_bins.setdefault((ix, iy), []).append((layer, box))
    for chunk in report.split('violation type: ')[1:]:
        data = re.findall(r'capacity:(\d+) usage:(\d+) congestion:(\d+)', chunk)
        boxes = re.findall(r'bbox = \(([\d.]+), ([\d.]+)\) - \(([\d.]+), ([\d.]+)\)', chunk)
        if len(data) != 1 or len(boxes) != 1:
            raise ValueError('incomplete congestion entry')
        cap, usage, overflow = map(int, data[0]); x0, y0, x1, y1 = map(float, boxes[0])
        if usage-cap != overflow or overflow <= 0:
            raise ValueError('invalid congestion counts')
        x, y = (x0+x1)/2, (y0+y1)/2
        region = 'outside_macro_and_20um_edge'
        for macro in macros:
            a, b, c, d = macro['bbox']
            if a <= x <= c and b <= y <= d:
                region = 'inside_macro'; by_macro[macro['name']] += 1; break
            if a-20 <= x <= c+20 and b-20 <= y <= d+20:
                region = 'within_20um_macro_edge'
        counts[region] += 1
        if cap == 0:
            counts['zero_capacity_'+region] += 1
        if any(a <= x <= c and b <= y <= d for _, (a,b,c,d) in supply_bins.get((math.floor(x/100), math.floor(y/100)), [])):
            counts['center_overlaps_supply_projection'] += 1
    return dict(macros=macros, reported_entry_regions=dict(counts), per_macro_entries=dict(by_macro),
                supply_overlap_is_2d_only=True, congestion_report_has_no_layer=True,
                causal_conclusion='Spatial correlation only; layer-specific blockage and counterfactual route remain unproved')


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    packet = args.route.resolve()/'completion.json'; parent = json.loads(packet.read_text())
    if parent['platform'] != 'cpu' or parent['clock_period_ns'] != 10:
        raise ValueError('actual frozen CPU route required')
    verify(parent['bindings'])
    odb = Path(parent['result_directory'])/'4_1_cts.odb'
    if parent['artifacts'].get(str(odb)) != sha(odb):
        raise ValueError('CTS checkpoint differs')
    observation = args.snapshot.resolve(); summary = json.loads(observation.read_text())
    report = observation.parent/'congestion.rpt'
    if summary['snapshot_sha256'] != sha(report):
        raise ValueError('congestion snapshot differs')
    hook = ROOT/'integration/student-mini/report_congestion_geometry.tcl'
    tool = Path('/home/soclab/.local/bin/openroad')
    bindings = {str(p):sha(p) for p in (Path(__file__), hook, tool, packet, odb, observation, report)}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/congestion-geometry'/key; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', bindings=bindings, diagnostic_only=True, physical_evidence_complete=False,
                  formal_baseline=False, observed_at=datetime.now(timezone.utc).isoformat())
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            if execute_locked_route(['env', 'STUDENT_MINI_GEOMETRY_ODB='+str(odb), str(tool), '-exit', str(hook)],
                                    work/'geometry.log', 180, lambda _: None):
                raise ValueError('actual OpenDB observation failed')
        result['spatial_observation'] = classify(report.read_text(), (work/'geometry.log').read_text())
        verify(bindings)
        result['status'] = 'DIAGNOSTIC_GEOMETRY_OBSERVED'
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['artifacts'] = {p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result.get('reason'))), flush=True)
    return 0 if result['status'] == 'DIAGNOSTIC_GEOMETRY_OBSERVED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
