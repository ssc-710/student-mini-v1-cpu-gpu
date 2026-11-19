#!/usr/bin/env python3
"""Verify an unpacked student-mini-v1 package without any EDA tool (Python 3 standard library only).

    python3 verify_release.py [package-dir]

1. every file listed in MANIFEST.sha256 exists and matches its SHA-256;
2. every physical/power evidence file listed in evidence-index.json exists and
   matches its SHA-256; gzip members decompress to the SHA-256 of the original
   (pre-gzip) file; aliases point at a packaged file with the same content;
   files listed as omitted (not packaged for the size limit) are bound by
   SHA-256 to a packaged power record (activity_sha256);
3. every power record (power/<impl>/**.json 'records', accelerator profile.json
   'loads', data/summary/physical.json) that records netlist_sha256/spef_sha256
   names the pre-gzip SHA-256 of a packaged 6_final.v / 6_final.spef of the same
   implementation;
4. every platform record is re-compared against the frozen golden vectors
   from raw BF16 bit patterns (status, bits, P1 selection, primitive witness),
   independently of the comparison stored next to it;
5. record counts, case/seed coverage (10 seeds per case) and the record
   statuses in release.json agree with the recomputed results;
6. course packages (release.json "course"): only the course platforms are
   checked, no records of an excluded platform are shipped, and every entry of
   data/candidates.json is NOT_RUN without PROMOTE.
Exit code 0 only if all checks pass (the release itself may still be PARTIAL).
"""
import gzip
import hashlib
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def gunzip_sha(path):
    digest = hashlib.sha256()
    with gzip.open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def bf16(bits):
    return struct.unpack('<f', struct.pack('<I', bits << 16))[0]


