"""Combine fresh disjoint paired runs only after all twelve executions pass."""
import hashlib
import json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
paths=[BASE/'runs'/name/'receipt.json' for name in ['gpu-native-regression-paired-smoke','gpu-native-regression-paired-remaining']]
rows=[]
for path in paths:
    report=json.loads(path.read_text());assert report['status']=='SELECTED_FRESH_PAIRED_SIMX_EXACT_PASS'
    for name,digest in report['bindings'].items():
        # The runner is intentionally improved after smoke; its old version's
        # hash remains historical metadata, not proof of the new code's execution.
        if name.endswith('/tools/run_gpu_regression.py'):continue
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest, name
    for row in report['records']:
        assert row['status']=='FRESH_PAIRED_SIMX_TOKEN_HIDDEN_LOGITS_EXACT_PASS'
        variants=row['variants'];assert variants['baseline']['records']==variants['candidate']['records']
        for variant in variants.values():
            for name,digest in variant['outputs'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
            for name,digest in variant['bindings'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
        rows.append(dict(index=row['index'],question=row['question'],token_ids=variants['candidate']['token_ids'],
            variants={key:{k:value[k] for k in ['aggregate_cycles','kernel_sync_seconds','qa_compute_readback_seconds','process_wall_seconds','tokens_per_kernel_wall_second']} for key,value in variants.items()}))
assert sorted(row['index'] for row in rows)==list(range(12))
out=BASE/'runs/gpu-twelve-prompt-comparison.json';assert not out.exists()
out.write_text(json.dumps(dict(status='TWELVE_FRESH_PAIRED_SIMX_TOKEN_HIDDEN_LOGITS_EXACT_PASS',records=sorted(rows,key=lambda row:row['index']),
    bindings={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    limitation='Fresh algorithm semantic regression on fixed SimX only. Diagnostic single-pair timings, not stable performance attribution, hardware RTL/fault/protocol or full-core PPA qualification. Runner improvements after a completed run are not retroactive checks.'),ensure_ascii=False,indent=2)+'\n')
print('TWELVE_FRESH_PAIRED_SIMX_EXACT_PASS')
