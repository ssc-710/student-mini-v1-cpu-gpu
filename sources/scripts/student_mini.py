#!/usr/bin/env python3
"""Student-mini contracts, full-array comparison and honest release readiness.

This module never manufactures hardware outputs from a golden model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'grading/student-mini'


def read_contracts():
    return tuple(json.loads((CONTRACT / name).read_text(encoding='utf-8'))
                 for name in ('spec.json', 'rubric.json'))


def validate_rubric(rubric):
    dimensions = rubric['dimensions']
    if [d['points'] for d in dimensions] != [20, 40, 20, 20] or rubric['total'] != 100:
        raise ValueError('rubric must be 20/40/20/20 = 100')
    ids = []
    for dimension in dimensions:
        multiple = 2 if dimension['id'] == 'optimization' else 1
        if multiple * sum(item['points'] for item in dimension['items']) != dimension['points']:
            raise ValueError('rubric item weights disagree')
        ids.extend(item['id'] for item in dimension['items'])
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate rubric item')


def score_gain(gain, item_id, *, evidence_valid):
    if type(gain) not in (int, float) or not math.isfinite(gain):
        raise ValueError('gain must be a finite number')
    if type(evidence_valid) is not bool:
        raise ValueError('evidence validity must be explicit')
    _, rubric = read_contracts()
    item = next(item for item in rubric['dimensions'][-1]['items'] if item['id'] == item_id)
    if not evidence_valid:
        return 0
    return max([0] + [points for threshold, points in item['bands'] if gain >= threshold])


def compare_outputs(golden, actual, golden_bits, actual_bits):
    arrays = (golden, actual, golden_bits, actual_bits)
    if not all(isinstance(a, list) for a in arrays) or len({len(a) for a in arrays}) != 1 or not golden:
        raise ValueError('require non-empty aligned full output arrays')
    if any(type(v) not in (int, float) or not math.isfinite(v) for a in arrays[:2] for v in a):
        raise ValueError('numeric outputs must be finite; error cases use status/event records')
    if any(type(v) is not int or not 0 <= v < 65536 for a in arrays[2:] for v in a):
        raise ValueError('BF16 output bit patterns must be uint16')
    for values,bits in ((golden,golden_bits),(actual,actual_bits)):
        if any(value!=struct.unpack('<f',struct.pack('<I',pattern<<16))[0] for value,pattern in zip(values,bits,strict=True)):
            raise ValueError('numeric output does not decode from its BF16 bit pattern')
    delta = [a - g for g, a in zip(golden, actual, strict=True)]
    mismatch = [i for i, (g, a) in enumerate(zip(golden_bits, actual_bits, strict=True)) if g != a]
    # Both views must agree; fake equal bits cannot hide differing values.
    passed = not mismatch and all(d == 0 for d in delta)
    return dict(golden=golden, actual=actual, golden_bits=golden_bits, actual_bits=actual_bits,
                delta=delta, absolute_delta=[abs(d) for d in delta], mismatch_indices=mismatch,
                bit_mismatch_count=len(mismatch), mae=fmean(abs(d) for d in delta),
                rmse=math.sqrt(fmean(d*d for d in delta)), max_absolute_delta=max(abs(d) for d in delta),
                status='PASS' if passed else 'FAIL')


def summarize_seeds(rows):
    seeds = [row['seed'] for row in rows]
    if any(type(s) is not int for s in seeds) or sorted(seeds) != list(range(1, 11)):
        raise ValueError('require exactly one record for each seed 1..10')
    sizes = {len(row['golden']) for row in rows} | {len(row['actual']) for row in rows}
    if len(sizes) != 1 or 0 in sizes:
        raise ValueError('output shapes differ between seeds')
    checked = [dict(seed=row['seed'], **compare_outputs(row['golden'], row['actual'], row['golden_bits'], row['actual_bits'])) for row in rows]
    mean_golden = [fmean(row['golden'][i] for row in checked) for i in range(next(iter(sizes)))]
    mean_actual = [fmean(row['actual'][i] for row in checked) for i in range(next(iter(sizes)))]
    failed = sorted(row['seed'] for row in checked if row['status'] != 'PASS')
    return dict(status='FAIL' if failed else 'PASS', mean_golden=mean_golden, mean_actual=mean_actual,
                mean_delta=[a-g for g, a in zip(mean_golden, mean_actual, strict=True)],
                mean_absolute_error=fmean(row['mae'] for row in checked),
                rmse=math.sqrt(fmean(row['rmse']**2 for row in checked)),
                max_absolute_delta=max(row['max_absolute_delta'] for row in checked),
                bit_mismatch_count=sum(row['bit_mismatch_count'] for row in checked), failed_seeds=failed,
                records=sorted(checked, key=lambda row: row['seed']))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def performance_gain(parent, candidate, weights):
    """Cycle-ratio geometric mean, with exact case/seed joins and frozen weights."""
    def index(rows):
        result={}
        for row in rows:
            key=(row['case_id'],row['seed'])
            if key in result:raise ValueError('duplicate performance case/seed')
            if row.get('source') not in ('rtl','rtlsim','vexriscv-sim'):raise ValueError('hardware cycle source required')
            if type(row.get('cycles')) is not int or row['cycles']<=0:raise ValueError('positive hardware cycles required')
            result[key]=row
        return result
    p,c=index(parent),index(candidate)
    required={(case,seed) for case in weights for seed in range(1,11)}
    if p.keys()!=required or c.keys()!=required:raise ValueError('frozen performance board or seeds differ')
    if not weights or any(type(w) not in (int,float) or not math.isfinite(w) or w<=0 for w in weights.values()):raise ValueError('positive frozen weights required')
    logs=[];regressions=[]
    for key in sorted(required):
        for field in ('input_sha256','model_sha256','workload_sha256','clock_hz','measurement_boundary'):
            if not p[key].get(field) or p[key][field]!=c[key].get(field):raise ValueError('unfair comparison: '+field)
        ratio=p[key]['cycles']/c[key]['cycles']
        logs.append(weights[key[0]]*math.log(ratio)/10)
        if c[key]['cycles']/p[key]['cycles']>1.05:regressions.append(dict(case_id=key[0],seed=key[1]))
    return dict(gain=math.exp(sum(logs)/sum(weights.values()))-1,regressions_over_5_percent=regressions)


def promotion_points(decision, *, all_required_gates_valid, direct_parent_valid):
    """Scoring only, not an evidence verifier or automatic academic judgement."""
    if not all_required_gates_valid or not direct_parent_valid:return 0
    if decision=='PROMOTE':return 2
    if decision=='HOLD_INSUFFICIENT_GAIN':return 1
    return 0


def readiness():
    spec, rubric = read_contracts()
    validate_rubric(rubric)
    # A missing artifact is never replaced by the legacy full-size PASS.
    required = [f'baselines/{p}-{op}.json' for p in ('cpu', 'gpu', 'accelerator') for op in spec['operators']]
    required += [f'physical/{name}/profile.json' for name in ('cpu', 'gpu', 'accelerator-p1', 'accelerator-p2', 'accelerator-p3')]
    required += [f'nano/{p}.json' for p in ('cpu', 'gpu', 'accelerator')]
    required += ['resource-validation.json', 'dependency-validation.json']
    base = ROOT / 'grading/evidence/student-mini-v1'
    issues = [f'missing:{name}' for name in required if not (base / name).is_file()]
    # Until the final verifier exists, mere field presence cannot authorize release.
    issues.append('release-verifier-not-yet-qualified')
    return dict(schema_version=1, release_id=spec['release_id'], complete=False, status='HOLD',
                issues=issues, formal_promotions=0,
                bindings={str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in (CONTRACT/'spec.json', CONTRACT/'rubric.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'rubric', 'spec'])
    args = parser.parse_args()
    if args.command == 'status':
        value = readiness()
    else:
        spec, rubric = read_contracts()
        validate_rubric(rubric)
        value = spec if args.command == 'spec' else rubric
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 2 if args.command == 'status' and not value['complete'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
