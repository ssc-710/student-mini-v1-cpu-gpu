"""Recheck archived actual records; this does not rerun target simulations."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
out = root / 'rerun_sqrt3/baseline-audit'
out.mkdir(exist_ok=True)
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
    return json.loads(p.read_text(encoding='utf-8'))
def lines(p):
    return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]
def bf16(b):
    return struct.unpack('<f', struct.pack('<I', b << 16))[0]
def digest_inputs(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()

sys.path[:0] = [str(root/'sources'), str(root/'sources/shared/python')]
from scripts.generate_student_mini_vectors import case_catalog, numeric_inputs, golden
import numpy
import ml_dtypes

gpath = root/'data/golden/vectors.jsonl'
vectors = lines(gpath)
manifest = read(root/'data/golden/manifest.json')
expected_keys = {(c['id'], s) for c in case_catalog() for s in range(1,11)}
gkeys = [(g['case']['id'], g['seed']) for g in vectors]
issues = []
checks = []
def check(label, ok, detail=None):
    checks.append(dict(check=label, passed=bool(ok), detail=detail))
    if not ok:
        issues.append(dict(check=label, detail=detail))
check('golden_count_1000', len(vectors)==1000)
check('golden_unique_exact_case_seed_set', len(gkeys)==len(set(gkeys)) and set(gkeys)==expected_keys)
check('catalog_matches_manifest', case_catalog()==manifest['cases'])
check('manifest_seeds_1_to_10', manifest['seeds']==list(range(1,11)))
check('golden_file_digest', sha(gpath)==manifest['artifacts']['vectors.jsonl'])
for name, digest in manifest['bindings'].items():
    check('golden_source_binding:'+name, sha(root/'sources'/name)==digest)
regen = []
for ordinal,g in enumerate(vectors):
    inp = numeric_inputs(g['case'],g['seed'])
    expected = golden(g['case'],inp)
    row = dict(ordinal=ordinal, case_id=g['case']['id'], seed=g['seed'],
               inputs_match=inp==g['inputs'], golden_match=expected==g['golden'])
    regen.append(row)
    check('regeneration:'+str(ordinal), row['inputs_match'] and row['golden_match'])
(out/'golden-regeneration.json').write_text(json.dumps(regen,indent=2)+'\n')

platform_rows = {}
detail = []
baselines = []
case_summaries = []
for platform in ('cpu','gpu'):
    rows = lines(root/f'data/records/{platform}.jsonl')
    keys = [(r['case']['id'],r['seed']) for r in rows]
    check(platform+':count', len(rows)==1000)
    check(platform+':unique_exact_keys', len(keys)==len(set(keys)) and set(keys)==expected_keys)
    check(platform+':ordinal_bijection', sorted(r['ordinal'] for r in rows)==list(range(1000)))
    index = {k:r for k,r in zip(keys,rows)}
    platform_rows[platform]=index
    per_op = defaultdict(list)
    per_case = defaultdict(list)
    for ordinal,g in enumerate(vectors):
        key = (g['case']['id'],g['seed'])
        r=index.get(key)
        if r is None:
            check(platform+':missing:'+str(key),False)
            continue
        obs,exp=r['observation'],g['golden']
        gb,ab=exp.get('output_bits') or [],obs.get('actual_bits') or []
        selected=obs.get('selected')
        if selected is None and obs.get('selected_token_ids') is not None:
            selected=[t for ids in obs['selected_token_ids'] for t in ids]
        selection_ok=True
        if g['case']['operator']=='p1' and exp['expected_status']=='OK' and exp.get('selected_token_ids') is not None:
            selection_ok=selected==[t for ids in exp['selected_token_ids'] for t in ids]
        primitive_ok='primitive_witness_result' not in exp or obs.get('primitive')==exp['primitive_witness_result']
        missing=[e for e in exp['expected_events'] if not r['events']['actual_events'].get(e)]
        deltas=[bf16(a)-bf16(b) for a,b in zip(ab,gb)] if len(ab)==len(gb) else []
        tests=dict(case_seed_ordinal=r['ordinal']==ordinal and r['case']==g['case'] and r['seed']==g['seed'],
            platform=r['platform']==platform and obs.get('platform',platform)==platform,
            input_hash=r['input_sha256']==digest_inputs(g['inputs']),
            frozen_golden=r['golden']==exp, prng=r['prng']==g['prng'],
            status=obs['actual_status']==exp['expected_status'],
            output_bits=ab==gb,
            golden_values=[bf16(b) for b in gb]==(exp.get('output_values') or []),
            actual_values='actual' not in obs or [bf16(b) for b in ab]==(obs.get('actual') or []),
            selection=selection_ok,primitive=primitive_ok,
            expected_events=r['events']['expected_events']==exp['expected_events'],
            events=not missing and r['events']['missing_events']==missing,
            stored_pass=r['comparison']['status']=='PASS' and r['status']=='PASS',
            stored_bits=r['comparison']['golden_bits']==gb and r['comparison']['actual_bits']==ab)
        failed=[k for k,v in tests.items() if not v]
        item=dict(platform=platform,operator=g['case']['operator'],case_id=key[0],seed=key[1],ordinal=ordinal,
            expected_status=exp['expected_status'],actual_status=obs['actual_status'],
            elements=len(gb),bit_mismatches=sum(a!=b for a,b in zip(ab,gb))+abs(len(ab)-len(gb)),
            max_absolute_delta=max((abs(d) for d in deltas),default=0),
            selection_checked=g['case']['operator']=='p1' and exp['expected_status']=='OK',
            primitive_checked='primitive_witness_result' in exp,
            event_count=len(exp['expected_events']),backend=obs.get('backend'),
            passed=not failed,failed_checks=';'.join(failed))
        detail.append(item);per_op[item['operator']].append(item);per_case[key[0]].append(item)
        check(platform+':record:'+str(ordinal),not failed,failed or None)
    for op,group in per_op.items():
        baselines.append(dict(platform=platform,operator=op,cases=len({r['case_id'] for r in group}),
            records=len(group),passed=sum(r['passed'] for r in group),
            expected_status_counts=dict(Counter(r['expected_status'] for r in group)),
            numeric_records=sum(r['elements']>0 for r in group),elements=sum(r['elements'] for r in group),
            bit_mismatches=sum(r['bit_mismatches'] for r in group),
            max_absolute_delta=max(r['max_absolute_delta'] for r in group),
            selection_records=sum(r['selection_checked'] for r in group),
            primitive_records=sum(r['primitive_checked'] for r in group),
            expected_events=sum(r['event_count'] for r in group),backends=dict(Counter(r['backend'] for r in group))))
    for case_id,group in per_case.items():
        seeds=sorted(r['seed'] for r in group)
        check(platform+':seeds:'+case_id,seeds==list(range(1,11)))
        case_summaries.append(dict(platform=platform,case_id=case_id,operator=group[0]['operator'],seeds=seeds,
            passed=sum(r['passed'] for r in group),failed_seeds=[r['seed'] for r in group if not r['passed']]))

cross=[]
for key in gkeys:
    a=platform_rows['cpu'][key]['observation'];b=platform_rows['gpu'][key]['observation']
    same=a['actual_status']==b['actual_status'] and a['actual_bits']==b['actual_bits']
    cross.append(dict(case_id=key[0],seed=key[1],status_and_bits_equal=same))
    check('cpu_gpu:'+str(key),same)
with (out/'records.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=list(detail[0]));writer.writeheader();writer.writerows(detail)
(out/'cases.json').write_text(json.dumps(case_summaries,indent=2)+'\n')
(out/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
command=[sys.executable,str(root/'verify_release.py')]
proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
(out/'verify-release.stdout.json').write_text(proc.stdout)
(out/'verify-release.stderr.log').write_text(proc.stderr)
result=dict(timestamp=datetime.now(timezone.utc).isoformat(),mode='archived_actual_recomparison_and_golden_regeneration',
    target_simulations_rerun=False,python=sys.version,numpy=numpy.__version__,ml_dtypes=ml_dtypes.__version__,
    golden_records=len(vectors),unique_cases=len({k[0] for k in gkeys}),
    golden_regeneration_matches=sum(r['inputs_match'] and r['golden_match'] for r in regen),
    baselines=baselines,all_checks_passed=not issues,issue_count=len(issues),issues=issues,
    cpu_gpu_status_and_bits_equal=sum(r['status_and_bits_equal'] for r in cross),
    release_verifier=dict(command=command,exit_code=proc.returncode,result=json.loads(proc.stdout)),
    source_hashes={str(p.relative_to(root)):sha(p) for p in [Path(__file__),root/'verify_release.py',gpath,
        root/'data/golden/manifest.json',root/'data/records/cpu.jsonl',root/'data/records/gpu.jsonl',
        root/'MANIFEST.sha256',root/'release.json']})
(out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if not issues else 1)
