"""Whole same-ROM replay of the separately proved banked tag read candidate."""
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


def derive(source, root):
    changes = {
        '\nROOT=Path(__file__).resolve().parents[1]': '\nROOT=Path('+repr(str(root))+')',
        "files=[Path(__file__),": "files=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_tag_bank_replay.py',ROOT/'scripts/run_student_mini_cpu_tag_replay.py',",
        'CPU_TAG_REGISTER_MAPPING_STAGE_PASS': 'CPU_TAG_BANK_MAPPING_STAGE_PASS',
        "parent.get('tag_register_bits')!=11296": "parent.get('tag_register_bits')!=11621",
        "'build/student-mini/cpu-tag-replay-continuation'": "'build/student-mini/cpu-tag-bank-replay'",
    }
    for old, new in changes.items():
        expected = 2 if old == 'CPU_TAG_REGISTER_MAPPING_STAGE_PASS' else 1
        if source.count(old) != expected:
            raise ValueError('banked CPU full replay seam changed: '+old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--cpu-run', type=Path, required=True)
    args = parser.parse_args()
    original = ROOT/'scripts/run_student_mini_cpu_tag_replay.py'
    paths = [Path(__file__), original, args.mapping.resolve()/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-tag-bank-replay-launch'/identity; work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT)); bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='BANKED_CPU_REPLAY_QUEUED')), flush=True)
    with (work/'replay.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--mapping', str(args.mapping.resolve()),
            '--cpu-run', str(args.cpu_run.resolve())], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
    if rows:
        result['replay'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('replay', {}).get('status') == 'CPU_TAG_REGISTER_FULL_REPLAY_STAGE_PASS':
        result['status'] = 'CPU_TAG_BANK_FULL_REPLAY_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'])), flush=True)
    return 0 if result['status'] == 'CPU_TAG_BANK_FULL_REPLAY_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
