"""Bound initial-difference physical run; stop at negative resized placement."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.continue_student_mini_gpu_multiplier_physical import derive as multiplier_physical
from scripts.continue_student_mini_gpu_nrm_physical import placement_source as original_placement


def resized_gate(metrics):
    value = metrics.get('placeopt__timing__setup__ws')
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'100 MHz resized placement fails: {value}; expensive legalization/route not started')
    return value


def placement_source(source, root):
    source = original_placement(source, root)
    old = "work / (target + '.log'), 600, lambda _: heartbeat(target)"
    if source.count(old) != 1: raise ValueError('bounded global-report seam changed')
    source = source.replace(old, "work / (target + '.log'), 1200 if target == 'do-3_3_place_gp' else 600, lambda _: heartbeat(target)")
    old = "                if target == 'do-2_4_floorplan_pdn':"
    if source.count(old) != 1: raise ValueError('resized failfast seam changed')
    source = source.replace(old, """                if target == 'do-3_4_place_resized':
                    from scripts.continue_student_mini_gpu_initial_physical import resized_gate
                    result['resized_wns_ns'] = resized_gate(json.loads((logs/'3_4_place_resized.json').read_text()))
"""+old)
    return source.replace('files = [Path(__file__),', "files = [Path(__file__), ROOT/'scripts/continue_student_mini_gpu_initial_physical.py',", 1)


def derive(source, root):
    source = multiplier_physical(source, root)
    old = "place_producer.write_text(placement_source(placement.read_text(), ROOT))"
    if source.count(old) != 1: raise ValueError('private placement seam changed')
    source = source.replace(old, "place_producer.write_text(initial_placement(placement.read_text(), ROOT))")
    source = source.replace('def main():', 'from scripts.continue_student_mini_gpu_initial_physical import placement_source as initial_placement\n\ndef main():', 1)
    source = source.replace('paths = [Path(__file__),', "paths = [Path(__file__),ROOT/'scripts/continue_student_mini_gpu_initial_physical.py',", 1)
    return source.replace("'build/student-mini/gpu-multiplier-physical-continuation'", "'build/student-mini/gpu-initial-physical-continuation'")


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--replay-continuation', type=Path, required=True)
    args = parser.parse_args(); replay = args.replay_continuation.resolve()
    original = ROOT/'scripts/continue_student_mini_gpu_nrm_physical.py'
    paths = [Path(__file__), original, ROOT/'scripts/continue_student_mini_gpu_multiplier_physical.py', replay/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-initial-physical-launch'/key; work.mkdir(parents=True, exist_ok=False)
    private = work/'producer.py'; private.write_text(derive(original.read_text(), ROOT)); bindings[str(private)] = sha(private)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
                  arithmetic_latency=57, integer_multiplier_latency=3, old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='INITIAL_PHYSICAL_WAITING_FOR_REAL_REPLAY')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(private), '--replay-continuation', str(replay)], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'GPU_MULTIPLIER_PHYSICAL_PREFLIGHT_STAGE_PASS':
        result['status'] = 'GPU_INITIAL_PHYSICAL_LAUNCH_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
