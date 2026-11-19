"""Assemble, package and verify the student-mini-v1 release from an explicit plan.

    python3 scripts/assemble_student_mini_release.py --plan PLAN.json --out DIR

The plan names every evidence input (results, protocol runs, physical runs,
power runs, Nano sessions, resource-guard records).  Every record is
re-verified against the frozen golden vectors (bits, status, selection,
primitive), its expected events are attested from named evidence, and the
release gates are evaluated; nothing missing is filled in.  The package is a
whitelist (no tool installers, environments, caches or intermediate ODBs):
data, offline HTML, SPEC, physical evidence (DEF/netlist/SPEF compressed,
SDC, logs, config), power per seed, Nano sessions, bound sources and a SHA-256
manifest.  It is zipped, measured, and verified again from a clean unzip.

Physical gates: the CPU is one route completion (plus its 25 ROM-bank runs when
the plan lists rom_banks); the GPU is either one completion or the hierarchical
entry {top, blocks[4], sta, partition}: every block/top run must be
PLATFORM_PHYSICAL_ROUTE_STAGE_PASS (DRC/antenna zero) and the full-chip STA
GPU_FULLCHIP_SIGNOFF_PASS (setup/hold WNS from it) and bound to those runs.

Packaging is enforced, not only reported: an expanded package above 3 GiB or a
ZIP above 1 GiB, a clean-unzip manifest mismatch, or a failing shipped verifier
(which also checks every indexed physical/power file, its pre-gzip SHA-256 and
the power records' netlist/SPEF SHA-256 against the packaged 6_final.v/.spef)
sets status REJECTED_PACKAGING, renames the archive *.REJECTED.zip and exits 1.

Course mode (plan key "course", cpu-accelerator or cpu-gpu from build_student_mini_release_plan.py --course):
only the course platforms are verified, gated, summarised and packaged (package/zip named by
course.package_name); release.json and report.html state the course, the included platforms and
implementations and the excluded platforms (the GPU belongs to the CPU+GPU course, the accelerator to the
CPU+专用加速器 course).  In the cpu-gpu course the GPU is the hierarchical entry above; GPU blocks continued
with --eco-from are listed as 'physical-eco-from' disclosures (with the predecessor files they rewrote).  The course package also
carries data/candidates.json (four candidate layers per baseline, NOT_RUN, no PROMOTE), the optional
model card / resource measurements named by the plan, and SPEC.json tools/host/memory_layout when given.
Without "course" the three-platform behaviour is unchanged.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_release_records import load_vectors, verify_platform, compare, summarize_case
from scripts.student_mini_release_events import accelerator_events, cpu_events, gpu_events, attest
from scripts.student_mini_release_report import render

PLATFORMS = ('cpu', 'gpu', 'accelerator')
OPERATORS = ('p1', 'p2', 'p3')
PROTOCOL = ('MINI-31', 'MINI-32', 'MINI-33')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def protocol_rows(path):
    """case/seed -> protocol run row (CPU or GPU protocol completion)."""
    if not path:
        return {}
    value = load(path)
    if not value['status'].endswith('QUALIFICATION_PASS'):
        return {}
    return {(r['case_id'], r['seed']): r for r in value['records']}


def apply_records(platform, verified, vectors, plan, gates):
    """Attach events (and, for MINI-31/32/33 on CPU/GPU, the protocol execution) to every record."""
    protocol = protocol_rows(plan.get(platform, {}).get('protocol'))
    raw, witness = {}, {}
    if platform == 'accelerator':
        for op in OPERATORS:
            for line in Path(plan['accelerator'][op]['raw']).read_text().splitlines():
                row = json.loads(line)
                raw[(row['case_id'], row['seed'])] = row
        if plan['accelerator'].get('witness'):
            for row in load(plan['accelerator']['witness'])['records']:
                if row.get('auxiliary_kind') and row.get('case_id'):
                    witness[(row['case_id'], row['seed'])] = row
    for row in verified['records']:
        key = (row['case']['id'], row['seed'])
        name = row['case']['id'].split('-', 1)[1]
        if platform != 'accelerator' and name in PROTOCOL and key in protocol:
            p = protocol[key]
            observation = dict(p['observation'], ordinal=row['ordinal'], backend=f'{platform}-protocol-run',
                               protocol_setting=p['setting'], protocol_events=p['events'])
            row['main_execution'] = row['observation']
            row['observation'] = observation
            row['comparison'] = compare(row['golden'], observation, row['case']['operator'])
        if platform == 'accelerator' and 'primitive_witness_result' in row['golden'] and key in witness:
            # The fixed-function accelerator has no instruction path for the primitive; its
            # witness ran on the platform's numeric RTL (component level) and is attached here.
            w = witness[key]
            row['observation'] = dict(row['observation'], primitive=w['actual'], primitive_source=f"component-RTL witness ({w['auxiliary_kind']})")
            row['comparison'] = compare(row['golden'], row['observation'], row['case']['operator'])
            row['witness_attached'] = True
        if platform == 'accelerator':
            events = accelerator_events(row, raw.get(key, {}), witness.get(key))
        elif platform == 'cpu':
            events = cpu_events(row, protocol.get(key))
        else:
            events = gpu_events(row, protocol.get(key))
        row['events'] = attest(row, events)
        if row['comparison']['status'] != 'PASS':
            row['status'] = 'FAIL'
        elif row['events']['missing_events']:
            row['status'] = 'HOLD'
        else:
            row['status'] = 'PASS'
    by_case = {}
    for row in verified['records']:
        by_case.setdefault(row['case']['id'], []).append(row)
    cases = []
    for case_id, rows in sorted(by_case.items()):
        summary = summarize_case(rows)
        summary['status'] = 'FAIL' if any(r['status'] == 'FAIL' for r in rows) else 'HOLD' if any(r['status'] == 'HOLD' for r in rows) else 'PASS'
        summary['held_seeds'] = [r['seed'] for r in rows if r['status'] == 'HOLD']
        summary['missing_events'] = sorted({e for r in rows for e in r['events']['missing_events']})
        cases.append(summary)
    verified['cases'] = cases
    verified['counts'] = dict(records=len(verified['records']), **{s: sum(r['status'] == s for r in verified['records']) for s in ('PASS', 'HOLD', 'FAIL')},
                              cases=len(cases), cases_passed=sum(c['status'] == 'PASS' for c in cases))
    gates[f'{platform}-records'] = verified['counts']['PASS'] == 1000
    return verified


ZIP_MAX_BYTES = 1 << 30
EXPANDED_MAX_BYTES = 3 << 30
REJECTED = 'REJECTED_PACKAGING'


def verify_tree(root, failures):
    """Run the shipped standard-library verifier on an unpacked tree (manifest, evidence index, power bindings, records)."""
    verifier = Path(root) / 'verify_release.py'
    if not verifier.is_file():
        failures.append('verify_release.py missing from the package')
        return None
    check = subprocess.run([sys.executable, '-I', str(verifier), str(root)], capture_output=True, text=True)
    if check.returncode:
        failures.append(f'verify_release.py exit {check.returncode}')
    try:
        report = json.loads(check.stdout)
    except ValueError:
        report = None
    return dict(exit_code=check.returncode, report=report, output=None if report else (check.stdout + check.stderr)[-4000:])


ROUTE_PASS = 'PLATFORM_PHYSICAL_ROUTE_STAGE_PASS'
ROM_BANK_PASS = 'ROM_BANK_PHYSICAL_STAGE_PASS'
STA_PASS = 'GPU_FULLCHIP_SIGNOFF_PASS'
POWER_KEYS = ('operator', 'case_id', 'seed', 'total_mw', 'dynamic_mw', 'leakage_mw', 'energy_j', 'begin_ns', 'end_ns',
              'window_seconds', 'annotation_percent', 'annotated_pins', 'total_pins', 'unannotated_pins', 'unannotated_percent',
              'checked_output_cycles', 'activity_sha256', 'netlist_sha256', 'spef_sha256')
ACC_POWER_KEYS = ('operator', 'case_id', 'seed', 'power_w', 'dynamic_mw', 'leakage_mw', 'energy_j', 'begin_ns', 'end_ns',
                  'annotation_percent', 'annotated_pins', 'total_pins', 'frequency_hz', 'activity_sha256', 'netlist_sha256', 'spef_sha256')


def stream_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def frequency_hz(clock_period_ns):
    return int(round(1e9 / clock_period_ns)) if isinstance(clock_period_ns, (int, float)) and clock_period_ns > 0 else None


def route_component(path, status=ROUTE_PASS, timing=True):
    """One route run (platform top, GPU block or CPU ROM bank): status, DRC/antenna, timing where it is signed off."""
    value = load(path)
    metrics = value.get('route_metrics') or {}
    ok = (value.get('status') == status and metrics.get('drc') == 0 and metrics.get('antenna_nets') == 0
          and (not timing or (isinstance(metrics.get('wns_ns'), (int, float)) and metrics['wns_ns'] >= 0
                              and isinstance(metrics.get('hold_wns_ns'), (int, float)) and metrics['hold_wns_ns'] >= 0)))
    result_directory = value.get('result_directory')
    return value, dict(completion=str(path), status=value.get('status'), passed=ok,
                       design=value.get('design') or (Path(result_directory).parent.name if result_directory else None),
                       drc=metrics.get('drc'), antenna_nets=metrics.get('antenna_nets'), antenna_pins=metrics.get('antenna_pins'),
                       wns_ns=metrics.get('wns_ns'), hold_wns_ns=metrics.get('hold_wns_ns'),
                       budget_setup_ws_ns=metrics.get('budget_setup_ws_ns'), budget_hold_ws_ns=metrics.get('budget_hold_ws_ns'),
                       macro_audit=value.get('macro_audit'), report_metrics=value.get('report_metrics'),
                       result_directory=result_directory)


def total(rows, key):
    values = [r.get(key) for r in rows]
    return sum(values) if values and all(type(v) is int for v in values) else None


def gpu_hierarchical_route(entry):
    """GPU = 4 block route runs + top route run, timed by the full-chip STA of the assembled netlists."""
    reasons = []
    components = []
    if entry.get('top'):
        _, top = route_component(entry['top'], timing=False)
        components.append(dict(top, role='top'))
    else:
        reasons.append('top route run missing')
    blocks = [route_component(p, timing=False)[1] for p in entry.get('blocks') or []]
    components += [dict(b, role='block') for b in blocks]
    if len(blocks) != 4:
        reasons.append(f'{len(blocks)} of 4 block route runs')
    reasons += [f"{c['role']} {c['design']}: {c['status']}" for c in components if not c['passed']]
    sta = load(entry['sta']) if entry.get('sta') else None
    if not sta:
        reasons.append('full-chip STA missing')
    else:
        if sta.get('status') != STA_PASS:
            reasons.append(f"full-chip STA {sta.get('status')}: {sta.get('reason')}")
        for key in ('setup_wns_ns', 'hold_wns_ns'):
            if not isinstance(sta.get(key), (int, float)) or sta[key] < 0:
                reasons.append(f'full-chip STA {key} = {sta.get(key)}')
        bound = set((sta.get('bindings') or {}).values())
        unbound = [c['design'] for c in components if stream_sha(c['completion']) not in bound]
        if unbound:
            reasons.append(f'full-chip STA not bound to the packaged route runs: {unbound}')
    partition = load(entry['partition']) if entry.get('partition') else None
    if partition and not str(partition.get('status', '')).endswith('STAGE_PASS'):
        reasons.append(f"partition {partition.get('status')}")
    ok = not reasons
    clock = (sta or {}).get('clock_period_ns', 10)
    metrics = dict(clock_period_ns=clock, frequency_hz=frequency_hz(clock), timing_signoff='full-chip STA',
                   wns_ns=(sta or {}).get('setup_wns_ns'), tns_ns=(sta or {}).get('setup_tns_ns'),
                   hold_wns_ns=(sta or {}).get('hold_wns_ns'), hold_tns_ns=(sta or {}).get('hold_tns_ns'),
                   drc=total(components, 'drc'), antenna_nets=total(components, 'antenna_nets'),
                   antenna_pins=total(components, 'antenna_pins'))
    route = dict(status='GPU_HIERARCHICAL_SIGNOFF_PASS' if ok else 'HOLD', reasons=reasons, metrics=metrics,
                 components=components, fullchip_sta=sta and dict(completion=entry['sta'], status=sta.get('status'), reason=sta.get('reason'),
                                                                   setup_wns_ns=sta.get('setup_wns_ns'), setup_tns_ns=sta.get('setup_tns_ns'),
                                                                   hold_wns_ns=sta.get('hold_wns_ns'), hold_tns_ns=sta.get('hold_tns_ns'),
                                                                   peak_rss_bytes=sta.get('peak_rss_bytes')),
                 partition=partition and dict(completion=entry['partition'], status=partition.get('status'), blocks=partition.get('blocks'),
                                              flat_logic_cells=partition.get('flat_logic_cells')))
    return route, ok, frequency_hz(clock)


def single_route(entry, name):
    """Single-completion platform run (CPU top, legacy GPU), plus the CPU's ROM-bank hard blocks when listed."""
    route = load(entry['physical']) if entry.get('physical') else None
    if not route:
        return None, False, None
    ok = route['status'] == ROUTE_PASS
    clock = route.get('clock_period_ns') or (route.get('route_metrics') or {}).get('clock_period_ns')
    out = dict(status=route['status'], metrics=dict(route.get('route_metrics') or {}, frequency_hz=frequency_hz(clock)),
               macro_audit=route.get('macro_audit'), report_metrics=route.get('report_metrics'),
               result_directory=route.get('result_directory'))
    banks = entry.get('rom_banks')
    if name == 'cpu' and banks is not None:
        rows = [dict(route_component(p, status=ROM_BANK_PASS)[1], bank=load(p).get('bank')) for p in banks]
        out['rom_banks'] = rows
        out['rom_banks_passed'] = sum(r['passed'] for r in rows)
        ok = ok and len(rows) == 25 and sorted(r['bank'] for r in rows) == list(range(25)) and all(r['passed'] for r in rows)
    return out, ok, frequency_hz(clock)