def check_manifest(root, problems):
    hashes = {}
    for line in (root / 'MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = root / name
        actual = sha(path) if path.is_file() else None
        hashes[name] = actual
        if actual != digest:
            problems.append('manifest mismatch: ' + name)
    return hashes


def recorded_shas(value):
    """netlist/SPEF SHA-256 values of a power record (a string, or a list/dict of them for hierarchical designs)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    return []


def power_rows(value):
    rows = []
    if isinstance(value, dict):
        for key in ('records', 'loads'):
            if isinstance(value.get(key), list):
                rows += [r for r in value[key] if isinstance(r, dict)]
    return rows


def check_evidence(root, hashes, problems):
    """Evidence index: presence, packaged SHA, pre-gzip SHA, aliases, and power-to-netlist/SPEF binding."""
    index_path = root / 'evidence-index.json'
    if not index_path.is_file():
        return None
    index = json.loads(index_path.read_text(encoding='utf-8'))
    entries = index.get('files') or []
    by_path = {e['path']: e for e in entries}
    checked = 0
    for e in entries:
        if e.get('alias_of'):
            target = by_path.get(e['alias_of'])
            if not target or target.get('alias_of') or target.get('source_sha256') != e.get('source_sha256'):
                problems.append(f"evidence alias {e['path']} -> {e['alias_of']} does not resolve to the same content")
            continue
        path = root / e['path']
        if not path.is_file():
            problems.append('evidence file missing: ' + e['path'])
            continue
        digest = hashes.get(e['path']) or sha(path)
        if digest != e.get('sha256'):
            problems.append('evidence SHA-256 mismatch: ' + e['path'])
            continue
        if e.get('compressed'):
            try:
                if gunzip_sha(path) != e.get('source_sha256'):
                    problems.append('evidence pre-gzip SHA-256 mismatch: ' + e['path'])
            except (OSError, EOFError) as error:
                problems.append(f"evidence gzip unreadable: {e['path']} ({error})")
        elif e.get('source_sha256') != digest:
            problems.append('evidence source SHA-256 mismatch: ' + e['path'])
        checked += 1
    # pre-gzip SHA-256 of the packaged final netlists / parasitics per implementation
    finals = {'netlist': defaultdict(set), 'spef': defaultdict(set)}
    for e in entries:
        if e.get('kind') != 'physical':
            continue
        base = e['path'].rsplit('/', 1)[-1]
        if base in ('6_final.v', '6_final.v.gz'):
            finals['netlist'][e['implementation']].add(e.get('source_sha256'))
        elif base in ('6_final.spef', '6_final.spef.gz'):
            finals['spef'][e['implementation']].add(e.get('source_sha256'))
    sources = []
    for e in entries:
        if not e.get('alias_of') and e['path'].endswith('.json') and (root / e['path']).is_file() \
                and (e.get('kind') == 'power' or e['path'].endswith('/profile.json')):
            sources.append((e['implementation'], e['path'], root / e['path']))
    bound = unpackaged = 0
    values = [(impl, label, json.loads(path.read_text(encoding='utf-8'))) for impl, label, path in sources]
    physical_json = root / 'data/summary/physical.json'
    if physical_json.is_file():
        for impl, value in json.loads(physical_json.read_text(encoding='utf-8')).items():
            values.append((impl, 'data/summary/physical.json', (value or {}).get('power') or {}))
    for impl, label, value in values:
        for record in power_rows(value):
            # hierarchical records (GPU) also name each block's netlist/SPEF under 'blocks': {design: {...}}
            for row in [record] + [v for v in (record.get('blocks') or {}).values() if isinstance(v, dict)]:
                for field, kind in (('netlist_sha256', 'netlist'), ('spef_sha256', 'spef')):
                    for digest in recorded_shas(row.get(field)):
                        if not finals[kind][impl]:
                            # no final view of this implementation packaged: a release gate (PARTIAL), not an integrity error
                            unpackaged += 1
                            continue
                        bound += 1
                        if digest not in finals[kind][impl]:
                            problems.append(f"{label}: {impl} {record.get('operator')} seed {record.get('seed')} {field} {digest[:16]} "
                                            f"is not a packaged 6_final.{'v' if kind == 'netlist' else 'spef'} of {impl}")
    # files deliberately not packaged (size limit) must still be bound by SHA-256 to a packaged power record
    activity = defaultdict(set)
    for impl, label, value in values:
        for row in power_rows(value):
            if isinstance(row.get('activity_sha256'), str):
                activity[impl].add(row['activity_sha256'])
    omitted = index.get('omitted') or []
    for o in omitted:
        impl = o['path'].split('/')[1] if o.get('path', '').count('/') >= 2 else None
        if o['path'] in by_path:
            problems.append(f"omitted evidence {o['path']} is also listed as packaged")
        elif not o.get('sha256') or o['sha256'] not in activity.get(impl, ()):
            problems.append(f"omitted evidence {o['path']}: SHA-256 {str(o.get('sha256'))[:16]} not bound to a packaged power record of {impl}")
    return dict(files=checked, aliases=sum(bool(e.get('alias_of')) for e in entries), power_bindings_checked=bound,
                power_bindings_without_packaged_view=unpackaged, missing_at_packaging=index.get('missing') or [],
                omitted_files=len(omitted), omitted_bytes=sum(o.get('bytes') or 0 for o in omitted))


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    problems = []
    hashes = check_manifest(root, problems)
    evidence = check_evidence(root, hashes, problems)
    golden = [json.loads(l) for l in (root / 'data/golden/vectors.jsonl').read_text(encoding='utf-8').splitlines()]
    release = json.loads((root / 'release.json').read_text(encoding='utf-8'))
    counts = {}
    course = release.get('course')
    platforms = tuple(course['platforms']) if course else ('cpu', 'gpu', 'accelerator')
    if course:
        for excluded in course.get('excluded_platforms') or {}:
            if (root / f'data/records/{excluded}.jsonl').exists() or (root / f'data/arrays/{excluded}.npz').exists():
                problems.append(f'records of excluded platform {excluded} are shipped in a {course["id"]} package')
    candidates_path = root / 'data/candidates.json'
    candidate_count = None
    if candidates_path.is_file():
        entries = json.loads(candidates_path.read_text(encoding='utf-8')).get('candidates') or []
        candidate_count = len(entries)
        bad = [c for c in entries if c.get('status') != 'NOT_RUN' or c.get('promote') is not False or c.get('platform') not in platforms]
        if bad:
            problems.append(f'{len(bad)} candidate entries are not NOT_RUN/no-PROMOTE for an included platform')
    for platform in platforms:
        rows = [json.loads(l) for l in (root / f'data/records/{platform}.jsonl').read_text(encoding='utf-8').splitlines()]
        seen = defaultdict(set)
        statuses = defaultdict(int)
        for row in rows:
            g = golden[row['ordinal']]
            if row['case'] != g['case'] or row['seed'] != g['seed']:
                problems.append(f'{platform} {row["ordinal"]}: case/seed not bound to the golden vector')
                continue
            seen[row['case']['id']].add(row['seed'])
            obs, exp = row['observation'], g['golden']
            ok = obs.get('actual_status') == exp['expected_status']
            bits = obs.get('actual_bits') or []
            ok = ok and bits == (exp.get('output_bits') or [])
            ok = ok and all(bf16(b) == v for b, v in zip(exp.get('output_bits') or [], exp.get('output_values') or []))
            if g['case']['operator'] == 'p1' and exp.get('selected_token_ids') is not None and exp['expected_status'] == 'OK':
                selected = obs.get('selected')
                if selected is None and obs.get('selected_token_ids') is not None:
                    selected = [t for ids in obs['selected_token_ids'] for t in ids]
                ok = ok and selected == [t for ids in exp['selected_token_ids'] for t in ids]
            if 'primitive_witness_result' in exp:
                ok = ok and obs.get('primitive') == exp['primitive_witness_result']
            stored = row['comparison']['status'] == 'PASS'
            if ok != stored:
                problems.append(f'{platform} {row["ordinal"]}: stored comparison {stored} != recomputed {ok}')
            if row['status'] == 'PASS' and (not ok or row['events']['missing_events']):
                problems.append(f'{platform} {row["ordinal"]}: PASS without bit-exact result and all expected events')
            statuses[row['status']] += 1
        if len(rows) != len(golden) or any(sorted(s) != list(range(1, 11)) for s in seen.values()):
            problems.append(f'{platform}: incomplete case/seed coverage')
        counts[platform] = dict(statuses)
    report = dict(release_status=release['status'], record_status=counts, evidence=evidence,
                  problems=problems[:50], problem_count=len(problems))
    if course:
        report.update(course=course.get('id'), platforms=list(platforms), candidates=candidate_count)
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
