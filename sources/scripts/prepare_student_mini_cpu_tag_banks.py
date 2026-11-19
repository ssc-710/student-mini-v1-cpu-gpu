"""Prove the measured tag-mux timing candidate without mutating prior evidence."""
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
        'ROOT = Path(__file__).resolve().parents[1]': 'ROOT = Path('+repr(str(root))+')',
        'from scripts.student_mini_cpu_tag_registers import replace_tag, original_wrapper, MODULE':
        'from scripts.student_mini_cpu_tag_banks import replace_tag, original_wrapper, MODULE',
        "if path['startpoint']!='tag_mem.0.0.storage' or path['endpoint']!='data_mem_grain1.0.0.storage':":
        "if not path['startpoint'].startswith('builder_grant') or not path['endpoint'].startswith('tag_mem.0.0.read_data['):",
        "'not the diagnosed tag-to-data path'": "'not the diagnosed arbitration-to-tag-read mux path'",
        'files=[Path(__file__),': "files=[Path(__file__),ROOT/'scripts/prepare_student_mini_cpu_tag_banks.py',ROOT/'scripts/prepare_student_mini_cpu_tag_registers.py',ROOT/'scripts/student_mini_cpu_tag_banks.py',",
        "'build/student-mini/cpu-tag-registers'": "'build/student-mini/cpu-tag-banks'",
        'bits!=512*22+32': 'bits!=512*22+16*22+5',
        'tag storage is not exactly 11264 register bits plus 32-bit read output':
        'tag storage is not exactly 11264 bits plus 16x22 bank registers and 5-bit selector',
        'CPU_TAG_REGISTER_MAPPING_STAGE_PASS': 'CPU_TAG_BANK_MAPPING_STAGE_PASS',
    }
    for old, new in changes.items():
        expected = 2 if old == 'CPU_TAG_REGISTER_MAPPING_STAGE_PASS' else 1
        if source.count(old) != expected:
            raise ValueError('banked tag proof seam changed: '+old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--placement', type=Path, required=True)
    args = parser.parse_args()
    original = ROOT/'scripts/prepare_student_mini_cpu_tag_registers.py'
    paths = [Path(__file__), original, ROOT/'scripts/student_mini_cpu_tag_banks.py',
             args.mapping.resolve()/'completion.json', args.placement.resolve()/'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-tag-bank-proof-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT)); bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='TAG_BANK_PROOF_QUEUED')), flush=True)
    with (work/'proof.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--mapping', str(args.mapping.resolve()),
            '--placement', str(args.placement.resolve())], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'proof.log').read_text().splitlines() if line.startswith('{')]
    if rows:
        result['proof'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('proof', {}).get('status') == 'CPU_TAG_BANK_MAPPING_STAGE_PASS':
        result['status'] = 'CPU_TAG_BANK_PROOF_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'])), flush=True)
    return 0 if result['status'] == 'CPU_TAG_BANK_PROOF_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