def physical_summary(plan, gates, platforms=PLATFORMS):
    """Five unique implementations (fewer in course mode): route signoff, macro audit, per-seed power."""
    out = {}
    for name in [p for p in ('cpu', 'gpu') if p in platforms]:
        entry = plan.get(name, {})
        if isinstance(entry.get('physical'), dict):
            route, ok_route, freq = gpu_hierarchical_route(entry['physical'])
        else:
            route, ok_route, freq = single_route(entry, name)
        power = load(entry['power']) if entry.get('power') else None
        ok_power = bool(power and power['status'].endswith('GATE_POWER_STAGE_PASS'))
        out[name] = dict(frequency_hz=freq, route=route,
                         power=power and dict(status=power['status'], summary=power.get('summary'), corner=power.get('corner'),
                                              frequency_hz=power.get('frequency_hz'), window=power.get('window'), boundary=power.get('boundary'),
                                              records=[{k: r.get(k) for k in POWER_KEYS} for r in power.get('records', [])]))
        gates[f'{name}-physical'] = ok_route
        gates[f'{name}-power'] = ok_power and len(power.get('records', [])) == 30
    for op in OPERATORS if 'accelerator' in platforms else ():
        entry = plan['accelerator'][op]
        profile = load(Path(entry['package']) / 'profile.json') if entry.get('package') else None
        name = f'accelerator-{op}'
        # profile.json records setup WNS only; hold WNS comes from the packaged ORFS finish metrics (raw/finish.json),
        # so the accelerators are signed off on setup and hold like the CPU and GPU runs
        finish = Path(entry['package']) / 'raw/finish.json' if entry.get('package') else None
        hold = load(finish).get('finish__timing__hold__ws') if finish and finish.is_file() else None
        ok = bool(profile and profile.get('physical_evidence_complete') and profile['route_metrics']['wns_ns'] >= 0
                  and isinstance(hold, (int, float)) and hold >= 0
                  and profile['route_metrics']['drc'] == 0 and profile['route_metrics']['antenna_nets'] == 0)
        freq = profile and (profile.get('frequency_hz') or frequency_hz(profile.get('clock_period_ns')))
        out[name] = dict(frequency_hz=freq,
                         route=profile and dict(status='PASS' if ok else 'FAIL',
                                                metrics=dict(profile['route_metrics'], hold_wns_ns=hold, frequency_hz=freq),
                                                macro_pin_access=profile.get('macro_pin_access')),
                         power=profile and dict(status='PASS' if len(profile.get('loads', [])) == 10 else 'INCOMPLETE',
                                                frequency_hz=freq, corner=ACCELERATOR_CORNER,
                                                window='begin_ns..end_ns of each load (gate-level simulation of the command)',
                                                records=[dict({k: l.get(k) for k in ACC_POWER_KEYS},
                                                              unannotated_pins=(l['total_pins'] - l['annotated_pins'])
                                                              if isinstance(l.get('total_pins'), int) and isinstance(l.get('annotated_pins'), int) else None)
                                                         for l in profile.get('loads', [])]))
        gates[f'{name}-physical'] = ok
        gates[f'{name}-power'] = bool(profile and len(profile.get('loads', [])) == 10)
    return out


