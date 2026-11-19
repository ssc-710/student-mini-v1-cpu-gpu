"""Re-execute whole GPU after the exact initializer change; do not reuse counters."""
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
from scripts.continue_student_mini_gpu_multiplier_replay import derive as multiplier_replay


def derive(source, root):
    value = multiplier_replay(source, root)
    for old, new in {
        "cut.get('status')!='FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS'": "cut.get('status')!='FPU_INITIAL_DIFFERENCE_STAGE_PASS'",
        'paths = [Path(__file__),': "paths = [Path(__file__),ROOT/'scripts/continue_student_mini_gpu_initial_replay.py',",
        "'build/student-mini/gpu-multiplier-replay-continuation'": "'build/student-mini/gpu-initial-replay-continuation'",
    }.items():
        if value.count(old) != 1: raise ValueError('initial replay seam changed: '+old)
        value = value.replace(old, new)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-continuation', type=Path, required=True)
    parser.add_argument('--unit-work', type=Path, required=True)
    parser.add_argument('--previous-resource', type=Path, required=True)
    args = parser.parse_args(); resource = args.previous_resource.resolve()
    previous = json.loads(resource.read_text())
    if previous['status'] != 'PASS' or previous['limits_enforced'] is not True:
        raise ValueError('previous successful replay command required')
    old = previous['command']
    begin = old.index('--export-continuation'); arguments = old[begin:]
    for flag, path in (('--export-continuation', args.export_continuation), ('--unit-work', args.unit_work)):
        if arguments.count(flag) != 1: raise ValueError('previous replay argument ambiguous')
        arguments[arguments.index(flag)+1] = str(path.resolve())
    original = ROOT/'scripts/continue_student_mini_gpu_nrm_replay.py'
    paths = [Path(__file__), original, ROOT/'scripts/continue_student_mini_gpu_multiplier_replay.py',
             resource, args.export_continuation.resolve()/'inputs.json', args.unit_work.resolve()/'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, arguments=arguments), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-initial-replay-launch'/key; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT)); bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
                  arithmetic_latency=57, integer_multiplier_latency=3, old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(dict(result, arguments=arguments), indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='INITIAL_WHOLE_GPU_REPLAY_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), *arguments], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'GPU_MULTIPLIER_REPRESENTATIVE_REPLAY_STAGE_PASS':
        result['status'] = 'GPU_INITIAL_REPLAY_LAUNCH_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
