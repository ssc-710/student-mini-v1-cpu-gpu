"""Offline, standard-library-only case reader. This never executes target hardware."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import compare_outputs, summarize_seeds


def load_report(path, expected_sha):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha):
        raise ValueError('supply the full published report SHA-256, not a checksum prefix')
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('report SHA-256 mismatch; keep the original and ask for the correct file')
    report = json.loads(raw)
    if report.get('platform') not in ('cpu', 'gpu', 'accelerator') or not isinstance(report.get('records'), list):
        raise ValueError('full platform result report required, not a screenshot or summary')
    groups = {}
    for row in report['records']:
        case = row['case']['id']; seed = row['seed']
        if type(seed) is not int or seed not in range(1, 11) or row['status'] not in ('PASS', 'HOLD', 'FAIL'):
            raise ValueError('invalid seed or stored case status')
        group = groups.setdefault(case, {})
        if seed in group:
            raise ValueError('duplicate case/seed')
        group[seed] = row
    if not groups or any(sorted(group) != list(range(1, 11)) for group in groups.values()):
        raise ValueError('every case must contain exactly seeds 1..10; missing seeds cannot pass')
    return report, groups


def inspect_case(report, groups, case_id, seed=None):
    if case_id not in groups:
        raise ValueError('unknown case ID; use --list-cases first')
    if seed is not None and (type(seed) is not int or seed not in range(1, 11)):
        raise ValueError('seed must be 1..10')
    rows = [groups[case_id][n] for n in range(1, 11)]
    checked = []
    numerical_rows = []
    for row in rows:
        golden = row['golden']; observation = row.get('observation')
        result = dict(case=row['case'], seed=row['seed'], prng=row.get('prng'), inputs=row['inputs'],
                      golden=golden, actual_observation=observation, stored_status=row['status'],
                      recorded_comparison=row.get('comparison'), recomputed_bf16=None)
        if observation is not None and golden['expected_status'] == 'OK' and observation.get('actual_status') == 'OK':
            comparison = compare_outputs(golden['output_values'], observation['actual'],
                                         golden['output_bits'], observation['actual_bits'])
            result['recomputed_bf16'] = comparison
            numerical_rows.append(dict(seed=row['seed'], **comparison))
        checked.append(result)
    summary = summarize_seeds(numerical_rows) if len(numerical_rows) == 10 else None
    counter_summary = {}
    for name in ('cycles', 'instructions', 'dma_bytes', 'cache_bytes'):
        values = [(row.get('observation') or {}).get(name) for row in rows]
        complete = all(type(v) is int and v >= 0 for v in values)
        counter_summary[name] = dict(raw=values, complete=complete,
                                     mean=sum(values)/10 if complete else None)
    return dict(status='OFFLINE_INSPECTION_ONLY', platform=report['platform'], case_id=case_id,
                hardware_executed=False, baseline_qualified=False,
                stored_status_counts=dict(Counter(row['status'] for row in rows)),
                failed_or_held_seeds=[row['seed'] for row in rows if row['status'] != 'PASS'],
                ten_seed_bf16_summary=summary, counter_summary=counter_summary,
                note='Numeric agreement does not override protocol, physical, Nano or source-binding HOLD. Error cases retain their actual status/event records; no zero deltas are invented.',
                records=checked if seed is None else [checked[seed-1]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--sha256', required=True, help='published full result-report SHA-256')
    select = parser.add_mutually_exclusive_group(required=True)
    select.add_argument('--list-cases', action='store_true')
    select.add_argument('--case', dest='case_id')
    seeds = parser.add_mutually_exclusive_group()
    seeds.add_argument('--seed', type=int, choices=range(1, 11))
    seeds.add_argument('--all-seeds', action='store_true')
    args = parser.parse_args()
    if args.list_cases and (args.seed is not None or args.all_seeds):
        parser.error('seed selection requires --case')
    try:
        report, groups = load_report(args.report, args.sha256)
        if args.list_cases:
            result = dict(status='OFFLINE_INSPECTION_ONLY', hardware_executed=False,
                          baseline_qualified=False, platform=report['platform'], cases=sorted(groups))
        else:
            result = inspect_case(report, groups, args.case_id, args.seed)
        result['report_sha256'] = args.sha256
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(status='INSPECTION_ERROR', reason=str(error)), ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
