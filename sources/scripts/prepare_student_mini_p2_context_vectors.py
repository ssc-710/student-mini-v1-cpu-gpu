"""Additional Nano context-boundary goldens; never changes the frozen mini board."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.generate_student_mini_vectors import numeric_inputs, golden
from scripts.student_mini import sha


def build():
    sources = [Path(__file__), ROOT/'scripts/generate_student_mini_vectors.py',
               ROOT/'shared/python/soc_ai_labs/rtl_oracle.py',
               ROOT/'shared/python/soc_ai_labs/numeric.py', ROOT/'grading/student-mini/spec.json']
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    target = ROOT/'build/student-mini/p2-context-vectors'/identity
    target.mkdir(parents=True, exist_ok=False)
    records = []
    for length in (9, 16, 31, 32, 33):
        for splits in (1, 2, 4):
            case = dict(id=f'P2-NANO-L{length}-S{splits}', operator='p2',
                        scenario='bad-length' if length == 33 else 'nano-context',
                        shape=dict(query=1, length=length, splits=splits))
            for seed in range(1, 11):
                inputs = numeric_inputs(case, seed)
                records.append(dict(case=case, seed=seed,
                                    prng='LCG32:1664525,1013904223,mod2^32;high-byte-low4-minus8',
                                    inputs=inputs, golden=golden(case, inputs)))
    path = target/'vectors.jsonl'
    path.write_text(''.join(json.dumps(row, allow_nan=False)+'\n' for row in records), encoding='utf-8')
    manifest = dict(kind='additional-golden-only', status='HOLD', hardware_complete=False,
                    bindings=bindings, records=len(records), seeds=list(range(1, 11)),
                    artifacts={'vectors.jsonl': sha(path)},
                    boundary='Supplementary Nano context coverage, not a replacement or expansion of frozen grading weights.')
    (target/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(vectors=str(path), records=len(records), sha256=sha(path))))


if __name__ == '__main__':
    build()