ACCELERATOR_CORNER = dict(process='sky130hd tt', voltage_v=1.8, temperature_c=25)


def copy_entry(source, target, compress):
    """Copy (gzip when compress) and return the SHA-256 and size of the source bytes as read."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with Path(source).open('rb') as src, target.open('xb') as raw:
        dst = gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) if compress else raw
        try:
            for chunk in iter(lambda: src.read(1 << 20), b''):
                digest.update(chunk)
                size += len(chunk)
                dst.write(chunk)
        finally:
            if compress:
                dst.close()
    return digest.hexdigest(), size


def package_evidence(plan, package):
    """physical/<component>/... and power/<implementation>/...; returns the evidence index rows."""
    rows = []
    for section, key in (('physical', 'physical_files'), ('power', 'power_files')):
        for component, files in (plan.get(key) or {}).items():
            for name, entry in files.items():
                entry = entry if isinstance(entry, dict) else dict(source=entry, sha256=None,
                                                                    compress=name.endswith('.gz') and not str(entry).endswith('.gz'))
                rel = f'{section}/{component}/{name}'
                source_sha, size = copy_entry(entry['source'], package / rel, entry['compress'])
                if entry.get('sha256') and entry['sha256'] != source_sha:
                    raise ValueError(f"{entry['source']} changed since its run recorded it ({entry['sha256']} != {source_sha})")
                rows.append(dict(path=rel, kind=section, component=component, implementation=component.split('/')[0],
                                 source=str(entry['source']), source_sha256=source_sha, source_bytes=size,
                                 compressed=bool(entry['compress'])))
    by_path = {r['path']: r for r in rows}
    for alias, canonical in (plan.get('physical_aliases') or {}).items():
        if canonical not in by_path:
            raise ValueError(f'alias {alias} -> {canonical}: canonical file not packaged')
        section, component = alias.split('/', 2)[:2]
        rows.append(dict(path=alias, kind=section, component=component, implementation=component.split('/')[0],
                         alias_of=canonical, source_sha256=by_path[canonical]['source_sha256'],
                         compressed=by_path[canonical]['compressed']))
    for row in rows:
        if not row.get('alias_of'):
            row['sha256'] = stream_sha(package / row['path'])
            row['bytes'] = (package / row['path']).stat().st_size
    return sorted(rows, key=lambda r: r['path'])


def evidence_gate(rows, gates, implementations=('cpu', 'gpu', *(f'accelerator-{op}' for op in OPERATORS))):
    """Every implementation ships final DEF, netlist, SPEF and SDC, and its power evidence."""
    have = {}
    for row in rows:
        have.setdefault((row['kind'], row['implementation']), set()).add(row['path'].rsplit('/', 1)[-1])
    required = {'6_final.def.gz', '6_final.v.gz', '6_final.spef.gz', '6_final.sdc'}
    missing = []
    for impl in implementations:
        names = have.get(('physical', impl), set())
        missing += [f'physical/{impl}: {n}' for n in sorted(required - names)]
        if not have.get(('power', impl)):
            missing.append(f'power/{impl}: no files')
    gates['physical-power-files'] = not missing
    return missing


def nano_summary(plan, gates, platforms=PLATFORMS):
    """12 frozen test questions x every included platform: session status, exact token sequence vs the candidate's PTQ reference."""
    candidate = load(plan['nano_candidate'])
    expected = candidate['quality']['ptq_exact']
    passing = ('NUMERICAL_SESSION_STAGE_PASS', 'NUMERICAL_OPERATOR_SESSION_STAGE_PASS')
    out = {}
    for platform in platforms:
        sessions = {}
        for path in plan['nano'].get(platform, []):
            value = load(path)
            if value.get('platform') != platform:
                raise ValueError(f'{path} is not a {platform} session')
            sessions.setdefault(value['question'], []).append((path, value))
        rows, deployments = [], set()
        for index, ref in enumerate(expected):
            found = sessions.get(ref['question'], [])
            row = dict(index=index, question=ref['question'], domain=ref.get('domain'), expected_tokens=ref['tokens'],
                       expected_text=ref.get('answer'), status='MISSING')
            for path, value in found:
                tokens = [r['token'] for r in value.get('records', [])]
                ok = value.get('status') in passing and tokens == ref['tokens']
                row.update(session=path, session_sha256=sha(Path(path)), session_status=value.get('status'), tokens=tokens,
                           token_sha256=value.get('token_sha256'), backend=value.get('backend') or value.get('operator_backend'),
                           status='PASS' if ok else 'FAIL')
                deployments.add(json.dumps(value.get('deployment'), sort_keys=True))
                if ok:
                    break
            rows.append(row)
        out[platform] = dict(sessions=rows, deployments=len(deployments))
        gates[f'{platform}-nano'] = all(r['status'] == 'PASS' for r in rows) and len(deployments) == 1
    return out


