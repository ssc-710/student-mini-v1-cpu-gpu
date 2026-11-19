"""Exact host differential for the scale-context candidate on frozen 1000 vectors."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import argparse

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE / 'tools'))
from prepare_scalar_ctx_candidate import prepare
sys.path.insert(0, str(ROOT / 'sources'))
from scripts.export_student_mini_input import encode

parser = argparse.ArgumentParser()
parser.add_argument('--run-id', default='scalar-ctx-host-frozen-1000')
args = parser.parse_args()
assert args.run_id not in ('.', '..') and not any(char in args.run_id for char in '/\\')
candidate = prepare()
out = BASE / 'runs' / args.run_id
out.mkdir(parents=True, exist_ok=False)
env = dict(os.environ, TMPDIR=str(BASE / 'build/cache/tmp'))
sources = {
    'original': ROOT / 'sources/software/student_mini_scalar.c',
    'candidate': candidate,
}
for name, path in sources.items():
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-ffp-contract=off', '-fno-fast-math',
        '-I' + str(ROOT / 'sources/software/include'), str(path),
        str(ROOT / 'sources/software/operator_scalar.c'), '-o', str(out / (name + '.so')),
    ], env=env, check=True)

class Result(C.Structure):
    _fields_ = [('status', C.c_uint32), ('count', C.c_uint32),
                ('selected_count', C.c_uint32), ('output', C.c_uint16 * 32),
                ('selected', C.c_uint8 * 8), ('primitive', C.c_int32)]

libs = [C.CDLL(str(out / (name + '.so'))) for name in sources]
for lib in libs:
    lib.student_mini_execute.argtypes = [C.c_void_p, C.POINTER(Result)]
vectors_path = ROOT / 'data/golden/vectors.jsonl'
vectors = [json.loads(line) for line in vectors_path.read_text().splitlines()]
records = []
for ordinal, vector in enumerate(vectors):
    raw = encode(vector, ordinal)
    buf = C.create_string_buffer(raw)
    original, actual = Result(), Result()
    libs[0].student_mini_execute(buf, C.byref(original))
    libs[1].student_mini_execute(buf, C.byref(actual))
    assert bytes(original) == bytes(actual), (ordinal, vector['case']['id'], vector['seed'])
    records.append({
        'ordinal': ordinal,
        'case_id': vector['case']['id'],
        'operator': vector['case']['operator'],
        'seed': vector['seed'],
        'status': int(actual.status),
        'match': True,
    })

summary = {}
for operator, expected_records, expected_cases in [('p1', 330, 33), ('p2', 340, 34), ('p3', 330, 33)]:
    rows = [row for row in records if row['operator'] == operator]
    assert len(rows) == expected_records
    assert len({row['case_id'] for row in rows}) == expected_cases
    for case_id in {row['case_id'] for row in rows}:
        assert sorted(row['seed'] for row in rows if row['case_id'] == case_id) == list(range(1, 11))
    summary[operator] = {'records': len(rows), 'cases': expected_cases, 'matched': len(rows)}

sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = {
    'status': 'SCALE_CONTEXT_FROZEN_HOST_1000_EXACT_PASS',
    'by_operator': summary,
    'candidate_sha256': sha(candidate),
    'original_sha256': sha(sources['original']),
    'vectors_sha256': sha(vectors_path),
    'records': records,
    'limitation': ('Host exact differential only. P3 is 33 cases x seeds 1-10, but '
                   'VexRiscv RTL, GPU SimX/RTLSIM, protocol and physical qualification remain required.'),
}
(out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('SCALE_CONTEXT_FROZEN_HOST_EXACT_PASS', json.dumps(summary))
