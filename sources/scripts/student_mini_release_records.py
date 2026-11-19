"""Independent record verification and statistics for the student-mini release.

Every platform record is re-checked against the frozen golden vectors from
raw bit patterns; nothing is taken from the producer's own comparison fields.
"""
from __future__ import annotations

import json
import math
import struct
from collections import defaultdict
from pathlib import Path
from statistics import fmean

COUNTERS = ('cycles', 'instructions', 'dma_bytes', 'cache_bytes')


def bf16(bits: int) -> float:
    return struct.unpack('<f', struct.pack('<I', bits << 16))[0]


def load_vectors(path: Path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    index = {}
    for ordinal, row in enumerate(rows):
        key = (row['case']['id'], row['seed'])
        if key in index:
            raise ValueError(f'duplicate golden case/seed {key}')
        index[key] = (ordinal, row)
    return index


def compare(golden: dict, observation: dict, operator: str) -> dict:
    expected = golden['expected_status']
    actual_status = observation.get('actual_status')
    bits_g = golden.get('output_bits') or []
    bits_a = observation.get('actual_bits') or []
    result = dict(expected_status=expected, actual_status=actual_status, status_match=actual_status == expected)
    if bits_g:
        if any(type(b) is not int or not 0 <= b < 65536 for b in bits_g + bits_a):
            raise ValueError('BF16 bit patterns must be uint16')
        values_g = [bf16(b) for b in bits_g]
        values_a = [bf16(b) for b in bits_a] if len(bits_a) == len(bits_g) else []
        if values_g != golden['output_values']:
            raise ValueError('golden values disagree with golden bits')
        if values_a:
            delta = [a - g for a, g in zip(values_a, values_g)]
            absolute = [abs(d) for d in delta]
            mismatches = [i for i, (a, g) in enumerate(zip(bits_a, bits_g)) if a != g]
            result.update(golden_bits=bits_g, actual_bits=bits_a, golden=values_g, actual=values_a, delta=delta,
                          absolute_delta=absolute, mismatch_indices=mismatches, bit_mismatch_count=len(mismatches),
                          max_absolute_delta=max(absolute), mae=fmean(absolute),
                          rmse=math.sqrt(fmean(d * d for d in delta)), shape_match=True)
        else:
            result.update(golden_bits=bits_g, actual_bits=bits_a, golden=values_g, actual=None, shape_match=False,
                          bit_mismatch_count=len(bits_g))
        numeric_ok = result['shape_match'] and result['bit_mismatch_count'] == 0
    else:
        result.update(golden_bits=[], actual_bits=bits_a, shape_match=not bits_a, bit_mismatch_count=len(bits_a))
        numeric_ok = not bits_a
    if operator == 'p1' and golden.get('selected_token_ids') is not None and expected == 'OK':
        flat = [t for ids in golden['selected_token_ids'] for t in ids]
        actual = observation.get('selected')
        if actual is None and observation.get('selected_token_ids') is not None:
            actual = [t for ids in observation['selected_token_ids'] for t in ids]
        result['actual_selected'] = actual
        result['selection_match'] = actual == flat
        numeric_ok = numeric_ok and result['selection_match']
    if 'primitive_witness_result' in golden:
        result['primitive_match'] = observation.get('primitive') == golden['primitive_witness_result']
        numeric_ok = numeric_ok and result['primitive_match']
    result['status'] = 'PASS' if result['status_match'] and numeric_ok else 'FAIL'
    return result


def summarize_case(rows: list) -> dict:
    rows = sorted(rows, key=lambda r: r['seed'])
    if [r['seed'] for r in rows] != list(range(1, 11)):
        raise ValueError('every case requires seeds 1..10 exactly once')
    numeric = [r['comparison'] for r in rows if r['comparison'].get('golden_bits')]
    summary = dict(case_id=rows[0]['case']['id'], operator=rows[0]['case']['operator'], scenario=rows[0]['case']['scenario'],
                   expected_status=rows[0]['golden']['expected_status'],
                   failed_seeds=[r['seed'] for r in rows if r['comparison']['status'] != 'PASS'],
                   per_seed=[dict(seed=r['seed'], status=r['comparison']['status'],
                                  max_absolute_delta=r['comparison'].get('max_absolute_delta'),
                                  mae=r['comparison'].get('mae'), rmse=r['comparison'].get('rmse'),
                                  bit_mismatch_count=r['comparison'].get('bit_mismatch_count'),
                                  actual_status=r['comparison']['actual_status']) for r in rows])
    summary['status'] = 'PASS' if not summary['failed_seeds'] else 'FAIL'
    if len(numeric) == 10 and all(c.get('actual') is not None for c in numeric):
        width = len(numeric[0]['golden'])
        mean_g = [fmean(c['golden'][i] for c in numeric) for i in range(width)]
        mean_a = [fmean(c['actual'][i] for c in numeric) for i in range(width)] if all(len(c['golden']) == width for c in numeric) else None
        summary.update(mean_golden=mean_g, mean_actual=mean_a,
                       mean_difference=[a - g for a, g in zip(mean_a, mean_g)] if mean_a else None,
                       max_absolute_delta=max(c['max_absolute_delta'] for c in numeric),
                       mean_absolute_error=fmean(c['mae'] for c in numeric),
                       rmse=math.sqrt(fmean(c['rmse'] ** 2 for c in numeric)),
                       bit_mismatch_count=sum(c['bit_mismatch_count'] for c in numeric))
    elif numeric:
        # Variable output shapes across seeds: aggregate only scalar statistics.
        summary.update(mean_golden=None, mean_actual=None, mean_difference=None,
                       max_absolute_delta=max((c.get('max_absolute_delta') or 0) for c in numeric),
                       mean_absolute_error=fmean((c.get('mae') or 0) for c in numeric),
                       rmse=math.sqrt(fmean((c.get('rmse') or 0) ** 2 for c in numeric)),
                       bit_mismatch_count=sum(c['bit_mismatch_count'] for c in numeric))
    counters = {}
    for name in COUNTERS:
        raw = [r['observation'].get(name) for r in rows]
        counters[name] = dict(raw=raw, mean=fmean(raw) if all(isinstance(v, (int, float)) for v in raw) else None)
    summary['counters'] = counters
    return summary


def verify_platform(platform: str, result_files: list, vectors: dict) -> dict:
    """Return normalized, independently verified records for one platform."""
    records = {}
    sources = []
    for path in result_files:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('platform') != platform:
            raise ValueError(f'{path} is not a {platform} result')
        sources.append(str(path))
        for row in payload['records']:
            key = (row['case']['id'], row['seed'])
            if key in records:
                raise ValueError(f'duplicate {platform} record {key}')
            ordinal, golden_row = vectors[key]
            if row['golden'] != golden_row['golden'] or row['inputs'] != golden_row['inputs'] or row['case'] != golden_row['case']:
                raise ValueError(f'{platform} record {key} is not bound to the frozen golden vector')
            observation = row['observation']
            records[key] = dict(ordinal=ordinal, case=golden_row['case'], seed=row['seed'], prng=golden_row['prng'],
                                inputs=golden_row['inputs'], golden=golden_row['golden'], observation=observation,
                                comparison=compare(golden_row['golden'], observation, golden_row['case']['operator']))
    if set(records) != set(vectors):
        missing = sorted(set(vectors) - set(records))[:5]
        raise ValueError(f'{platform} records incomplete; e.g. missing {missing}')
    by_case = defaultdict(list)
    for row in records.values():
        by_case[row['case']['id']].append(row)
    cases = [summarize_case(rows) for _, rows in sorted(by_case.items())]
    ordered = [records[k] for k in sorted(records, key=lambda k: records[k]['ordinal'])]
    return dict(platform=platform, sources=sources, records=ordered, cases=cases,
                counts=dict(records=len(ordered), passed=sum(r['comparison']['status'] == 'PASS' for r in ordered),
                            cases=len(cases), cases_passed=sum(c['status'] == 'PASS' for c in cases)))
