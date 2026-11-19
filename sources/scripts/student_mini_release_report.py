"""Offline HTML report for the student-mini release (single self-contained file).

The page opens on one full-screen panorama: the production process of the package
as a process diagram (modules, sub-modules, typed edges, iteration loops with the
counts found in the evidence), why it took as long as it did, and what the package
contains.  Every module / sub-module is a link into a detail view (hash routing,
browser Back returns); detail views render lazily from embedded JSON and keep the
full record drill-down: every summary row links to its case, every case lists its
ten seeds, every seed shows inputs, golden bits/values, actual bits/values and
per-element deltas.  No network access, no external assets.

The diagram is not hard-coded: it is generated from the course's declarative
process graph (integration/student-mini/release/process-graph-<course>.json) by
scripts/student_mini_process_graph.py, so the same renderer serves the
CPU + accelerator course, the CPU + GPU course and the three-platform release.

    render(summary, platforms)                    # as called by assemble_student_mini_release.py
    render(summary, platforms, package_dir=DIR)   # binds package files (SPEC, data/, physical/, ...)

    python3 scripts/student_mini_release_report.py --package DIR --out FILE.html   # re-render an existing package
    python3 scripts/student_mini_release_report.py --check GRAPH.json [--package DIR] # validate a graph file
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.student_mini_process_graph import Bundle, graph_path, load_graph, panorama_svg, validate  # noqa: E402

ASSETS = Path(__file__).resolve().parent / 'student_mini_report_assets'


def compact_record(platform, row):
    c = row['comparison']
    obs = row['observation']
    return dict(ordinal=row['ordinal'], case=row['case']['id'], seed=row['seed'], status=c['status'],
                expected_status=c['expected_status'], actual_status=c['actual_status'],
                golden_bits=c.get('golden_bits') or [], golden=c.get('golden') or [], actual_bits=c.get('actual_bits'),
                actual=c.get('actual'), delta=c.get('delta'), max_abs=c.get('max_absolute_delta'), mae=c.get('mae'),
                rmse=c.get('rmse'), mismatch=c.get('bit_mismatch_count'),
                cycles=obs.get('cycles'), counters={k: obs.get(k) for k in ('cycles', 'instructions', 'dma_bytes', 'cache_bytes')},
                source=obs.get('backend'), events=row.get('events'), main=row.get('main_execution') is not None)


def compact_case(case):
    return dict(case_id=case['case_id'], operator=case.get('operator'), scenario=case.get('scenario'), expected_status=case.get('expected_status'),
                status=case.get('status'), failed_seeds=case.get('failed_seeds'), held_seeds=case.get('held_seeds'),
                max_absolute_delta=case.get('max_absolute_delta'), mean_absolute_error=case.get('mean_absolute_error'), rmse=case.get('rmse'),
                bit_mismatch_count=case.get('bit_mismatch_count'), cycles_mean=((case.get('counters') or {}).get('cycles') or {}).get('mean'))


def embed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str).replace('</', '<\\/')


def graph_for(summary, graph=None):
    if isinstance(graph, dict):
        return graph, None
    path = Path(graph) if graph else graph_path((summary.get('course') or {}).get('id'))
    return load_graph(path), path


def render(summary: dict, platforms: dict, package_dir=None, graph=None) -> str:
    """Self-contained report.html.  package_dir binds the package files; graph overrides the course's graph file."""
    graph, path = graph_for(summary, graph)
    errors = validate(graph)
    if errors:
        raise ValueError(f'process graph {path}: ' + '; '.join(errors[:10]))
    first = next(iter(platforms.values()))
    records = dict(records={p: [compact_record(p, r) for r in v['records']] for p, v in platforms.items()},
                   inputs={r['ordinal']: r['inputs'] for r in first['records']},
                   cases={p: [compact_case(c) for c in v.get('cases', [])] for p, v in platforms.items()})
    bundle = Bundle(graph, summary, platforms, package_dir)
    payload = bundle.payload()
    if path:
        rel = path.resolve().relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else str(path)
        payload['graph_file'] = dict(path=rel, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    svg = panorama_svg(bundle)
    css = (ASSETS / 'report.css').read_text(encoding='utf-8')
    js = (ASSETS / 'report.js').read_text(encoding='utf-8')
    name = summary.get('release_id', 'student-mini-v1')
    description = f"{name} 生产流程报告：流程全景、耗时根因、六类验收门与逐条记录（离线单文件）"
    return '\n'.join([
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{html.escape(name)} 生产流程报告</title><meta name="description" content="{html.escape(description)}">',
        f'<style>{css}</style></head><body class="on-pano">',
        f'<div id="pano">{svg}</div><div id="detail" hidden></div><button id="theme" type="button" title="切换浅色 / 深色">◐ 自动</button>',
        f'<script id="graph" type="application/json">{embed(payload)}</script>',
        f'<script id="data" type="application/json">{embed(records)}</script>',
        f'<script>{js}</script></body></html>'])


# ----------------------------------------------------------------------------- re-render an existing package

def platforms_from_package(package):
    """Rebuild render()'s platforms argument from a package's data/records/*.jsonl and golden vectors."""
    from scripts.student_mini_release_records import summarize_case
    vectors = [json.loads(line) for line in (package / 'data/golden/vectors.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    platforms = {}
    for path in sorted((package / 'data/records').glob('*.jsonl')):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        for row in rows:
            row['inputs'] = vectors[row['ordinal']]['inputs']
            digest = hashlib.sha256(json.dumps(row['inputs'], sort_keys=True).encode()).hexdigest()
            if digest != row.get('input_sha256'):
                raise ValueError(f'{path.name} ordinal {row["ordinal"]}: input SHA-256 does not match the golden vectors')
            row['comparison'] = dict(row['comparison'], status=row['status'])
        by_case = {}
        for row in rows:
            by_case.setdefault(row['case']['id'], []).append(row)
        cases = []
        for case_id, group in sorted(by_case.items()):
            case = summarize_case(group)
            case['status'] = 'FAIL' if any(r['status'] == 'FAIL' for r in group) else 'HOLD' if any(r['status'] == 'HOLD' for r in group) else 'PASS'
            cases.append(case)
        platforms[path.stem] = dict(records=rows, cases=cases)
    order = (json.loads((package / 'release.json').read_text(encoding='utf-8')).get('course') or {}).get('platforms')
    return {p: platforms[p] for p in order} if order else platforms


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--package', type=Path, help='unpacked release package directory')
    parser.add_argument('--out', type=Path, help='write the re-rendered report here (never into a sealed package)')
    parser.add_argument('--graph', type=Path, help='graph file (default: the course graph)')
    parser.add_argument('--check', type=Path, help='validate a graph file; with --package also list unresolved bindings')
    args = parser.parse_args()
    if args.check:
        graph = load_graph(args.check)
        errors = validate(graph)
        report = dict(graph=str(args.check), errors=errors)
        if args.package:
            summary = json.loads((args.package / 'release.json').read_text(encoding='utf-8'))
            bundle = Bundle(graph, summary, platforms_from_package(args.package), args.package)
            bundle.payload()
            panorama_svg(bundle)
            report['unresolved_bindings'] = sorted(set(bundle.missing))
            report['missing_notes'] = sorted({n for p in bundle.payload()['nodes'].values() for n in p['notes_missing']})
            report['guard_records_bound'] = len({n for nid in bundle.nodes for n in bundle.guard_names(nid)})
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if errors else 0
    if not (args.package and args.out):
        parser.error('--package and --out are required (or --check)')
    summary = json.loads((args.package / 'release.json').read_text(encoding='utf-8'))
    if args.out.resolve().parent == args.package.resolve():
        parser.error('refusing to write into the package: its MANIFEST.sha256 seals report.html')
    args.out.write_text(render(summary, platforms_from_package(args.package), args.package, args.graph), encoding='utf-8')
    print(json.dumps(dict(out=str(args.out), bytes=args.out.stat().st_size)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
