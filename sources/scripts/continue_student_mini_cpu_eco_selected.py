"""Run selected PTQ on the fully replayed DFI CPU bound to the legalized ECO."""
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
from scripts.continue_student_mini_cpu_dfi_selected import runner_source, continuation_source
from scripts.route_student_mini_platform import checked_parent


def placement_child(parent, platform):
    if platform != 'cpu': raise ValueError('CPU ECO only')
    checked_parent(parent, 'cpu')
    if parent.get('precision_changed') is not False or parent.get('clock_changed') is not False:
        raise ValueError('exact frozen CPU numeric/clock contract required')
    path = Path(parent['config']).parent
    if path.parent != ROOT/'build/student-mini/cpu-drive-eco': raise ValueError('actual isolated ECO workspace required')
    return path


def derive(source, root, runner):
    source = continuation_source(source, root, runner)
    old = 'from scripts.continue_student_mini_cpu_dfi_selected import placement_child'
    if source.count(old) != 1: raise ValueError('ECO placement seam changed')
    source = source.replace(old, 'from scripts.continue_student_mini_cpu_eco_selected import placement_child')
    source = source.replace('paths = [Path(__file__),', "paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_eco_selected.py',", 1)
    return source.replace("'build/student-mini/selected-dfi-cpu-placement-continuation'", "'build/student-mini/selected-eco-cpu-placement-continuation'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--previous-resource', type=Path, required=True)
    args = parser.parse_args(); resource = args.previous_resource.resolve()
    prior = json.loads(resource.read_text())
    if prior['status'] != 'PASS' or prior['limits_enforced'] is not True: raise ValueError('verified prior selected-model command required')
    arguments = prior['command'][prior['command'].index('--replay'):]
    if arguments.count('--replay') != 1: raise ValueError('ambiguous prior replay')
    arguments[arguments.index('--replay')+1] = str(args.replay.resolve())
    arguments += ['--physical-continuation', str(args.placement.resolve())]
    packet = args.placement.resolve()/'completion.json'; placement = json.loads(packet.read_text())
    placement_child(placement, 'cpu'); verify(placement['bindings'])
    original = ROOT/'scripts/continue_student_mini_selected_cpu.py'
    runner = ROOT/'scripts/run_student_mini_selected_cpu_replay.py'
    paths = [Path(__file__), original, runner, ROOT/'scripts/continue_student_mini_cpu_dfi_selected.py', resource, packet,
             args.replay.resolve()/'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, arguments=arguments), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/selected-eco-cpu-launch'/key; work.mkdir(parents=True, exist_ok=False)
    private_runner = work/'runner.py'; private_runner.write_text(runner_source(runner.read_text(), ROOT))
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT, private_runner))
    bindings.update({str(p): sha(p) for p in (producer, private_runner)})
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False, accepted_nano_session=False)
    (work/'inputs.json').write_text(json.dumps(dict(result, arguments=arguments), indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='SELECTED_MODEL_ON_LEGALIZED_DFI_CPU_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), *arguments], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS':
        result['status'] = 'SELECTED_ECO_CPU_NUMERICAL_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