def resources_summary(plan, gates):
    rows = []
    for path in plan.get('resources', []):
        value = load(path)
        events = {}
        for line in str(value.get('memory_events') or '').splitlines():
            key, _, count = line.partition(' ')
            if count.strip().isdigit():
                events[key] = int(count)
        rows.append(dict(record=Path(path).name, status=value.get('status'), cpu_limit=value.get('cpu_limit'),
                         memory_limit_bytes=value.get('memory_limit_bytes'), memory_peak_bytes=value.get('memory_peak_bytes'),
                         elapsed_seconds=value.get('elapsed_seconds'), exit_code=value.get('exit_code'),
                         memory_events=events or None, command=' '.join(value.get('command', []))[:300]))
    gates['resource-limits'] = bool(rows) and all(r['status'] == 'PASS' and r['cpu_limit'] == 2 and r['memory_limit_bytes'] == 8 << 30
                                                  and r['exit_code'] == 0 for r in rows)
    return rows


POWER_CSV_HEADER = ['implementation', 'operator', 'case_id', 'seed', 'total_mw', 'dynamic_mw', 'leakage_mw', 'energy_j', 'begin_ns',
                    'end_ns', 'window_seconds', 'frequency_hz', 'voltage_v', 'temperature_c', 'annotation_percent', 'unannotated_pins',
                    'unannotated_percent', 'activity_sha256', 'window']


def power_csv_rows(physical):
    """One row per seed and a 'mean' row per implementation/operator: window, workload, frequency, corner, coverage."""
    out = []
    for impl, value in physical.items():
        power = value.get('power') or {}
        corner = power.get('corner') or {}
        freq = power.get('frequency_hz') or value.get('frequency_hz')
        rows = []
        for r in power.get('records') or []:
            total_mw = r.get('total_mw') if r.get('total_mw') is not None else (r.get('power_w') or 0) * 1000
            unannotated = r.get('unannotated_percent', None if r.get('annotation_percent') is None else 100 - r['annotation_percent'])
            seconds = r.get('window_seconds')
            if seconds is None and isinstance(r.get('end_ns'), (int, float)) and isinstance(r.get('begin_ns'), (int, float)):
                seconds = (r['end_ns'] - r['begin_ns']) * 1e-9
            rows.append([impl, r.get('operator'), r.get('case_id'), r.get('seed'), total_mw, r.get('dynamic_mw'), r.get('leakage_mw'),
                         r.get('energy_j'), r.get('begin_ns'), r.get('end_ns'), seconds, r.get('frequency_hz') or freq,
                         corner.get('voltage_v'), corner.get('temperature_c'), r.get('annotation_percent'), r.get('unannotated_pins'),
                         unannotated, r.get('activity_sha256'), power.get('window')])
        out += rows
        for op in sorted({row[1] for row in rows}, key=str):
            group = [row for row in rows if row[1] == op]
            mean = lambda i: (sum(row[i] for row in group) / len(group)) if all(isinstance(row[i], (int, float)) for row in group) else None
            out.append([impl, op, group[0][2], f'mean of {len(group)}', mean(4), mean(5), mean(6), mean(7), None, None, mean(10),
                        group[0][11], group[0][12], group[0][13], mean(14), mean(15), mean(16), None, power.get('window')])
    return out


def write_csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


LAYER_NOTE = ('Four-layer candidate structure retained (task.md section 1); promotion is not run in student-mini-v1: '
              'no candidate executed, no performance improvement claimed, no PROMOTE.')


def candidates(spec, platforms):
    """Per baseline: the spec's four candidate layers, each NOT_RUN with the baseline as parent."""
    return dict(description=LAYER_NOTE, layers=spec.get('layers'), promote=False,
                candidates=[dict(platform=p, operator=op, layer=layer, status='NOT_RUN', promote=False,
                                 parent=f'baseline:{p}/{op}', parent_implementation=p if p != 'accelerator' else f'accelerator-{op}')
                            for p in platforms for op in OPERATORS for layer in spec.get('layers') or []])


def guard_outcome(record_path):
    """Last status/reason JSON line the guarded child printed (sibling .log of the guard record), if any."""
    log = Path(record_path).with_suffix('.log')
    if not log.is_file():
        return None
    for line in reversed(log.read_text(encoding='utf-8', errors='replace').splitlines()):
        line = line.strip()
        if line.startswith('{') and ('"reason"' in line or '"status"' in line):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            return {k: value.get(k) for k in ('status', 'reason') if value.get(k) is not None}
    return None


