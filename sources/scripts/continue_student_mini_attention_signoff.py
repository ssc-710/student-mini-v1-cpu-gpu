"""Wait for a specific route, then verify gate workloads and measure their power.

This bounded continuation is not a release evaluator. Failures preserve all logs
and remain HOLD; neither a successful subprocess nor a power number grants B0.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def checked_route(route):
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('route did not complete with fresh sources')
    value = route.get('metrics', {}).get('finish__timing__setup__ws')
    if type(value) not in (float, int) or not 0 <= value < 10:
        raise ValueError('route has no valid nonnegative 10 ns setup margin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--sky130-library-root', type=Path, required=True)
    args = parser.parse_args()
    placement, manifest = args.placement.resolve(), args.manifest.resolve()
    files = [Path(__file__), placement/'inputs.json', placement/'completion.json', manifest,
             ROOT/'scripts/run_student_mini_attention_activity.py',
             ROOT/'scripts/run_student_mini_attention_power.py',
             ROOT/'scripts/student_mini_activity_power.tcl']
    bindings = {str(path): sha(path) for path in files}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/attention-signoff-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', physical_evidence_complete=False, bindings=bindings)
    started = time.monotonic()

    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=time.monotonic()-started), indent=2)+'\n')

    def execute(command, name, timeout):
        with (work/(name+'.log')).open('x') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            begin = time.monotonic()
            try:
                while child.poll() is None:
                    heartbeat(name)
                    if time.monotonic()-begin > timeout:
                        raise TimeoutError(name)
                    time.sleep(10)
            except BaseException:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                raise
        if child.returncode:
            raise RuntimeError(f'{name} failed; inspect bound log')
        return json.loads((work/(name+'.log')).read_text().splitlines()[-1])

    try:
        route_path = placement/'route/completion.json'
        while not route_path.exists():
            if time.monotonic()-started > 14400:
                raise TimeoutError('bounded route wait expired')
            heartbeat('WAITING_FOR_ROUTE_COMPLETION')
            time.sleep(10)
        checked_route(json.loads(route_path.read_text()))
        bindings[str(route_path)] = sha(route_path)
        if any(sha(Path(p)) != digest for p, digest in bindings.items()):
            raise ValueError('continuation input changed while waiting')
        activity = execute([sys.executable, str(ROOT/'scripts/run_student_mini_attention_activity.py'),
            '--placement', str(placement), '--manifest', str(manifest), '--mode', 'gate',
            '--sky130-library-root', str(args.sky130_library_root.resolve())], 'gate-workloads', 18000)
        if activity.get('complete') is not True:
            raise ValueError('gate workload verification incomplete')
        result['activity'] = activity
        power = execute([sys.executable, str(ROOT/'scripts/run_student_mini_attention_power.py'),
            '--placement', str(placement), '--activity', str(Path(activity['work'])/'completion.json')],
            'activity-power', 18000)
        result['power'] = power
        if power.get('complete') is not True:
            raise ValueError('per-seed power incomplete')
        result.update(stages_complete=True,
            reason='Gate outputs and ten powers measured; full physical source-closure/release validation remains required')
    except Exception as error:
        result.update(stages_complete=False, reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), complete=result['stages_complete'], reason=result['reason'])), flush=True)
    return 0 if result['stages_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
