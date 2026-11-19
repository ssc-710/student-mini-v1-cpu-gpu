"""Single-variable floorplan-size experiment on the same replayed GPU synthesis."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.resume_student_mini_interrupted import replace_once


def capacity(text):
    def number(label):
        found = re.findall(re.escape(label)+r'\s+([0-9.]+)', text)
        if len(found) != 1: raise ValueError('unique measured placement area required: '+label)
        return float(found[0])
    core = number('Core area:'); fixed = number('Fixed instances area:')
    movable = number('Standard cells area:')
    if not 0 < fixed < core or movable <= 0:
        raise ValueError('invalid actual placement areas')
    if 'Target density 0.2500 is too low for the available free area.' not in text:
        raise ValueError('actual capacity warning missing')
    return dict(core_area_um2=core, fixed_area_um2=fixed, movable_area_um2=movable,
                measured_free_area_utilization=movable/(core-fixed), requested_density=.25,
                minimum_total_area_for_requested_density_um2=fixed+movable/.25)


def expanded_config(source):
    # Macro coordinates, orientation, halos, density, clock and netlist stay
    # unchanged. Only die/core dimensions, sharing the old 20 um margin, grow.
    source = replace_once(source, 'export DIE_AREA = 0 0 4200 4200',
                          'export DIE_AREA = 0 0 6000 6000')
    return replace_once(source, 'export CORE_AREA = 20 20 4180 4180',
                        'export CORE_AREA = 20 20 5980 5980')


def derive(source):
    old = "config = work / 'config.mk'; shutil.copyfile(parent['config'], config); bindings[str(config)] = sha(config)"
    new = "config = work / 'config.mk'; config.write_text(expanded_config(Path(parent['config']).read_text())); bindings[str(config)] = sha(config)"
    source = replace_once(source, old, new)
    source = replace_once(source, 'def main():',
        'from scripts.continue_student_mini_gpu_footprint import expanded_config\n\ndef main():')
    return replace_once(source, 'files = [Path(__file__),',
                        "files = [Path(__file__), ROOT/'scripts/continue_student_mini_gpu_footprint.py',")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prior-placement', 'prior-producer', 'synthesis-continuation'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); prior = args.prior_placement.resolve()
    packet = prior/'completion.json'; parent = json.loads(packet.read_text())
    source = args.prior_producer.resolve(); synthesis = args.synthesis_continuation.resolve()
    log = prior/'do-3_3_place_gp.log'
    if (parent['clock_period_ns'] != 10 or parent['macro_count'] != 37
        or parent['bindings'].get(str(source)) != sha(source)
        or parent['bindings'].get(str(synthesis/'completion.json')) != sha(synthesis/'completion.json')
        or parent['artifacts'].get(str(log)) != sha(log)):
        raise ValueError('same actual GPU parent, synthesis and completed log required')
    verify(parent['bindings']); observation = capacity(log.read_text())
    if observation['minimum_total_area_for_requested_density_um2'] >= 5960**2:
        raise ValueError('proposed die still cannot satisfy requested density')
    files = [Path(__file__), ROOT/'scripts/resume_student_mini_interrupted.py', source, packet, log,
             synthesis/'inputs.json', synthesis/'completion.json']
    bindings = {str(p):sha(p) for p in files}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-footprint-continuation'/key; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(source.read_text()))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, capacity_observation=observation,
                  single_variable='square_die_side_um:4200->6000; same 20 um core margin',
                  macro_positions_changed=False, rtl_changed=False, clock_changed=False, precision_changed=False,
                  formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='LARGER_GPU_FOOTPRINT_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--synthesis-continuation', str(synthesis)],
                               cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['placement'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('placement', {}).get('status') == 'REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS':
        result['status'] = 'GPU_FOOTPRINT_PLACEMENT_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], placement=result.get('placement'))), flush=True)
    return 0 if result['status'] == 'GPU_FOOTPRINT_PLACEMENT_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