def disclosures(plan, platforms, physical, resources, gates, verified=None):
    """Derived HOLD / disclosure items: guarded runs whose record is not PASS, re-audited physical runs,
    accelerator records that are HOLD in the raw results until the component-RTL witness is attached."""
    items = []
    by_name = {Path(p).name: p for p in plan.get('resources', [])}
    for r in resources:
        if r['status'] != 'PASS':
            outcome = guard_outcome(by_name.get(r['record'], r['record'])) or {}
            events = r.get('memory_events') or {}
            peak, limit = r.get('memory_peak_bytes'), r.get('memory_limit_bytes')
            items.append(dict(kind='resource-record-hold', item=r['record'], status=r['status'],
                              text=f"guard record {r['record']}: status {r['status']}, exit code {r['exit_code']}, peak memory {peak} of "
                                   f"limit {limit} bytes{' (reached the cap)' if peak is not None and peak == limit else ''}, "
                                   f"memory.events max {events.get('max')}, oom {events.get('oom')}, oom_kill {events.get('oom_kill')}; "
                                   f"child outcome: {outcome.get('status')}: {str(outcome.get('reason'))[:300]}; "
                                   'the resource-limits gate requires every listed record to be PASS, so it stays NOT MET'))
    for name in [p for p in ('cpu', 'gpu') if p in platforms]:
        entry = plan.get(name) or {}
        if isinstance(entry.get('physical'), str):
            route = load(entry['physical'])
            if route.get('reaudit_of'):
                origin = Path(route['reaudit_of']) / 'completion.json'
                original = load(origin) if origin.is_file() else {}
                items.append(dict(kind='physical-reaudit', item=f'{name}/top', status=route.get('status'),
                                  text=f"{name} physical sign-off is the --reaudit run {Path(entry['physical']).parent.name} "
                                       f"({route.get('status')}): audit and sign-off rerun on the unchanged results of "
                                       f"{Path(route['reaudit_of']).name} (all non-audit inputs SHA-identical). The original run's "
                                       f"own status is {original.get('status')}: {str(original.get('reason'))[:400]}"))
        elif isinstance(entry.get('physical'), dict):
            # hierarchical GPU: blocks continued with --eco-from rewrote their predecessor's ORFS result directory
            for path in entry['physical'].get('blocks') or []:
                block = load(path)
                if not block.get('eco_from'):
                    continue
                origin = Path(block['eco_from']) / 'completion.json'
                original = load(origin) if origin.is_file() else {}
                mine = block.get('artifacts') or {}
                rewritten = sorted(Path(k).name for k, v in (original.get('artifacts') or {}).items()
                                   if Path(k).name.startswith('6_final.') and k in mine and mine[k] != v)
                design = Path(block.get('result_directory') or '').parent.name
                items.append(dict(kind='physical-eco-from', item=f'{name}/{design}', status=block.get('status'),
                                  text=f"{name} block {design} is the --eco-from run {Path(path).parent.name[:8]} ({block.get('status')}"
                                       f"{', chip-timing context ' + Path(block['eco_context']).name if block.get('eco_context') else ''}): "
                                       f"post-route ECO continued on the routed result of {Path(block['eco_from']).name[:8]} "
                                       f"({original.get('status')}) in the same ORFS result directory "
                                       f"{Path(block.get('result_directory') or '').name}; the predecessor's completion and inputs are packaged "
                                       f"under eco-from/. Files the predecessor's completion binds that the ECO run rewrote: "
                                       f"{', '.join(rewritten) or 'none'} (the predecessor's recorded SHA-256 no longer matches them)."))
    if 'accelerator' in platforms:
        witness = (plan.get('accelerator') or {}).get('witness')
        attached = {(r['case']['id'], r['seed']) for r in (verified or {}).get('accelerator', {}).get('records', []) if r.get('witness_attached')}
        final = {(r['case']['id'], r['seed']): r['status'] for r in (verified or {}).get('accelerator', {}).get('records', [])}
        for op in OPERATORS:
            raw = load(plan['accelerator'][op]['results'])
            groups = {}
            for r in raw.get('records', []):
                if r.get('status') != 'HOLD':
                    continue
                key = (r['case']['id'], r['seed'])
                missing = tuple((r.get('observation') or {}).get('missing_witnesses') or ())
                groups.setdefault((missing, key in attached), []).append(key)
            for (missing, with_witness), keys in sorted(groups.items()):
                cases = sorted({k[0] for k in keys})
                statuses = sorted({final.get(k, 'absent') for k in keys})
                how = (f'the assembler attached the component-RTL primitive witness ({witness}) and re-verified each record against golden'
                       if with_witness else
                       'no witness is attached by the assembler; the release status comes from re-verifying the record against golden and '
                       "attesting the golden's expected events from the raw testbench rows (the producer's extra witness requirement is not "
                       'one of the frozen expected events)')
                items.append(dict(kind='accelerator-raw-hold', item=f'accelerator {op}', status=f"HOLD in raw results -> {'/'.join(statuses)}",
                                  text=f"{len(keys)} records ({', '.join(cases)}) are HOLD in the raw results "
                                       f"{Path(plan['accelerator'][op]['results']).parent.name[:16]}… with missing_witnesses {list(missing)}; {how}"))
    for text in plan.get('disclosures') or []:
        items.append(dict(kind='note', item='plan', status='', text=text))
    if not gates.get('one-hour'):
        items.append(dict(kind='one-hour', item='one-hour target', status='NOT ACHIEVED',
                          text='The one-hour complete-delivery target (task.md sections 1, 5, 6) is not achieved; see one_hour'))
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--no-zip', action='store_true')
    args = parser.parse_args()
    plan = load(args.plan)
    course = plan.get('course')
    platforms = tuple(course['platforms']) if course else PLATFORMS
    implementations = tuple(course['implementations']) if course else ('cpu', 'gpu', *(f'accelerator-{op}' for op in OPERATORS))
    package_name = course['package_name'] if course else 'student-mini-v1'
    out = args.out.resolve()
    if out.exists():
        raise ValueError(f'{out} exists; releases are never overwritten')
    package = out / package_name
    data = package / 'data'
    for sub in ('records', 'arrays', 'summary', 'golden', 'nano', 'resources'):
        (data / sub).mkdir(parents=True)
    vectors_path = Path(plan['vectors'])
    vectors = load_vectors(vectors_path)
    gates = {}
    verified = {}
    for platform in platforms:
        files = plan[platform]['results'] if platform != 'accelerator' else [plan['accelerator'][op]['results'] for op in OPERATORS]
        files = files if isinstance(files, list) else [files]
        verified[platform] = apply_records(platform, verify_platform(platform, files, vectors), vectors, plan, gates)
    physical = physical_summary(plan, gates, platforms)
    nano = nano_summary(plan, gates, platforms)
    resources = resources_summary(plan, gates)
    # ---- data files
    shutil.copyfile(vectors_path, data / 'golden/vectors.jsonl')
    if plan.get('golden_manifest'):
        shutil.copyfile(plan['golden_manifest'], data / 'golden/manifest.json')
    import numpy as np
    for platform, value in verified.items():
        with (data / 'records' / f'{platform}.jsonl').open('w', encoding='utf-8') as stream:
            for row in value['records']:
                stream.write(json.dumps(dict(platform=platform, ordinal=row['ordinal'], case=row['case'], seed=row['seed'], prng=row['prng'],
                                             input_sha256=hashlib.sha256(json.dumps(row['inputs'], sort_keys=True).encode()).hexdigest(),
                                             golden=row['golden'], observation=row['observation'], main_execution=row.get('main_execution'),
                                             comparison=row['comparison'], events=row['events'], status=row['status']),
                                        ensure_ascii=False, allow_nan=False) + '\n')
        width = max(len(r['comparison'].get('golden_bits') or []) for r in value['records'])
        n = len(value['records'])
        golden_bits = np.zeros((n, width), np.uint16)
        actual_bits = np.zeros((n, width), np.uint16)
        delta = np.full((n, width), np.nan, np.float64)
        lengths = np.zeros(n, np.int32)
        for i, row in enumerate(value['records']):
            c = row['comparison']
            g = c.get('golden_bits') or []
            lengths[i] = len(g)
            golden_bits[i, :len(g)] = g
            a = c.get('actual_bits') or []
            actual_bits[i, :len(a)] = a[:width]
            if c.get('delta'):
                delta[i, :len(c['delta'])] = c['delta']
        np.savez_compressed(data / 'arrays' / f'{platform}.npz', ordinal=np.array([r['ordinal'] for r in value['records']], np.int32),
                            seed=np.array([r['seed'] for r in value['records']], np.int32), length=lengths,
                            golden_bits=golden_bits, actual_bits=actual_bits, signed_delta=delta)
    write_csv(data / 'summary/cases.csv',
              ['platform', 'case_id', 'operator', 'scenario', 'expected_status', 'status', 'failed_seeds', 'held_seeds', 'missing_events',
               'max_absolute_delta', 'mean_absolute_error', 'rmse', 'bit_mismatch_count', 'cycles_mean', 'instructions_mean',
               'dma_bytes_mean', 'cache_bytes_mean'],
              [[p, c['case_id'], c['operator'], c['scenario'], c['expected_status'], c['status'], ' '.join(map(str, c['failed_seeds'])),
                ' '.join(map(str, c['held_seeds'])), ' '.join(c['missing_events']), c.get('max_absolute_delta'), c.get('mean_absolute_error'),
                c.get('rmse'), c.get('bit_mismatch_count'), c['counters']['cycles']['mean'], c['counters']['instructions']['mean'],
                c['counters']['dma_bytes']['mean'], c['counters']['cache_bytes']['mean']]
               for p, v in verified.items() for c in v['cases']])
    baselines = []
    for platform in platforms:
        for op in OPERATORS:
            rows = [r for r in verified[platform]['records'] if r['case']['operator'] == op]
            cases = [c for c in verified[platform]['cases'] if c['operator'] == op]
            impl = platform if platform != 'accelerator' else f'accelerator-{op}'
            power_rows = [r for r in (physical[impl]['power'] or {}).get('records', []) if r.get('operator') in (op, None)] if physical.get(impl) else []
            mean_mw = (sum((r.get('total_mw') if r.get('total_mw') is not None else (r.get('power_w') or 0) * 1000) for r in power_rows) / len(power_rows)) if power_rows else None
            cycles = [r['observation'].get('cycles') for r in rows if isinstance(r['observation'].get('cycles'), (int, float))]
            status = 'PASS' if all(r['status'] == 'PASS' for r in rows) and gates.get(f'{impl}-physical') and gates.get(f'{impl}-power') else \
                     'FAIL' if any(r['status'] == 'FAIL' for r in rows) else 'HOLD'
            baselines.append(dict(platform=platform, operator=op, status=status, records=len(rows), passed=sum(r['status'] == 'PASS' for r in rows),
                                  held=sum(r['status'] == 'HOLD' for r in rows), failed=sum(r['status'] == 'FAIL' for r in rows),
                                  cases=len(cases), cases_passed=sum(c['status'] == 'PASS' for c in cases),
                                  mean_cycles=round(sum(cycles) / len(cycles), 1) if cycles else None,
                                  physical=impl if gates.get(f'{impl}-physical') else f'{impl} (incomplete)',
                                  power=f'{mean_mw:.3f} mW' if mean_mw is not None else 'missing', power_seeds=len(power_rows)))
    baseline_gate = 'nine-baselines' if not course else f"{course['id']}-{len(baselines)}-baselines"
    gates[baseline_gate] = all(b['status'] == 'PASS' for b in baselines)
    write_csv(data / 'summary/baselines.csv', list(baselines[0]), [list(b.values()) for b in baselines])
    write_csv(data / 'summary/power_per_seed.csv', POWER_CSV_HEADER, power_csv_rows(physical))
    (data / 'summary/physical.json').write_text(json.dumps(physical, indent=2) + '\n')
    (data / 'nano/sessions.json').write_text(json.dumps(nano, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (data / 'resources/resources.json').write_text(json.dumps(resources, indent=2) + '\n')
    for path in plan.get('resources', []):
        shutil.copyfile(path, data / 'resources' / Path(path).name)
    measurements = None
    if plan.get('resource_measurements'):
        measurements = load(plan['resource_measurements'])
        shutil.copyfile(plan['resource_measurements'], data / 'resources' / 'resource-measurements.json')
    model_card = None
    if plan.get('nano_model_card'):
        model_card = load(plan['nano_model_card'])
        shutil.copyfile(plan['nano_model_card'], data / 'nano' / 'model-card.json')
    candidate_layers = None
    if course:
        candidate_layers = candidates(load(plan['spec']), platforms)
        (data / 'candidates.json').write_text(json.dumps(candidate_layers, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    # ---- physical and power evidence (DEF/netlist/SPEF/logs compressed, no ODB), indexed with source SHA-256
    evidence = package_evidence(plan, package)
    evidence_missing = evidence_gate(evidence, gates, implementations)
    (package / 'evidence-index.json').write_text(json.dumps(dict(
        description='Physical and power evidence files: packaged SHA-256, SHA-256 of the source bytes before compression, '
                    'aliases for identical content packaged once. Checked by verify_release.py.',
        missing=evidence_missing + list(plan.get('physical_files_missing') or []),
        omitted=list(plan.get('physical_files_omitted') or []), files=evidence), indent=2) + '\n')
    # ---- sources (whitelist from the plan) and SPEC
    for rel in plan.get('sources', []):
        source = ROOT / rel
        target = package / 'sources' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    spec = load(plan['spec'])
    spec['protocol_interfaces'] = plan.get('protocol_interfaces')
    spec['power_method'] = plan.get('power_method')
    spec['tools'] = plan.get('tools')
    for key in ('host', 'memory_layout'):
        if plan.get(key):
            spec[key] = load(plan[key]) if key == 'memory_layout' else plan[key]
    if course:
        spec['course'] = dict(course, spec_route_definition=(spec.get('routes') or {}).get(course['spec_route']))
    (package / 'SPEC.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    started = datetime.fromisoformat(spec['implementation_started_at'])
    now = datetime.now(timezone.utc)
    elapsed = (now - started).total_seconds()
    gates['one-hour'] = elapsed <= spec['deadline_seconds']
    complete = all(v for k, v in gates.items() if k != 'one-hour')
    disclosed = disclosures(plan, platforms, physical, resources, gates, verified) if course else None
    summary = dict(release_id=package_name, generated_at=now.isoformat(), status='COMPLETE' if complete else 'PARTIAL_NOT_RELEASED',
                   one_hour=dict(started=spec['implementation_started_at'], elapsed_seconds=elapsed, achieved=gates['one-hour']),
                   gates=gates, baselines=baselines,
                   omitted_evidence=dict(files=len(plan.get('physical_files_omitted') or []),
                                         bytes=sum(o['bytes'] for o in plan.get('physical_files_omitted') or []),
                                         reasons=sorted({o['reason'] for o in plan.get('physical_files_omitted') or []}),
                                         listed_in='evidence-index.json: omitted'),
                   tiles=[dict(label='发布状态', value='COMPLETE' if complete else 'PARTIAL', cls='PASS' if complete else 'HOLD'),
                          dict(label='一小时目标', value='达成' if gates['one-hour'] else f'未达成 ({elapsed / 3600:.1f} h)', cls='PASS' if gates['one-hour'] else 'FAIL'),
                          *[dict(label=f'{p} 记录 PASS', value=f"{verified[p]['counts']['PASS']}/1000",
                                 cls='PASS' if verified[p]['counts']['PASS'] == 1000 else 'HOLD') for p in platforms],
                          dict(label='通过的 baseline', value=f"{sum(b['status'] == 'PASS' for b in baselines)}/{len(baselines)}",
                               cls='PASS' if gates[baseline_gate] else 'HOLD')],
                   sections=[dict(title='发布门', rows=[['门', '结果']] + [[k, 'PASS' if v else 'NOT MET'] for k, v in gates.items()]),
                             dict(title='物理实现与功耗', rows=[['实现', 'route', '频率 MHz', 'WNS ns', 'hold WNS ns', 'DRC', 'antenna', '功耗状态', 'seed 数']] +
                                  [[k, (v['route'] or {}).get('status', 'missing'), (v.get('frequency_hz') or 0) / 1e6,
                                    ((v['route'] or {}).get('metrics') or {}).get('wns_ns'), ((v['route'] or {}).get('metrics') or {}).get('hold_wns_ns'),
                                    ((v['route'] or {}).get('metrics') or {}).get('drc'), ((v['route'] or {}).get('metrics') or {}).get('antenna_nets'),
                                    (v['power'] or {}).get('status', 'missing'), len((v['power'] or {}).get('records') or [])] for k, v in physical.items()]),
                             *([] if 'gpu' not in platforms else [dict(title='GPU 分块物理实现 (block + top 的 DRC/antenna；时序以全芯片 STA 为准)',
                                  rows=[['组件', '角色', '状态', 'DRC', 'antenna nets', 'budget setup ns', 'budget hold ns']] +
                                  [[c.get('design'), c.get('role'), c.get('status'), c.get('drc'), c.get('antenna_nets'),
                                    c.get('budget_setup_ws_ns'), c.get('budget_hold_ws_ns')]
                                   for c in ((physical.get('gpu') or {}).get('route') or {}).get('components') or []])]),
                             dict(title='逐 seed 功耗 (mW)', rows=[['实现', '算子', 'case', 'seed', '总功耗', '动态', '漏电', '能量 J', '窗口 ns', '标注率 %']] +
                                  [[impl, r.get('operator'), r.get('case_id'), r.get('seed'),
                                    round(r['total_mw'] if r.get('total_mw') is not None else (r.get('power_w') or 0) * 1000, 3),
                                    round(r.get('dynamic_mw') or 0, 3), round(r.get('leakage_mw') or 0, 6), r.get('energy_j'),
                                    (r.get('end_ns') or 0) - (r.get('begin_ns') or 0), round(r.get('annotation_percent') or 0, 3)]
                                   for impl, v in physical.items() for r in ((v.get('power') or {}).get('records') or [])]),
                             dict(title='NanoChat 会话 (12 个冻结测试问题，逐 token 与 PTQ 参考一致)', rows=[['平台', '问题', '领域', '状态', 'token 数', '后端']] +
                                  [[p, r['question'], r.get('domain'), r['status'], len(r.get('tokens') or []), r.get('backend')]
                                   for p, v in nano.items() for r in v['sessions']]),
                             dict(title='受限资源运行 (2 vCPU / 8 GiB)', rows=[['记录', '状态', '峰值内存 MiB', '耗时 s', '退出码']] +
                                  [[r['record'], r['status'], round((r['memory_peak_bytes'] or 0) / 2**20), round(r['elapsed_seconds'] or 0), r['exit_code']]
                                   for r in resources]),
                             dict(title='未打包的证据文件 (SHA-256 仍记录在 evidence-index.json 与 profile.json 中)',
                                  rows=[['文件', '字节', 'SHA-256', '原因']] +
                                  [[o['path'], o['bytes'], o.get('sha256'), o['reason']] for o in plan.get('physical_files_omitted') or []]),
                             dict(title='边界说明', text=plan.get('boundary_note', ''))])
    if course:
        summary['course'] = dict(id=course['id'], name=course['name'], spec_route=course['spec_route'], platforms=list(platforms),
                                 implementations=list(implementations), implementation_components=course.get('implementation_components'),
                                 baselines=len(baselines), excluded_platforms=course.get('excluded_platforms'))
        summary['disclosures'] = disclosed
        summary['candidates'] = dict(file='data/candidates.json', count=len(candidate_layers['candidates']), status='NOT_RUN', promote=False)
        if measurements is not None:
            summary['resource_measurements'] = dict(file='data/resources/resource-measurements.json', content=measurements)
        if model_card is not None:
            summary['nano_model_card'] = dict(file='data/nano/model-card.json', status=model_card.get('status'),
                                              holds=model_card.get('holds'), mismatches=model_card.get('mismatches'))
        rom = (physical.get('cpu') or {}).get('route') or {}
        summary['title'] = f"{package_name} {course['name']} 课程最小 baseline 报告"
        summary['baseline_heading'] = f"{len(baselines)} 个 baseline（{course['name']}）"
        summary['sections'][0:0] = [
            dict(title=f"课程：{course['name']}（spec route {course['spec_route']}）",
                 rows=[['项目', '内容']] + [['包含的平台', ', '.join(platforms)], ['物理实现', ', '.join(implementations)]]
                      + [[f'实现 {k}', v] for k, v in (course.get('implementation_components') or {}).items()]
                      + [[f'不包含：{k}', v] for k, v in (course.get('excluded_platforms') or {}).items()]),
            dict(title='HOLD 与披露事项', rows=[['类别', '对象', '状态', '说明']] + [[d['kind'], d['item'], d['status'], d['text']] for d in disclosed])]
        summary['sections'] += [
            dict(title='CPU ROM bank 硬化分块 (25 个，逐块验收)', rows=[['bank', '状态', 'DRC', 'antenna nets', 'WNS ns', 'hold WNS ns']] +
                 [[r.get('bank'), r.get('status'), r.get('drc'), r.get('antenna_nets'), r.get('wns_ns'), r.get('hold_wns_ns')]
                  for r in rom.get('rom_banks') or []]),
            *([] if 'gpu' not in platforms else [dict(
                title='GPU 全芯片 STA 与分区 (层次化实现的时序签核)',
                rows=[['项目', '值']] + [[k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v] for k, v in
                                         list((((physical.get('gpu') or {}).get('route') or {}).get('fullchip_sta') or {}).items())
                                         + [(f'partition {k}', v) for k, v in
                                            ((((physical.get('gpu') or {}).get('route') or {}).get('partition') or {}).items())]
                                         + [('route reasons', ((physical.get('gpu') or {}).get('route') or {}).get('reasons'))]])]),
            dict(title='四层候选结构 (只保留结构，NOT_RUN，无 PROMOTE)', text=LAYER_NOTE,
                 rows=[['平台', '算子', '层', '状态', '父 baseline']] +
                      [[c['platform'], c['operator'], c['layer'], c['status'], c['parent']] for c in candidate_layers['candidates']])]
        if measurements is not None:
            summary['sections'].append(dict(title='软件依赖与临时磁盘实测 (data/resources/resource-measurements.json)',
                                            text=json.dumps(measurements, ensure_ascii=False)[:20000]))
        if model_card is not None:
            summary['sections'].append(dict(title='NanoChat 模型卡 (data/nano/model-card.json)',
                                            text=json.dumps(model_card, ensure_ascii=False)[:20000]))
        if plan.get('tools') or plan.get('host'):
            summary['sections'].append(dict(title='工具版本与主机配置 (SPEC.json tools / host)',
                                            rows=[['项目', '值']] + [[k, json.dumps(v, ensure_ascii=False)] for k, v in (plan.get('host') or {}).items()]
                                                 + [[t['path'], ' '.join((t.get('version') or {}).get('output') or [])[:300]
                                                     + ('' if t.get('current_matches_recorded') else ' [current binary differs from the recorded SHA-256]')]
                                                    for t in (plan.get('tools') or {}).get('binaries', [])]))
    report_platforms = {p: dict(records=[dict(r, status=r['status'], comparison=dict(r['comparison'], status=r['status'])) for r in v['records']],
                                cases=v['cases']) for p, v in verified.items()}
    (package / 'report.html').write_text(render(summary, report_platforms, package_dir=package), encoding='utf-8')
    (package / 'release.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if plan.get('readme'):
        shutil.copyfile(plan['readme'], package / 'README.md')
    if plan.get('verifier'):
        shutil.copyfile(plan['verifier'], package / 'verify_release.py')
    # ---- size limit on the expanded package (enforced before the manifest seals release.json)
    expanded = sum(p.stat().st_size for p in package.rglob('*') if p.is_file())
    if expanded > EXPANDED_MAX_BYTES:
        gates['expanded-size'] = False
        summary.update(status=REJECTED, gates=gates)
        summary['tiles'][0] = dict(label='发布状态', value='REJECTED (size)', cls='FAIL')
        (package / 'report.html').write_text(render(summary, report_platforms, package_dir=package), encoding='utf-8')
        (package / 'release.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    # ---- manifest
    files = sorted(p for p in package.rglob('*') if p.is_file())
    manifest = '\n'.join(f'{stream_sha(p)}  {p.relative_to(package).as_posix()}' for p in files) + '\n'
    (package / 'MANIFEST.sha256').write_text(manifest)
    expanded = sum(p.stat().st_size for p in package.rglob('*') if p.is_file())
    failures = []
    if expanded > EXPANDED_MAX_BYTES:
        failures.append(f'expanded package {expanded} bytes > {EXPANDED_MAX_BYTES}')
    result = dict(status=summary['status'], release_status=summary['status'], gates=gates, expanded_bytes=expanded, files=len(files) + 1,
                  evidence_files=sum(not r.get('alias_of') for r in evidence), evidence_aliases=sum(bool(r.get('alias_of')) for r in evidence),
                  evidence_missing=evidence_missing, evidence_omitted=len(plan.get('physical_files_omitted') or []))
    if args.no_zip:
        check = verify_tree(package, failures)
        result['package_verifier'] = check
    elif not failures:
        archive = out / f'{package_name}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as z:
            for p in sorted(package.rglob('*')):
                if p.is_file():
                    # already-compressed members are stored; DEFLATE would only cost time
                    z.write(p, p.relative_to(out).as_posix(),
                            compress_type=zipfile.ZIP_STORED if p.suffix in ('.gz', '.npz', '.zip') else zipfile.ZIP_DEFLATED)
        result['zip_bytes'] = archive.stat().st_size
        result['zip_sha256'] = stream_sha(archive)
        if result['zip_bytes'] > ZIP_MAX_BYTES:
            failures.append(f"zip {result['zip_bytes']} bytes > {ZIP_MAX_BYTES}")
        with tempfile.TemporaryDirectory() as clean:
            with zipfile.ZipFile(archive) as z:
                z.extractall(clean)
            root = Path(clean) / package_name
            bad = [line for line in (root / 'MANIFEST.sha256').read_text().splitlines()
                   if not (root / line.split('  ', 1)[1]).is_file() or stream_sha(root / line.split('  ', 1)[1]) != line.split('  ', 1)[0]]
            result['clean_unzip_bytes'] = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            result['clean_unzip_manifest_ok'] = not bad
            if bad:
                failures.append(f'clean unzip: {len(bad)} manifest mismatches, e.g. {bad[:3]}')
            if result['clean_unzip_bytes'] > EXPANDED_MAX_BYTES:
                failures.append(f"clean unzip {result['clean_unzip_bytes']} bytes > {EXPANDED_MAX_BYTES}")
            result['clean_unzip_verifier'] = verify_tree(root, failures)
        result['size_targets'] = dict(zip_max_bytes=ZIP_MAX_BYTES, expanded_max_bytes=EXPANDED_MAX_BYTES,
                                      zip_ok=result['zip_bytes'] <= ZIP_MAX_BYTES, expanded_ok=result['clean_unzip_bytes'] <= EXPANDED_MAX_BYTES)
        if failures:
            rejected = out / f'{package_name}.REJECTED.zip'
            archive.rename(rejected)
            result['zip_path'] = str(rejected)
        else:
            result['zip_path'] = str(archive)
    if args.no_zip:
        result['size_targets'] = dict(expanded_max_bytes=EXPANDED_MAX_BYTES, expanded_ok=expanded <= EXPANDED_MAX_BYTES)
    if failures:
        result['status'] = REJECTED
    result['packaging_failures'] = failures
    (out / 'package-report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('gates',)}))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
