"""Restart an interrupted immutable producer in a fresh, provenance-bound attempt.

No old completion is created, and absent resource measurements remain absent.
The selected CPU and GPU jobs retain their original numeric and acceptance gates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('interruption recovery seam changed: ' + old)
    return source.replace(old, new)


def private_mapper(source, root, controller):
    source = replace_once(source, 'ROOT = Path(__file__).resolve().parents[1]',
                          'ROOT = Path(' + repr(str(root)) + ')')
    return replace_once(source, 'paths = [Path(__file__),',
                        'paths = [Path(__file__), Path(' + repr(str(controller)) + '),')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('gpu', 'cpu'), required=True)
    parser.add_argument('--interrupted-launch', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    prior = args.interrupted_launch.resolve()
    expected = ROOT/'build/student-mini'/('gpu-initial-replay-launch' if args.kind == 'gpu' else 'selected-eco-cpu-launch')
    if prior.parent != expected or (prior/'completion.json').exists():
        raise ValueError('only the explicit incomplete original launch may be restarted')
    packet = prior/'inputs.json'
    parent = json.loads(packet.read_text())
    verify(parent['bindings'])
    source = prior/'producer.py'
    paths = [Path(__file__), packet, source]
    auxiliary = ROOT/'scripts/prepare_student_mini_gpu_physical.py' if args.kind == 'gpu' else prior/'runner.py'
    paths.append(auxiliary)
    bindings = {str(p): sha(p) for p in paths}
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, boot_id=boot,
                                             attempt=args.attempt), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/interruption-recovery'/identity
    work.mkdir(parents=True, exist_ok=False)
    text = source.read_text()
    private = work/('mapper.py' if args.kind == 'gpu' else 'runner.py')
    private.write_text(private_mapper(auxiliary.read_text(), ROOT, Path(__file__))
                       if args.kind == 'gpu' else auxiliary.read_text())
    if args.kind == 'gpu':
        text = replace_once(text, "mapper = ROOT/'scripts/prepare_student_mini_gpu_physical.py'",
                            'mapper = Path(' + repr(str(private)) + ')')
    else:
        text = replace_once(text, 'runner = Path(' + repr(str(auxiliary)) + ')',
                            'runner = Path(' + repr(str(private)) + ')')
    text = replace_once(text, 'paths = [Path(__file__),',
                        'paths = [Path(__file__), Path(' + repr(str(Path(__file__))) + '), Path(' + repr(str(packet)) + '),')
    producer = work/'producer.py'
    producer.write_text(text)
    bindings.update({str(p): sha(p) for p in (producer, private)})
    result = dict(status='HOLD', kind=args.kind, bindings=bindings, boot_id=boot,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  interrupted_launch=str(prior), old_completion_missing=True,
                  interrupted_peak_memory_available=False, interruption_cause='not established',
                  formal_baseline=False, physical_evidence_complete=False, accepted_nano_session=False)
    (work/'inputs.json').write_text(json.dumps(dict(result, arguments=parent['arguments']), indent=2)+'\n')
    verify(bindings)
    print(json.dumps(dict(work=str(work), stage='FRESH_INTERRUPTION_RECOVERY', kind=args.kind)), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), *parent['arguments']], cwd=ROOT,
                               stdout=output, stderr=subprocess.STDOUT)
    verify(bindings)
    rows = [json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows:
        result['child'] = rows[-1]
    expected_status = 'GPU_MULTIPLIER_REPRESENTATIVE_REPLAY_STAGE_PASS' if args.kind == 'gpu' else 'SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS'
    if code == 0 and result.get('child', {}).get('status') == expected_status:
        result['status'] = 'INTERRUPTION_RECOVERY_STAGE_PASS'
    result['exit_code'] = code
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return 0 if result['status'] == 'INTERRUPTION_RECOVERY_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
