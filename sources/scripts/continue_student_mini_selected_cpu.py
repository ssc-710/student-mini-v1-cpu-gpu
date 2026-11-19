"""Rebind the selected PTQ model only after this exact CPU passes placement."""
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
from scripts.continue_student_mini_platform_route import placement_child
from scripts.route_student_mini_platform import checked_parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('physical-continuation', 'replay', 'image-dir', 'old-image-dir', 'candidate', 'preflight'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); prior = args.physical_continuation.resolve()
    runner = ROOT/'scripts/run_student_mini_selected_cpu_replay.py'
    paths = [Path(__file__), runner, ROOT/'scripts/continue_student_mini_platform_route.py',
             ROOT/'scripts/route_student_mini_platform.py', prior/'inputs.json', args.replay/'completion.json',
             args.image_dir/'manifest.json', args.old_image_dir/'manifest.json', args.candidate, args.preflight]
    bindings = {str(p.resolve()): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/selected-cpu-placement-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False,
                  accepted_nano_session=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work), stage='WAITING_FOR_EXACT_CPU_PLACEMENT')), flush=True)
    try:
        packet = prior/'completion.json'
        while not packet.is_file():
            heartbeat('WAITING_FOR_EXACT_CPU_PLACEMENT')
            if time.monotonic()-begin > 43200: raise TimeoutError('bounded placement wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text()); placement_packet = placement_child(parent, 'cpu')/'completion.json'
        placement = json.loads(placement_packet.read_text()); checked_parent(placement, 'cpu')
        replay_packet = args.replay.resolve()/'completion.json'
        if placement['bindings'].get(str(replay_packet)) != sha(replay_packet):
            raise ValueError('CPU placement belongs to different replayed RTL')
        for value in (parent, placement):
            verify(value['bindings']); bindings.update(value['bindings'])
        bindings.update({str(p): sha(p) for p in (packet, placement_packet)}); verify(bindings)
        heartbeat('SELECTED_MODEL_ON_QUALIFIED_CPU_QUEUED')
        command = [sys.executable, str(runner)]
        for name, value in vars(args).items():
            if name != 'physical_continuation': command += ['--'+name.replace('_', '-'), str(value.resolve())]
        with (work/'replay.log').open('x') as log:
            code = subprocess.call(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        rows = [json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
        if rows: result['replay'] = rows[-1]
        verify(bindings)
        if code or result.get('replay', {}).get('status') != 'SELECTED_MAPPED_CPU_NUMERICAL_STAGE_PASS':
            raise ValueError('selected-model CPU replay failed; child HOLD retained')
        child_packet = Path(result['replay']['work'])/'completion.json'; child = json.loads(child_packet.read_text())
        verify(child['bindings']); bindings.update(child['bindings']); bindings[str(child_packet)] = sha(child_packet)
        result.update(status='SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS',
            reason='Selected PTQ model and 1000 baselines match on the placed CPU; route, power, reset and accepted session gates remain')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
