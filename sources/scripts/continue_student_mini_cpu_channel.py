"""Re-place the frozen DFI synthesis with only wider SRAM channels.

This tests a congestion hypothesis; a placement pass cannot establish route
improvement. Old ECOs are not automatically applied to a different placement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.resume_student_mini_interrupted import replace_once


def derive(source):
    source = replace_once(source,
        'from scripts.student_mini_cpu_tag_floorplan import geometry, placement_tcl, configuration',
        'from scripts.student_mini_cpu_channel_floorplan import geometry, placement_tcl, configuration')
    return replace_once(source, 'paths = [Path(__file__),',
        "paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_channel_floorplan.py', ROOT/'scripts/continue_student_mini_cpu_channel.py',")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-placement', type=Path, required=True)
    parser.add_argument('--prior-producer', type=Path, required=True)
    parser.add_argument('--diagnostic', type=Path, required=True)
    args = parser.parse_args()
    packet = args.prior_placement.resolve()/'completion.json'
    prior = json.loads(packet.read_text()); source = args.prior_producer.resolve()
    diagnostic = args.diagnostic.resolve(); observed = json.loads(diagnostic.read_text())
    if (prior['clock_period_ns'] != 10 or prior['geometry']['gap'] != 80 or prior['geometry']['macro_count'] != 29
        or prior['bindings'].get(str(source)) != sha(source)
        or observed['status'] != 'DIAGNOSTIC_GEOMETRY_OBSERVED' or observed['diagnostic_only'] is not True):
        raise ValueError('actual frozen original placement and geometry observation required')
    verify(prior['bindings']); verify(observed['bindings'])
    synthesis = Path(prior['parent_synthesis'])
    paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_channel_floorplan.py',
             ROOT/'scripts/resume_student_mini_interrupted.py', source, packet, diagnostic,
             synthesis/'completion.json']
    bindings = {str(p):sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-channel-continuation'/key; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(source.read_text()))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, single_variable='macro_channel_gap_um:80->160',
                  comparison_parent=str(args.prior_placement.resolve()), rtl_changed=False, clock_changed=False,
                  precision_changed=False, formal_baseline=False, physical_evidence_complete=False,
                  later_three_gate_eco_reused=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='WIDER_CHANNEL_PLACEMENT_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--synthesis', str(synthesis)], cwd=ROOT,
                               stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['placement'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('placement', {}).get('status') == 'CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':
        result['status'] = 'CPU_CHANNEL_PLACEMENT_STAGE_PASS'
    result['reason'] = 'Single-variable placement comparison only; real congestion benefit and final signoff remain to be measured'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], placement=result.get('placement'))), flush=True)
    return 0 if result['status'] == 'CPU_CHANNEL_PLACEMENT_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
