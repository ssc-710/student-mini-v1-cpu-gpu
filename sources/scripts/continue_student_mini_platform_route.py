"""Wait for a bound physical continuation, then run the existing strict router."""
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
from scripts.retry_student_mini_route import verify


def placement_child(parent, platform):
    statuses = {'cpu': 'CPU_TAG_PHYSICAL_PREFLIGHT_STAGE_PASS',
                'gpu': 'GPU_NRM_PHYSICAL_PREFLIGHT_STAGE_PASS'}
    if platform not in statuses or parent.get('status') != statuses[platform]:
        raise ValueError('matching complete physical preflight required; no route launched')
    child = parent.get('placement', {})
    expected = {'cpu': 'CPU_PLACEMENT_PREFLIGHT_STAGE_PASS',
                'gpu': 'REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS'}
    if child.get('status') != expected[platform] or not isinstance(child.get('work'), str):
        raise ValueError('matching bound placement child required')
    return Path(child['work'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-continuation', type=Path, required=True)
    parser.add_argument('--platform', choices=('cpu', 'gpu'), required=True)
    args = parser.parse_args(); prior = args.physical_continuation.resolve()
    router = ROOT/'scripts/route_student_mini_platform.py'
    paths = [Path(__file__), router, prior/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, platform=args.platform), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/platform-route-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', bindings=bindings, platform=args.platform,
                  formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    start = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-start))+'\n')
    print(json.dumps(dict(work=str(work), stage='WAITING_FOR_QUALIFIED_PHYSICAL_PREFLIGHT')), flush=True)
    try:
        packet = prior/'completion.json'
        while not packet.is_file():
            heartbeat('WAITING_FOR_QUALIFIED_PHYSICAL_PREFLIGHT')
            if time.monotonic()-start > 43200:
                raise TimeoutError('bounded preflight wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text()); child = placement_child(parent, args.platform)
        verify(parent['bindings']); bindings.update(parent['bindings']); bindings[str(packet)] = sha(packet)
        # Both producers record the placement path. The router independently
        # checks raw placement status, WNS, clock, macros and checkpoint SHAs.
        if child.parent != ROOT/'build/student-mini'/('cpu-placement' if args.platform == 'cpu' else 'gpu-repaired-placement'):
            raise ValueError('unexpected placement workspace')
        placement_receipt = child/'completion.json'
        bindings[str(placement_receipt)] = sha(placement_receipt)
        verify(bindings); heartbeat('QUALIFIED_ROUTE_QUEUED')
        with (work/'route.log').open('x') as log:
            code = subprocess.call([sys.executable, str(router), '--placement', str(child),
                                    '--platform', args.platform], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        rows = [json.loads(line) for line in (work/'route.log').read_text().splitlines() if line.startswith('{')]
        if rows: result['route'] = rows[-1]
        verify(bindings)
        if code or result.get('route', {}).get('status') != 'PLATFORM_ROUTE_STAGE_PASS':
            raise ValueError('route did not qualify; child HOLD retained')
        result.update(status='PLATFORM_ROUTING_CONTINUATION_STAGE_PASS',
            reason='Exact preflight led to completed route; activity, power, pin access and full acceptance still required')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-start
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'PLATFORM_ROUTING_CONTINUATION_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
