"""Process-graph framework for the offline student-mini release report.

A course describes how its package was produced in a declarative graph file
(integration/student-mini/release/process-graph-<course>.json): modules (columns),
lanes (shared / per platform), nodes and chips with template KPIs bound to package
data, typed edges (data, gate, loop, shared, hold) and iteration counts bound to
evidence.  This module

  * loads and validates the graph (``validate``),
  * resolves every binding against the package being assembled, the resource-guard
    records (grading/evidence/student-mini-v1/environment) and run directories in
    the repository (``Bundle``),
  * lays the panorama out on a fixed 1440x810 canvas and emits it as one SVG
    (``panorama_svg``), and
  * returns the JSON bundle the report's JavaScript uses to render detail views.

Binding grammar (``src``):  ``root:path#op#op``
  roots   summary spec physical golden resources candidates model_card measure nano evidence
          pkg:<file in package>|<path>   repo:<file in repo>|<path>   guard:<record name>|<path>
          calc:<function>[:args]
  path    dot separated keys / list indices ("" = whole object)
  ops     len  min:key  max:key  sum:key  mean:key  count:key=value      (aggregate a list)
          ns f1 f2 int dur bytes gib short pct                           (format)
Nothing is invented: an unresolvable binding renders as "—" and is listed by --check.
"""
from __future__ import annotations

import fnmatch
import glob
import hashlib
import html
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH_DIR = ROOT / 'integration/student-mini/release'
ENV_DIR = ROOT / 'grading/evidence/student-mini-v1/environment'
NOTES_PATH = ROOT / 'build/student-mini/explore/NOTES.md'

W, H = 1440, 810
DIAG_TOP, MOD_HEAD, DIAG_BOTTOM = 62, 40, 506
BUS_GAP = 10  # horizontal channel under the module headers for edges between non-adjacent modules
BUS_TRACK = {'gate': 2.0, 'shared': 4.5, 'hold': 7.0, 'data': 7.0, 'loop': 9.5}
LEGEND_Y, PANEL_TOP, PANEL_BOTTOM = 512, 532, 804
GAP = 6
EDGE_TYPES = ('data', 'gate', 'loop', 'shared', 'hold')
EDGE_LABELS = {'data': '数据依赖', 'gate': '验收门检查', 'loop': '迭代 / 回环（×次数）', 'shared': '共享产物 / 工具',
               'hold': '阻塞 HOLD / NOT MET'}


# ----------------------------------------------------------------------------- graph file

def graph_path(course_id):
    """Graph file of a course; the three-platform release uses process-graph-three-platform.json."""
    return GRAPH_DIR / f'process-graph-{course_id or "three-platform"}.json'


def load_graph(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def iter_nodes(graph):
    """(node, parent_id, module_id) for every module child and chip, depth first."""
    for module in graph['modules']:
        for child in module.get('children', []):
            yield child, module['id'], module['id']
            for chip in child.get('chips', []):
                yield chip, child['id'], module['id']


def validate(graph):
    """Structural errors of a graph description (empty list = valid)."""
    errors = []
    ids = [m['id'] for m in graph.get('modules', [])]
    for node, _, _ in iter_nodes(graph):
        if 'id' not in node or 'title' not in node:
            errors.append(f'node without id/title: {node}')
            continue
        ids.append(node['id'])
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f'duplicate id {i}')
    known = set(ids)
    lanes = {lane['id'] for lane in graph.get('lanes', [])}
    for module in graph.get('modules', []):
        if module.get('layout') not in ('stack', 'lanes'):
            errors.append(f"module {module['id']}: layout must be stack or lanes")
        for child in module.get('children', []):
            if module.get('layout') == 'lanes' and child.get('lane') not in lanes:
                errors.append(f"{child['id']}: lane {child.get('lane')} not in {sorted(lanes)}")
    for edge in graph.get('edges', []):
        if edge.get('type') not in EDGE_TYPES:
            errors.append(f'edge {edge}: type must be one of {EDGE_TYPES}')
        for end in ('from', 'to'):
            if edge.get(end) not in known:
                errors.append(f'edge {edge.get("from")} -> {edge.get("to")}: unknown {end} {edge.get(end)}')
    for sink in graph.get('time_sinks', []):
        if sink.get('node') not in known:
            errors.append(f"time sink {sink.get('label')}: unknown node {sink.get('node')}")
    for cause in graph.get('root_causes', []):
        if cause.get('node') not in known:
            errors.append(f"root cause: unknown node {cause.get('node')}")
    return errors


# ----------------------------------------------------------------------------- evidence stores

def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def log_outcome(log):
    """Last status/reason JSON line of a guarded child's log, else its last non-empty line."""
    if not log.is_file():
        return None
    lines = [l.strip() for l in log.read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
    found = []
    for line in lines:
        if line.startswith('{') and ('"reason"' in line or '"status"' in line):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                found.append(value)
    # prefer the last line with a reason, then the last non-progress status (RUNNING/BUILDING lines are heartbeats)
    final = next((v for v in reversed(found) if v.get('reason')), None) or         next((v for v in reversed(found) if str(v.get('status', '')).upper() not in ('RUNNING', 'BUILDING', 'WAITING_FOR_SERIAL_QUEUE', 'STARTED')), None)
    if final:
        return {k: str(final.get(k))[:600] for k in ('status', 'reason', 'stage') if final.get(k) is not None}
    if found:
        return None
    return {'reason': lines[-1][:600]} if lines else None


class GuardStore:
    """All resource-guard records (and logs whose guarded run left no record)."""

    def __init__(self, env_dir=ENV_DIR, package_dir=None):
        self.env_dir = Path(env_dir)
        self.package_dir = Path(package_dir) if package_dir else None
        self.entries = {}
        self.raw = {}
        if not self.env_dir.is_dir():
            return
        for path in sorted(self.env_dir.rglob('*.json')):
            name = path.relative_to(self.env_dir).as_posix()
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except ValueError:
                continue
            if not isinstance(value, dict) or 'command' not in value:
                continue
            self.raw[name] = value
            self.entries[name] = self._entry(name, path, value)
        for path in sorted(self.env_dir.rglob('*.log')):
            name = path.relative_to(self.env_dir).as_posix()
            if name[:-4] + '.json' in self.entries:
                continue
            outcome = log_outcome(path) or {}
            self.entries[name] = dict(name=name, kind='log', status=outcome.get('status') or 'NO_RECORD', created_at=None, start=None,
                                      elapsed=None, peak=None, limit=None, exit_code=None, mem=None, script=None, command=None,
                                      outcome=outcome, sha256=file_sha(path), bytes=path.stat().st_size, in_package=False,
                                      log_mtime=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='seconds'))

    def _entry(self, name, path, value):
        command = [str(c) for c in value.get('command') or []]
        script = next((Path(c).name for c in command if c.endswith(('.py', '.sh', '.tcl'))), Path(command[0]).name if command else None)
        events = {}
        for line in str(value.get('memory_events') or '').splitlines():
            key, _, count = line.partition(' ')
            if count.strip().isdigit():
                events[key] = int(count)
        start = parse_time(value.get('created_at'))
        in_package = bool(self.package_dir and (self.package_dir / 'data/resources' / Path(name).name).is_file())
        return dict(name=name, kind='record', status=value.get('status'), created_at=value.get('created_at'),
                    start=start.timestamp() if start else None, elapsed=value.get('elapsed_seconds'),
                    peak=value.get('memory_peak_bytes'), limit=value.get('memory_limit_bytes'), cpu_limit=value.get('cpu_limit'),
                    exit_code=value.get('exit_code'), mem={k: events.get(k) for k in ('max', 'oom', 'oom_kill')} if events else None,
                    script=script, command=' '.join(command)[:420], outcome=log_outcome(path.with_suffix('.log')),
                    sha256=file_sha(path), bytes=path.stat().st_size, in_package=in_package)

    def records(self):
        return [e for e in self.entries.values() if e['kind'] == 'record']

    def match(self, patterns):
        names = [n for n in self.entries if any(fnmatch.fnmatchcase(n, p) for p in patterns or [])]
        return sorted(names, key=lambda n: (self.entries[n]['start'] or float('inf'), n))


class NotesStore:
    """Bullets of build/student-mini/explore/NOTES.md, found by search strings."""

    def __init__(self, path=NOTES_PATH):
        self.path = Path(path)
        self.bullets = []
        if not self.path.is_file():
            return
        current = None
        for number, line in enumerate(self.path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            if line.startswith('- '):
                current = [number, number, line[2:]]
                self.bullets.append(current)
            elif line.strip() and not line.startswith(('#', ' ')):
                current = [number, number, line.strip()]
                self.bullets.append(current)
            elif line.startswith('  ') and current is not None and line.strip():
                current[1] = number
                current[2] += ' ' + line.strip()
            else:
                current = None

    def find(self, needle):
        return [dict(lines=f'L{a}' if a == b else f'L{a}-L{b}', text=t) for a, b, t in self.bullets if needle in t][:3]


# ----------------------------------------------------------------------------- formatting

def fmt_duration(seconds):
    if not isinstance(seconds, (int, float)):
        return None
    if seconds < 90:
        return f'{seconds:.0f} s'
    if seconds < 5400:
        return f'{seconds / 60:.0f} min'
    return f'{seconds / 3600:.1f} h'


def fmt_bytes(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    for unit, size in (('GB', 1e9), ('MB', 1e6), ('kB', 1e3)):
        if value >= size:
            return f'{value / size:.1f} {unit}' if value / size < 100 else f'{value / size:.0f} {unit}'
    return f'{value:.0f} B'


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


FORMATS = {
    'ns': lambda v: None if number(v) is None else f'{number(v):+.3f}',
    'f1': lambda v: None if number(v) is None else f'{number(v):.1f}',
    'f2': lambda v: None if number(v) is None else f'{number(v):.2f}',
    'int': lambda v: None if number(v) is None else f'{int(round(number(v))):,}',
    'dur': fmt_duration,
    'bytes': fmt_bytes,
    'gib': lambda v: None if number(v) is None else f'{number(v) / 2**30:.2f} GiB',
    'short': lambda v: None if v is None else str(v)[:8] + '…',
    'pct': lambda v: None if number(v) is None else f'{number(v):.1f}%',
}


def aggregate(value, op):
    name, _, arg = op.partition(':')
    if name == 'len':
        return len(value) if isinstance(value, (list, dict, str)) else None
    if not isinstance(value, list):
        return None
    if name == 'count':
        key, _, want = arg.partition('=')
        return sum(1 for v in value if isinstance(v, dict) and str(v.get(key)) == want)
    numbers = [number(v.get(arg)) for v in value if isinstance(v, dict) and number(v.get(arg)) is not None]
    if not numbers:
        return None
    return {'min': min, 'max': max, 'sum': sum, 'mean': lambda x: sum(x) / len(x)}[name](numbers)


def walk(value, path):
    for key in [k for k in str(path).split('.') if k != ''] if path else []:
        if isinstance(value, list):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def display(value):
    if value is None:
        return '—'
    if isinstance(value, bool):
        return 'PASS' if value else 'NOT MET'
    if isinstance(value, int):
        return f'{value:,}' if abs(value) >= 10000 else str(value)
    if isinstance(value, float):
        return f'{value:.4g}'
    return str(value)


def template(text, values):
    """'{name}' / '{name:spec}' substitution; unresolved or unformattable values become '—'."""
    def sub(match):
        name, _, spec = match.group(1).partition(':')
        value = values.get(name)
        if value is None:
            return '—'
        if spec:
            try:
                return format(value, spec)
            except (ValueError, TypeError):
                return display(value)
        return display(value)
    return re.sub(r'\{([A-Za-z_][\w]*(?::[^}]*)?)\}', sub, text or '')


# ----------------------------------------------------------------------------- bundle (all resolved data)

class Bundle:
    def __init__(self, graph, summary, platforms, package_dir=None, env_dir=ENV_DIR, notes_path=NOTES_PATH, repo_root=ROOT):
        self.graph = graph
        self.summary = summary
        self.platforms = platforms
        self.package = Path(package_dir) if package_dir else None
        self.repo = Path(repo_root)
        self.guards = GuardStore(env_dir, self.package)
        self.notes = NotesStore(notes_path)
        self.cache = {}
        self._guard_cache = {}
        self.missing = []
        self.roots = dict(summary=summary, spec=self.pkg_json('SPEC.json'), physical=self.pkg_json('data/summary/physical.json'),
                          golden=self.pkg_json('data/golden/manifest.json'), resources=self.pkg_json('data/resources/resources.json'),
                          candidates=self.pkg_json('data/candidates.json'), model_card=self.pkg_json('data/nano/model-card.json'),
                          measure=self.pkg_json('data/resources/resource-measurements.json'), nano=self.pkg_json('data/nano/sessions.json'),
                          evidence=self.pkg_json('evidence-index.json'))
        self.nodes = {}
        self.parent = {}
        self.module_of = {}
        for module in graph['modules']:
            self.nodes[module['id']] = module
            self.module_of[module['id']] = module['id']
        for node, parent, module in iter_nodes(graph):
            self.nodes[node['id']] = node
            self.parent[node['id']] = parent
            self.module_of[node['id']] = module

    # -- json files
    def pkg_json(self, rel):
        return self.load_json(self.package / rel) if self.package else None

    def load_json(self, path):
        key = str(path)
        if key not in self.cache:
            try:
                self.cache[key] = json.loads(Path(path).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                self.cache[key] = None
        return self.cache[key]

    # -- binding resolution
    def get(self, src):
        if src is None:
            return None
        parts = str(src).split('#')
        head, ops = parts[0], parts[1:]
        root, _, rest = head.partition(':')
        if root == 'calc':
            value = self.calc(rest)
        elif root in ('pkg', 'repo', 'guard'):
            rel, _, path = rest.partition('|')
            if root == 'pkg':
                doc = self.pkg_json(rel)
            elif root == 'repo':
                doc = self.load_json(self.repo / rel)
            else:
                doc = self.guards.raw.get(rel)
            value = walk(doc, path)
        elif root in self.roots:
            value = walk(self.roots[root], rest)
        else:
            value = None
        for op in ops:
            if op.split(':')[0] in ('len', 'min', 'max', 'sum', 'mean', 'count'):
                value = aggregate(value, op)
            elif op in FORMATS:
                value = FORMATS[op](value) if value is not None else None
        if value is None:
            self.missing.append(src)
        return value

    def values(self, mapping):
        return {k: self.get(v) for k, v in (mapping or {}).items()}

    # -- guard bindings
    def guard_names(self, node_id):
        if node_id in self._guard_cache:
            return self._guard_cache[node_id]
        self._guard_cache[node_id] = names = self._guard_names(node_id)
        return names

    def _guard_names(self, node_id):
        node = self.nodes.get(node_id) or {}
        names = self.guards.match(node.get('guard'))
        names += [a['guard'] for a in node.get('attempts', []) if a.get('guard') in self.guards.entries and a['guard'] not in names]
        for chip in node.get('chips', []):
            names += [n for n in self.guard_names(chip['id']) if n not in names]
        for child in node.get('children', []):
            names += [n for n in self.guard_names(child['id']) if n not in names]
        return sorted(set(names), key=lambda n: (self.guards.entries[n]['start'] or float('inf'), n))

    def attempt_rows(self, node_id):
        rows = []
        for attempt in (self.nodes.get(node_id) or {}).get('attempts', []):
            entry = self.guards.entries.get(attempt.get('guard')) or {}
            work = self.repo / attempt['work'] if attempt.get('work') else None
            completion = self.load_json(work / 'completion.json') if work else None
            heartbeat = self.load_json(work / 'heartbeat.json') if work else None
            elapsed, basis = entry.get('elapsed'), 'guard record'
            if elapsed is None and heartbeat and isinstance(heartbeat.get('elapsed_seconds'), (int, float)):
                elapsed, basis = heartbeat['elapsed_seconds'], f"heartbeat.json（最后阶段 {heartbeat.get('stage')}，{heartbeat.get('updated_at')}）"
            rows.append(dict(label=attempt.get('label'), guard=attempt.get('guard'), guard_kind=entry.get('kind'),
                             status=entry.get('status') or (completion or {}).get('status') or 'NO_RECORD',
                             created_at=entry.get('created_at'), start=entry.get('start'), elapsed=elapsed, elapsed_basis=basis if elapsed else None,
                             peak=entry.get('peak'), exit_code=entry.get('exit_code'), mem=entry.get('mem'), outcome=entry.get('outcome'),
                             guard_sha256=entry.get('sha256'), work=attempt.get('work'),
                             completion_status=(completion or {}).get('status'), completion_reason=str((completion or {}).get('reason') or '')[:500] or None,
                             heartbeat=heartbeat, result=attempt.get('result'),
                             notes=[n for needle in attempt.get('notes', []) for n in self.notes.find(needle)]))
        return rows

    def calc(self, spec):
        name, _, arg = spec.partition(':')
        gates = self.summary.get('gates') or {}
        evidence = self.roots['evidence'] or {}
        if name == 'env_records_total':
            return len(self.guards.records())
        if name in ('guard_count', 'guard_pass', 'guard_hold', 'guard_seconds'):
            names = self.guard_names(arg)
            rows = [self.guards.entries[n] for n in names]
            if name == 'guard_count':
                return len(rows)
            if name == 'guard_pass':
                return sum(r['status'] == 'PASS' for r in rows)
            if name == 'guard_hold':
                return sum(r['status'] != 'PASS' for r in rows)
            return sum(r['elapsed'] or 0 for r in rows)
        if name == 'attempts':
            return len((self.nodes.get(arg) or {}).get('attempts', [])) or None
        if name == 'records_pass':
            return sum(r['status'] == 'PASS' for r in (self.platforms.get(arg) or {}).get('records', [])) if arg in self.platforms else None
        if name == 'cases':
            platform, _, op = arg.partition(':')
            cases = (self.platforms.get(platform) or {}).get('cases')
            return sum(c.get('operator') == op for c in cases) if cases else None
        if name == 'cases_total':
            cases = (self.platforms.get(arg) or {}).get('cases')
            return len(cases) if cases else None
        if name == 'raw_hold_records':
            items = [d for d in self.summary.get('disclosures') or [] if d.get('kind') == 'accelerator-raw-hold']
            counts = [int(m.group(1)) for d in items for m in [re.match(r'(\d+) records', d.get('text', ''))] if m]
            return sum(counts) if counts else None
        if name == 'tools_match':
            binaries = walk(self.roots['spec'], 'tools.binaries') or []
            return sum(bool(b.get('current_matches_recorded')) for b in binaries) if binaries else None
        if name == 'stage_sum':
            src, _, keys = arg.rpartition(':')
            stages = self.get(src + '|stage_seconds') if '|' not in src else self.get(src)
            if not isinstance(stages, dict):
                return None
            values = [stages.get(k) for k in keys.split(',')]
            return fmt_duration(sum(v for v in values if isinstance(v, (int, float)))) if any(isinstance(v, (int, float)) for v in values) else None
        if name == 'macro_supply_total':
            audit = walk(self.roots['physical'], 'cpu.route.macro_audit') or {}
            return (audit.get('supply_pins_connected') or 0) + (audit.get('supply_pins_bad') or 0) if audit else None
        if name == 'power_mean':
            rows = walk(self.roots['physical'], f'{arg}.power.records') or []
            values = [r.get('total_mw') if r.get('total_mw') is not None else (r.get('power_w') or 0) * 1000 for r in rows]
            return sum(values) / len(values) if values else None
        if name == 'omitted_files':
            return len(evidence.get('omitted') or []) if evidence else None
        if name == 'omitted_bytes':
            return sum(o.get('bytes') or 0 for o in evidence.get('omitted') or []) if evidence else None
        if name == 'evidence_files':
            return sum(not f.get('alias_of') for f in evidence.get('files') or []) if evidence else None
        if name == 'evidence_aliases':
            return sum(bool(f.get('alias_of')) for f in evidence.get('files') or []) if evidence else None
        if name == 'nano_pass':
            rows = walk(self.roots['nano'], f'{arg}.sessions')
            return sum(r.get('status') == 'PASS' for r in rows) if rows else None
        if name == 'gates_pass':
            return sum(bool(v) for v in gates.values()) if gates else None
        if name == 'gates_total':
            return len(gates) if gates else None
        if name == 'elapsed_h':
            seconds = walk(self.summary, 'one_hour.elapsed_seconds')
            return seconds / 3600 if isinstance(seconds, (int, float)) else None
        if name == 'peak_at_cap':
            rows = self.roots['resources'] or []
            return sum(1 for r in rows if r.get('memory_peak_bytes') and r.get('memory_limit_bytes') and r['memory_peak_bytes'] >= r['memory_limit_bytes']) if rows else None
        if name == 'package_sources':
            return sum(1 for p in (self.package / 'sources').rglob('*') if p.is_file()) if self.package and (self.package / 'sources').is_dir() else None
        if name == 'package_bytes':
            return self.package_bytes()
        if name == 'packaging_runs':
            return len(self.packaging_runs()) or None
        return None

    def package_bytes(self):
        if not self.package or not self.package.is_dir():
            return None
        skip = {'report.html', 'release.json', 'MANIFEST.sha256'}
        return sum(p.stat().st_size for p in self.package.rglob('*') if p.is_file() and p.relative_to(self.package).as_posix() not in skip)

    def package_contents(self):
        if not self.package or not self.package.is_dir():
            return []
        sizes = {}
        for p in self.package.rglob('*'):
            if p.is_file():
                rel = p.relative_to(self.package).as_posix()
                top = rel.split('/')[0] if '/' in rel else rel
                if rel.count('/') >= 1 and top in ('physical', 'power', 'data'):
                    top = '/'.join(rel.split('/')[:2])
                files, size = sizes.get(top, (0, 0))
                sizes[top] = (files + 1, size + p.stat().st_size)
        return [dict(path=k, files=v[0], bytes=v[1]) for k, v in sorted(sizes.items())]

    def packaging_runs(self):
        pattern = self.graph.get('packaging_runs')
        if not pattern:
            return []
        rows = []
        for path in sorted(glob.glob(str(self.repo / pattern))):
            value = self.load_json(path) or {}
            rows.append(dict(path=Path(path).relative_to(self.repo).as_posix(), status=value.get('status'), zip_bytes=value.get('zip_bytes'),
                             expanded_bytes=value.get('expanded_bytes'), clean_unzip_manifest_ok=value.get('clean_unzip_manifest_ok'),
                             verifier_exit=(value.get('clean_unzip_verifier') or {}).get('exit_code'),
                             problems=((value.get('clean_unzip_verifier') or {}).get('report') or {}).get('problem_count'),
                             failures=value.get('packaging_failures'), zip_path=value.get('zip_path'),
                             mtime=datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec='seconds')))
        return rows

    # -- node status / text
    def status(self, node):
        spec = node.get('status')
        if isinstance(spec, dict) and 'gates' in spec:
            gates = self.summary.get('gates') or {}
            values = [gates.get(g) for g in spec['gates']]
            if any(v is None for v in values):
                return 'NA'
            return 'PASS' if all(values) else 'NOT_MET'
        if isinstance(spec, dict) and 'src' in spec:
            value = self.get(spec['src'])
            if value is None:
                return 'NA'
            return 'PASS' if value == spec.get('equals') else 'HOLD'
        if isinstance(spec, str):
            return spec
        return 'INFO'

    def title(self, node):
        return template(node['title'], self.values(node.get('v')))

    def kpis(self, node):
        return [template(k.get('t'), self.values(k.get('v'))) for k in node.get('kpi', [])]

    def edge_count(self, edge):
        spec = edge.get('count')
        if not spec:
            return None
        if 'guard_node' in spec:
            return self.calc('guard_count:' + spec['guard_node']) or None
        if 'attempts' in spec:
            return self.calc('attempts:' + spec['attempts'])
        if spec.get('packaging_runs'):
            return len(self.packaging_runs()) or None
        if 'src' in spec:
            return self.get(spec['src'])
        return spec.get('value')

    # -- time analysis
    def time_window(self):
        start = parse_time(walk(self.summary, 'one_hour.started'))
        end = parse_time(self.summary.get('generated_at'))
        return start, end

    def sink_rows(self):
        rows = []
        for sink in self.graph.get('time_sinks', []):
            if sink.get('attempts'):
                attempts = self.attempt_rows(sink['attempts'])
                seconds = sum(a['elapsed'] or 0 for a in attempts)
                count = len(attempts)
                basis = [f"{a['label']}: {fmt_duration(a['elapsed']) or '—'} ({a['elapsed_basis'] or '无时长证据'})" for a in attempts]
            else:
                nodes = sink.get('guard_nodes') or [sink.get('guard_node')]
                names = sorted({n for node in nodes for n in self.guard_names(node)})
                entries = [self.guards.entries[n] for n in names]
                seconds = sum(e['elapsed'] or 0 for e in entries)
                count = len(entries)
                basis = [f'{count} 条记录（含 {sum(e["kind"] == "log" for e in entries)} 个仅日志、时长未知）']
            rows.append(dict(label=sink['label'], node=sink['node'], seconds=seconds, count=count, basis=basis))
        return sorted(rows, key=lambda r: -r['seconds'])

    def module_records(self):
        out = {}
        for module in self.graph['modules']:
            names = self.guard_names(module['id'])
            out[module['id']] = names
        return out

    # -- JSON for the page
    def node_payload(self, node_id):
        node = self.nodes[node_id]
        is_module = node_id in [m['id'] for m in self.graph['modules']]
        children = [c['id'] for c in (node.get('children') if is_module else node.get('chips')) or []]
        names = self.guard_names(node_id)
        views = []
        for view in node.get('views', []):
            view = dict(view)
            if view.get('src') is not None:
                value = self.get(view['src'])
                if isinstance(value, dict) and view.get('omit'):
                    value = {k: v for k, v in value.items() if k not in view['omit']}
                view['data'] = value
            if view.get('elapsed'):
                view['elapsed_value'] = self.get(view['elapsed'])
            views.append(view)
        return dict(id=node_id, module=self.module_of.get(node_id), parent=self.parent.get(node_id), is_module=is_module,
                    title=self.title(node), name=node.get('name'), short=node.get('short'), n=node.get('n'), kind=node.get('kind', 'module' if is_module else 'step'),
                    status=self.status(node) if not is_module else self.module_status(node),
                    kpi=self.kpis(node), desc=node.get('desc'), inputs=node.get('inputs'), outputs=node.get('outputs'),
                    files=node.get('files'), evidence=node.get('evidence'), children=children, guard=names,
                    guard_seconds=sum(self.guards.entries[n]['elapsed'] or 0 for n in names),
                    attempts=self.attempt_rows(node_id) if node.get('attempts') else None,
                    notes=[n for needle in node.get('notes', []) for n in self.notes.find(needle)],
                    notes_missing=[needle for needle in node.get('notes', []) if not self.notes.find(needle)],
                    views=views, lane=node.get('lane'))

    def module_status(self, module):
        states = [self.status(c) for c in module.get('children', [])]
        if any(s in ('NOT_MET', 'FAIL') for s in states):
            return 'NOT_MET'
        if any(s == 'HOLD' for s in states):
            return 'HOLD'
        if states and all(s in ('PASS', 'INFO', 'NA') for s in states) and any(s == 'PASS' for s in states):
            return 'PASS'
        return 'INFO'

    def payload(self):
        start, end = self.time_window()
        nodes = {nid: self.node_payload(nid) for nid in self.nodes}
        edges = [dict(edge, count_value=self.edge_count(edge)) for edge in self.graph.get('edges', [])]
        used = sorted({n for p in nodes.values() for n in p['guard']} | {a['guard'] for p in nodes.values() for a in p['attempts'] or [] if a.get('guard')})
        guards = {n: self.guards.entries[n] for n in used if n in self.guards.entries}
        return dict(schema='student-mini-report-bundle-v1', course=self.graph.get('course'), graph_file=None,
                    modules=[m['id'] for m in self.graph['modules']], lanes=self.graph.get('lanes'), nodes=nodes, edges=edges,
                    guards=guards, env_dir=self.guards.env_dir.relative_to(self.repo).as_posix() if self.guards.env_dir.is_relative_to(self.repo) else str(self.guards.env_dir),
                    env_records_total=len(self.guards.records()), notes_path=NOTES_PATH.relative_to(ROOT).as_posix(),
                    time=dict(start=start.isoformat() if start else None, end=end.isoformat() if end else None,
                              elapsed=walk(self.summary, 'one_hour.elapsed_seconds'), deadline=walk(self.roots['spec'], 'deadline_seconds') or 3600,
                              sinks=self.sink_rows(), causes=[dict(node=c['node'], text=template(c['t'], self.values(c.get('v')))) for c in self.graph.get('root_causes', [])],
                              modules=self.module_records()),
                    data=dict(summary={k: v for k, v in self.summary.items() if k not in ('sections', 'tiles')}, sections=self.summary.get('sections'),
                              physical=self.roots['physical'], nano=self.roots['nano'], resources=self.roots['resources'],
                              candidates=self.roots['candidates'], model_card=self.roots['model_card'], measure=self.roots['measure'],
                              golden={k: v for k, v in (self.roots['golden'] or {}).items() if k != 'cases'} if self.roots['golden'] else None,
                              spec=trim_spec(self.roots['spec']), evidence=compact_evidence(self.roots['evidence']),
                              packaging_runs=self.packaging_runs(), package_contents=self.package_contents(), package_bytes=self.package_bytes()))


def trim_spec(spec):
    if not spec:
        return None
    out = {k: v for k, v in spec.items() if k != 'tools'}
    tools = spec.get('tools') or {}
    out['tools'] = dict({k: v for k, v in tools.items() if k not in ('binaries', 'flow_and_pdk_files')},
                        binaries=[dict(path=b.get('path'), recorded=b.get('recorded_sha256'), current=b.get('current_sha256'),
                                       matches=b.get('current_matches_recorded'), version=' '.join(((b.get('version') or {}).get('output') or [])[:1]),
                                       bound_by_count=b.get('bound_by_count', len(b.get('bound_by') or []))) for b in tools.get('binaries') or []],
                        flow_and_pdk_files=[dict(path=f.get('path'), current=f.get('current_sha256'), matches=f.get('current_matches_recorded'),
                                                 bound_by_count=f.get('bound_by_count', len(f.get('bound_by') or []))) for f in tools.get('flow_and_pdk_files') or []])
    return out


def compact_evidence(index):
    if not index:
        return None
    files = [[f['path'], f.get('bytes'), f.get('sha256'), f.get('source_sha256'), f.get('source_bytes'), f.get('alias_of'), bool(f.get('compressed'))]
             for f in index.get('files') or []]
    return dict(columns=['path', 'bytes', 'sha256', 'source_sha256', 'source_bytes', 'alias_of', 'compressed'], files=files,
                omitted=index.get('omitted') or [], missing=index.get('missing') or [])


# ----------------------------------------------------------------------------- text measurement

def text_width(text, size, bold=False):
    width = 0.0
    for ch in str(text):
        o = ord(ch)
        if o >= 0x2E80 or ch in '（）：，、；。！？“”':
            width += 1.0
        elif ch in 'il.,:;|!\'`· ':
            width += 0.3
        elif ch in 'mwMW@%':
            width += 0.86
        elif ch.isupper() or ch.isdigit():
            width += 0.62
        else:
            width += 0.53
    return width * size * (1.05 if bold else 1.0)


def fit(text, size, width, bold=False):
    text = str(text)
    if text_width(text, size, bold) <= width:
        return text
    while text and text_width(text + '…', size, bold) > width:
        text = text[:-1]
    return text + '…'


def wrap(text, size, width, lines, bold=False):
    """Greedy wrap at spaces (Latin) or any character (CJK); the last line is truncated."""
    tokens = re.findall(r'[A-Za-z0-9_./+\-×≥≤%]+|\s+|.', str(text))
    out, line, i = [], '', 0
    while i < len(tokens):
        token = tokens[i]
        candidate = line + token
        if not line.strip() or text_width(candidate.strip(), size, bold) <= width:
            line, i = candidate, i + 1
            continue
        if len(out) == lines - 1:
            break
        out.append(fit(line.strip(), size, width, bold))
        line = ''
        if token.isspace():
            i += 1
    out.append(fit((line + ''.join(tokens[i:])).strip(), size, width, bold))
    return [o for o in out if o]


# ----------------------------------------------------------------------------- layout

def esc(text):
    return html.escape(str(text), quote=True)


class Box:
    def __init__(self, node_id, x, y, w, h):
        self.id, self.x, self.y, self.w, self.h = node_id, x, y, w, h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2


def layout(graph):
    """Module frames, node boxes and chip boxes on the fixed canvas."""
    modules = graph['modules']
    weights = [m.get('w', 1.0) for m in modules]
    usable = W - 16 - GAP * (len(modules) - 1)
    unit = usable / sum(weights)
    lanes = graph.get('lanes') or [{'id': 'A', 'height': 76}, {'id': 'cpu', 'height': 172}, {'id': 'accelerator', 'height': 144}]
    inner_top, inner_bottom = DIAG_TOP + MOD_HEAD + BUS_GAP, DIAG_BOTTOM
    total = sum(l.get('height', 1) for l in lanes)
    avail = inner_bottom - inner_top - GAP * (len(lanes) - 1)
    bands, y = {}, inner_top
    for lane in lanes:
        h = avail * lane.get('height', 1) / total
        bands[lane['id']] = (y, h)
        y += h + GAP
    frames, boxes, chips = {}, {}, {}
    x = 8.0
    first_lanes = next((m['id'] for m in modules if m.get('layout') == 'lanes'), None)
    for module, weight in zip(modules, weights):
        w = unit * weight
        frames[module['id']] = Box(module['id'], x, DIAG_TOP, w, DIAG_BOTTOM - DIAG_TOP)
        gutter = 16 if module['id'] == first_lanes else 0
        ix, iw = x + 6 + gutter, w - 12 - gutter
        if module.get('layout') == 'stack':
            place_stack(module.get('children', []), ix, inner_top, iw, inner_bottom - inner_top, boxes)
        else:
            for lane in lanes:
                members = [c for c in module.get('children', []) if c.get('lane') == lane['id']]
                if not members:
                    continue
                by, bh = bands[lane['id']]
                ratios = (module.get('cols') or {}).get(lane['id']) or [1.0]
                ncols = max(len(ratios), 1 + max(c.get('col', 0) for c in members))
                ratios = (list(ratios) + [1.0] * ncols)[:ncols]
                cx = ix
                for col in range(ncols):
                    cw = (iw - GAP * (ncols - 1)) * ratios[col] / sum(ratios)
                    place_stack([c for c in members if c.get('col', 0) == col], cx, by, cw, bh, boxes)
                    cx += cw + GAP
        x += w + GAP
    for module in modules:
        for child in module.get('children', []):
            box = boxes.get(child['id'])
            if box and child.get('chips'):
                place_chips(child, box, chips)
    owner = {}
    for module in modules:
        for child in module.get('children', []):
            owner[child['id']] = module['id']
            for chip in child.get('chips', []):
                owner[chip['id']] = module['id']
    return frames, boxes, chips, bands, first_lanes, owner


def place_stack(children, x, y, w, h, boxes):
    if not children:
        return
    weights = [c.get('h', 1.0) for c in children]
    avail = h - GAP * (len(children) - 1)
    for child, weight in zip(children, weights):
        bh = avail * weight / sum(weights)
        boxes[child['id']] = Box(child['id'], x, y, w, bh)
        y += bh + GAP


def place_chips(node, box, chips):
    cols = node.get('chip_cols', 2)
    items = node['chips']
    rows = math.ceil(len(items) / cols)
    head = 33 if node.get('kpi') else 21
    top = box.y + head
    avail_h = box.y + box.h - 5 - top
    ch = min(26, (avail_h - 4 * (rows - 1)) / rows)
    cw = (box.w - 12 - 4 * (cols - 1)) / cols
    for i, chip in enumerate(items):
        r, c = divmod(i, cols)
        chips[chip['id']] = Box(chip['id'], box.x + 6 + c * (cw + 4), top + r * (ch + 4), cw, ch)


# ----------------------------------------------------------------------------- SVG

STATUS_CLASS = {'PASS': 'pass', 'HOLD': 'hold', 'NOT_MET': 'fail', 'FAIL': 'fail', 'NA': 'na', 'INFO': 'info'}


def svg_text(x, y, text, cls, anchor=None, extra=''):
    a = f' text-anchor="{anchor}"' if anchor else ''
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}"{a}{extra}>{esc(text)}</text>'


def node_svg(bundle, node, box, is_chip=False):
    status = bundle.status(node)
    kind = node.get('kind', 'step')
    title = bundle.title(node)
    kpis = bundle.kpis(node)
    tip = ' · '.join([title] + kpis) + ' — 点击查看详情'
    cls = f"nd {'chip' if is_chip else 'box'} st-{STATUS_CLASS.get(status, 'info')} k-{kind}"
    out = [f'<a href="#/node/{esc(node["id"])}" class="{cls}" data-id="{esc(node["id"])}"><title>{esc(tip)}</title>']
    if is_chip:
        out.append(f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" rx="4" class="bg"/>')
        out.append(svg_text(box.x + 6, box.cy + 4, fit(title, 11, box.w - 10), 'ct'))
        out.append('</a>')
        return ''.join(out)
    out.append(f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" rx="6" class="bg"/>')
    out.append(f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="4" height="{box.h:.1f}" rx="2" class="bar"/>')
    pad = 18 if kind in ('gate', 'hold') else 9
    if kind == 'gate':
        cy = box.y + 12
        out.append(f'<path d="M{box.x + 10:.1f} {cy - 5:.1f} l5 5 l-5 5 l-5 -5 z" class="gem"/>')
    if kind == 'hold':
        out.append(f'<circle cx="{box.x + 10:.1f}" cy="{box.y + 12:.1f}" r="4.5" class="gem"/>')
    tw = box.w - pad - 8
    has_chips = bool(node.get('chips'))
    max_title = 1 if has_chips or box.h < 46 else 2
    lines = wrap(title, 12.5, tw, max_title, bold=True)
    y = box.y + 15.5
    for line in lines:
        out.append(svg_text(box.x + pad, y, line, 't'))
        y += 14
    room = box.y + box.h - 4
    if has_chips:
        room = box.y + 33
    for k in kpis:
        if y + 9 > room + 1:
            break
        out.append(svg_text(box.x + pad, y + 0.5, fit(k, 11, box.w - pad - 8), 'k'))
        y += 13
    out.append('</a>')
    return ''.join(out)


def ortho(points, r=5.0):
    """Orthogonal polyline with rounded corners."""
    d = f'M{points[0][0]:.1f} {points[0][1]:.1f}'
    for i in range(1, len(points) - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[i - 1], points[i], points[i + 1]
        l1, l2 = abs(x1 - x0) + abs(y1 - y0), abs(x2 - x1) + abs(y2 - y1)
        k = min(r, l1 / 2, l2 / 2)
        ax = x1 - k * ((x1 > x0) - (x1 < x0)) if l1 else x1
        ay = y1 - k * ((y1 > y0) - (y1 < y0)) if l1 else y1
        bx = x1 + k * ((x2 > x1) - (x2 < x1)) if l2 else x1
        by = y1 + k * ((y2 > y1) - (y2 < y1)) if l2 else y1
        d += f' L{ax:.1f} {ay:.1f} Q{x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}'
    return d + f' L{points[-1][0]:.1f} {points[-1][1]:.1f}'


def edge_path(a, b, edge, ctx):
    """Path between two boxes and the point where a loop badge sits.

    Same module: direct curves.  Adjacent modules: through the gap between them.  Modules further apart:
    up the module gap into the bus channel under the module headers (one track per edge type), along it and
    down the gap next to the target, so long edges never cut diagonally across other steps."""
    frames, order, owner = ctx['frames'], ctx['order'], ctx['owner']
    if a.id == b.id:
        x, y = a.x + a.w - 14, a.y + 2
        return (f'M{x - 7:.1f} {y + 6:.1f} a7 7 0 1 1 7 7', (x + 2, y - 1))
    ma, mb = owner.get(a.id), owner.get(b.id)
    ia, ib = order.get(ma, 0), order.get(mb, 0)
    if ma != mb and ma in frames and mb in frames:
        fa, fb = frames[ma], frames[mb]
        forward = ib > ia
        if abs(ib - ia) == 1:
            gx = (fa.x + fa.w + fb.x) / 2 if forward else (fb.x + fb.w + fa.x) / 2
            x1 = a.x + a.w if forward else a.x
            x2 = b.x if forward else b.x + b.w
            pts = [(x1, a.cy), (gx, a.cy), (gx, b.cy), (x2, b.cy)]
            return ortho(pts), (gx, (a.cy + b.cy) / 2)
        bus = DIAG_TOP + MOD_HEAD - 4 + BUS_TRACK.get(edge.get('type'), 7.0)
        if forward:
            g1, g2 = fa.x + fa.w + GAP / 2, fb.x - GAP / 2
            pts = [(a.x + a.w, a.cy), (g1, a.cy), (g1, bus), (g2, bus), (g2, b.cy), (b.x, b.cy)]
        else:
            g1, g2 = fa.x - GAP / 2, fb.x + fb.w + GAP / 2
            pts = [(a.x, a.cy), (g1, a.cy), (g1, bus), (g2, bus), (g2, b.cy), (b.x + b.w, b.cy)]
        return ortho(pts), ((g1 + g2) / 2, bus)
    if edge.get('type') == 'loop' and b.x + b.w <= a.x + 1:
        x1, y1 = a.x + 10, a.y + 1
        x2, y2 = b.x + b.w - 10, b.y + 1
        lift = min(y1, y2) - 22
        d = f'M{x1:.1f} {y1:.1f} C{x1 - 10:.1f} {lift:.1f} {x2 + 10:.1f} {lift:.1f} {x2:.1f} {y2:.1f}'
        return d, ((x1 + x2) / 2, lift + 6)
    overlap = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    if overlap > 10:
        cx = max(a.x, b.x) + overlap / 2
        y1, y2 = (a.y + a.h, b.y) if b.y > a.y else (a.y, b.y + b.h)
        mid = (y1 + y2) / 2
        return f'M{cx:.1f} {y1:.1f} C{cx:.1f} {mid:.1f} {cx:.1f} {mid:.1f} {cx:.1f} {y2:.1f}', (cx, mid)
    if b.x >= a.x + a.w - 1:
        x1, y1, x2, y2 = a.x + a.w, a.cy, b.x, b.cy
    else:
        x1, y1, x2, y2 = a.x, a.cy, b.x + b.w, b.cy
    gx = (x1 + x2) / 2
    return ortho([(x1, y1), (gx, y1), (gx, y2), (x2, y2)]), (gx, (y1 + y2) / 2)


def panorama_svg(bundle):
    graph = bundle.graph
    frames, boxes, chips, bands, first_lanes, owner = layout(graph)
    allboxes = dict(boxes, **chips)
    ctx = dict(frames=frames, owner=owner, order={m['id']: i for i, m in enumerate(graph['modules'])})
    summary = bundle.summary
    course = summary.get('course') or {}
    out = [f'<svg id="pano-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="生产流程全景">', '<defs>']
    for t in EDGE_TYPES:
        out.append(f'<marker id="ar-{t}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                   f'<path d="M0 0 L10 5 L0 10 z" class="mk mk-{t}"/></marker>')
    out.append('</defs>')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" class="canvas"/>')
    # ---- header
    title = template(graph.get('title', '{release_id}'), dict(release_id=summary.get('release_id'), course=course.get('name', '三平台')))
    out.append(svg_text(14, 27, fit(title, 19, 820, True), 'h1'))
    out.append(svg_text(14, 47, fit(graph.get('subtitle', ''), 11.5, 860), 'sub'))
    elapsed_h = bundle.calc('elapsed_h')
    pills = [(f"发布状态 {summary.get('status')}", 'fail' if summary.get('status') != 'COMPLETE' else 'pass', 'pkg.hold'),
             (f"baseline {sum(b['status'] == 'PASS' for b in summary.get('baselines') or [])}/{len(summary.get('baselines') or [])} PASS",
              'pass' if all(b['status'] == 'PASS' for b in summary.get('baselines') or []) else 'hold', 'base.gate'),
             (f"一小时目标 未达成 · {elapsed_h:.1f} h" if elapsed_h and not (summary.get('gates') or {}).get('one-hour') else '一小时目标 达成',
              'fail' if not (summary.get('gates') or {}).get('one-hour') else 'pass', 'why')]
    px = W - 56
    for text, cls, target in reversed(pills):
        pw = text_width(text, 12, True) + 20
        px -= pw
        out.append(f'<a href="#/node/{target}" class="pill st-{cls}"><rect x="{px:.1f}" y="14" width="{pw:.1f}" height="26" rx="13" class="bg"/>'
                   f'{svg_text(px + pw / 2, 31.5, text, "pt", "middle")}</a>')
        px -= 8
    # ---- lane bands (behind the lane modules)
    lane_mods = [m for m in graph['modules'] if m.get('layout') == 'lanes']
    if lane_mods:
        x0 = frames[lane_mods[0]['id']].x
        x1 = frames[lane_mods[-1]['id']].x + frames[lane_mods[-1]['id']].w
        for lane in graph.get('lanes', []):
            by, bh = bands[lane['id']]
            out.append(f'<rect x="{x0:.1f}" y="{by - 2:.1f}" width="{x1 - x0:.1f}" height="{bh + 4:.1f}" class="band band-{esc(lane["id"])}"/>')
    # ---- module frames
    for i, module in enumerate(graph['modules']):
        f = frames[module['id']]
        names = bundle.guard_names(module['id'])
        seconds = sum(bundle.guards.entries[n]['elapsed'] or 0 for n in names)
        status = bundle.module_status(module)
        agg = f'受限运行 {len(names)} 次 · Σ {fmt_duration(seconds) or "0 s"}' if names else '无受限运行记录'
        out.append(f'<a href="#/node/{esc(module["id"])}" class="mod st-{STATUS_CLASS.get(status, "info")}" data-id="{esc(module["id"])}">'
                   f'<title>{esc(module["title"])} — {esc(agg)} — 点击查看模块详情</title>'
                   f'<rect x="{f.x:.1f}" y="{f.y:.1f}" width="{f.w:.1f}" height="{f.h:.1f}" rx="9" class="frame"/>'
                   f'<rect x="{f.x:.1f}" y="{f.y:.1f}" width="{f.w:.1f}" height="{MOD_HEAD - 4}" rx="9" class="head"/>'
                   f'<circle cx="{f.x + 15:.1f}" cy="{f.y + 15:.1f}" r="10" class="num"/>{svg_text(f.x + 15, f.y + 19.5, module.get("n", i + 1), "numt", "middle")}'
                   f'{svg_text(f.x + 30, f.y + 19.5, fit(module["title"], 13.5, f.w - 36, True), "mt")}'
                   f'{svg_text(f.x + 30, f.y + 32.5, fit(agg, 10.5, f.w - 36), "ma")}</a>')
        if i < len(graph['modules']) - 1:
            nf = frames[graph['modules'][i + 1]['id']]
            out.append(f'<path d="M{f.x + f.w - 1:.1f} {f.y + 18:.1f} L{nf.x + 1:.1f} {f.y + 18:.1f}" class="flow" marker-end="url(#ar-data)"/>')
    if first_lanes:
        f = frames[first_lanes]
        for lane in graph.get('lanes', []):
            by, bh = bands[lane['id']]
            cx, cy = f.x + 13, by + bh / 2
            out.append(f'<text x="{cx:.1f}" y="{cy:.1f}" class="lane" text-anchor="middle" transform="rotate(-90 {cx:.1f} {cy:.1f})">'
                       f'{esc(fit(lane.get("label", lane["id"]), 10.5, bh - 6))}</text>')
    # ---- nodes
    for node, parent, module in iter_nodes(graph):
        box = allboxes.get(node['id'])
        if box is None:
            continue
        out.append(node_svg(bundle, node, box, is_chip=node['id'] in chips))
    # ---- edges (above boxes, low opacity until hovered)
    out.append('<g id="edges">')
    for edge in graph.get('edges', []):
        a, b = allboxes.get(edge['from']), allboxes.get(edge['to'])
        if not a or not b:
            continue
        d, (bx, by) = edge_path(a, b, edge, ctx)
        count = bundle.edge_count(edge)
        label = edge.get('label', '')
        tip = f"{EDGE_LABELS[edge['type']]}：{bundle.title(bundle.nodes[edge['from']])} → {bundle.title(bundle.nodes[edge['to']])}" + (f' · {label}' if label else '') + \
              (f" · {count} {edge.get('unit', '次')}" if count is not None else '')
        marker = '' if a.id == b.id and edge['type'] == 'loop' else f' marker-end="url(#ar-{edge["type"]})"'
        if a.id == b.id:
            marker = f' marker-end="url(#ar-loop)"'
        out.append(f'<g class="edge e-{edge["type"]}" data-from="{esc(edge["from"])}" data-to="{esc(edge["to"])}"><title>{esc(tip)}</title>'
                   f'<path d="{d}" class="hit"/><path d="{d}" class="ln"{marker}/>')
        if edge['type'] == 'loop':
            text = f'×{count}' if count is not None else '×?'
            bw = text_width(text, 10.5, True) + 10
            out.append(f'<rect x="{bx - bw / 2 + (bw / 2 if a.id == b.id else 0):.1f}" y="{by - 8:.1f}" width="{bw:.1f}" height="15" rx="7.5" class="badge"/>'
                       f'{svg_text(bx + (bw / 2 if a.id == b.id else 0), by + 3.5, text, "bt", "middle")}')
        out.append('</g>')
    out.append('</g>')
    # ---- legend
    lx = 14
    out.append(svg_text(lx, LEGEND_Y + 10, '图例（点击切换显示）：', 'lg'))
    lx += text_width('图例（点击切换显示）：', 11) + 6
    for t in EDGE_TYPES:
        out.append(f'<g class="legend e-{t}" data-type="{t}" tabindex="0" role="button"><rect x="{lx - 3:.1f}" y="{LEGEND_Y - 1:.1f}" '
                   f'width="{text_width(EDGE_LABELS[t], 11) + 44:.1f}" height="16" rx="4" class="lgbg"/>'
                   f'<path d="M{lx:.1f} {LEGEND_Y + 7:.1f} L{lx + 30:.1f} {LEGEND_Y + 7:.1f}" class="ln" marker-end="url(#ar-{t})"/>'
                   f'{svg_text(lx + 36, LEGEND_Y + 11, EDGE_LABELS[t], "lg")}</g>')
        lx += text_width(EDGE_LABELS[t], 11) + 54
    for cls, text in (('pass', 'PASS'), ('hold', 'HOLD'), ('fail', 'NOT MET'), ('info', '信息 / 无门')):
        out.append(f'<rect x="{lx:.1f}" y="{LEGEND_Y + 1:.1f}" width="12" height="12" rx="3" class="sw st-{cls}"/>{svg_text(lx + 16, LEGEND_Y + 11, text, "lg")}')
        lx += text_width(text, 11) + 28
    out.append(svg_text(W - 14, LEGEND_Y + 11, '◆ 验收门   ● 阻塞项   悬停方块高亮其连线', 'lg', 'end'))
    # ---- bottom panels
    out += why_panel(bundle)
    out += contents_panel(bundle)
    out.append('</svg>')
    return '\n'.join(out)


def why_panel(bundle):
    x0, y0, x1, y1 = 8, PANEL_TOP, 930, PANEL_BOTTOM
    out = [f'<a href="#/node/why" class="panel" data-id="why"><title>时间分析详情</title>'
           f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="9" class="frame"/></a>']
    start, end = bundle.time_window()
    elapsed = walk(bundle.summary, 'one_hour.elapsed_seconds')
    hours = elapsed / 3600 if isinstance(elapsed, (int, float)) else None
    head = (f'为什么用了 {hours:.1f} 小时（≈ {hours / 24:.1f} 天），而目标是 1 小时？' if hours else '耗时')
    out.append(svg_text(x0 + 12, y0 + 20, head, 'ph'))
    out.append(svg_text(x1 - 12, y0 + 20, '计时：SPEC.implementation_started_at → 本次装配 generated_at；条 = 每条受限运行', 'pn', 'end'))
    # gantt
    gx0, gx1, gy0 = x0 + 84, x0 + 560, y0 + 36
    rows = bundle.graph['modules']
    rh = 15
    records = bundle.module_records()
    if start and end and end > start:
        span = (end - start).total_seconds()
        scale = (gx1 - gx0) / span
        day = (start.astimezone(timezone(timedelta(hours=8)))).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        while day < end:
            gx = gx0 + (day - start).total_seconds() * scale
            out.append(f'<line x1="{gx:.1f}" y1="{gy0 - 4}" x2="{gx:.1f}" y2="{gy0 + rh * len(rows) + 2}" class="grid"/>')
            out.append(svg_text(gx + 2, gy0 + rh * len(rows) + 13, day.strftime('%m-%d'), 'ax'))
            day += timedelta(days=1)
        dl = (walk(bundle.roots['spec'], 'deadline_seconds') or 3600) * scale
        out.append(f'<rect x="{gx0:.1f}" y="{gy0 - 6:.1f}" width="{max(dl, 1.5):.1f}" height="{rh * len(rows) + 8}" class="deadline"/>')
        out.append(svg_text(gx0 + max(dl, 1.5) + 3, gy0 - 8 + 4, '◀ 1 h 目标', 'dl'))
        for i, module in enumerate(rows):
            ry = gy0 + i * rh
            label = fit(f"{module.get('n', i + 1)} {module.get('short', module['title'])}", 10.5, 70)
            out.append(f'<a href="#/node/{esc(module["id"])}" class="grow"><title>{esc(module["title"])}：{len(records[module["id"]])} 条受限运行</title>'
                       f'<rect x="{x0 + 8}" y="{ry:.1f}" width="{gx1 - x0 - 8}" height="{rh - 2}" class="rowbg"/>'
                       + svg_text(x0 + 12, ry + 10.5, label, 'rl'))
            for name in records[module['id']]:
                e = bundle.guards.entries[name]
                if e['start'] is None:
                    continue
                bx = gx0 + (e['start'] - start.timestamp()) * scale
                bw = max(1.4, (e['elapsed'] or 0) * scale)
                cls = 'pass' if e['status'] == 'PASS' else 'hold'
                out.append(f'<rect x="{bx:.1f}" y="{ry + 2:.1f}" width="{bw:.1f}" height="{rh - 6}" class="gb st-{cls}"><title>{esc(name)} · {esc(e["status"])} · '
                           f'{esc(fmt_duration(e["elapsed"]) or "—")}</title></rect>')
            out.append('</a>')
    # time sinks
    sx0, sy = x0 + 576, y0 + 40
    out.append(svg_text(sx0, sy - 6, '主要耗时（受限运行累计，含失败尝试）', 'pk'))
    sinks = bundle.sink_rows()[:6]
    top = max([s['seconds'] for s in sinks] + [1])
    for s in sinks:
        bwid = 120 * s['seconds'] / top
        value = f"{fmt_duration(s['seconds']) or '0 s'} · {s['count']} 次"
        out.append(f'<a href="#/node/{esc(s["node"])}" class="sink"><title>{esc(s["label"])}：{esc(value)} — {esc("; ".join(s["basis"]))}</title>'
                   + svg_text(sx0, sy + 10, fit(s['label'], 10.8, 168), 'sl')
                   + f'<rect x="{sx0 + 172}" y="{sy + 1}" width="{max(bwid, 1.5):.1f}" height="11" rx="2" class="sinkbar"/>'
                   + svg_text(sx0 + 176 + bwid, sy + 10.5, value, 'sv') + '</a>')
        sy += 17
    # root causes
    cy = y0 + 182
    out.append(svg_text(x0 + 12, cy, '根因（证据：guard 记录 / completion.json / NOTES.md）', 'pk'))
    for i, cause in enumerate(bundle.graph.get('root_causes', [])[:6]):
        text = template(cause['t'], bundle.values(cause.get('v')))
        line = fit(chr(0x2460 + i) + ' ' + text, 10.8, x1 - x0 - 28)
        out.append(f'<a href="#/node/{esc(cause["node"])}" class="cause"><title>{esc(text)}</title>'
                   + svg_text(x0 + 14, cy + 15 + i * 14.2, line, 'cz') + '</a>')
    return out


def contents_panel(bundle):
    x0, y0, x1, y1 = 938, PANEL_TOP, 1432, PANEL_BOTTOM
    summary = bundle.summary
    out = [f'<a href="#/node/contents" class="panel" data-id="contents"><title>包内容详情</title>'
           f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="9" class="frame"/></a>']
    out.append(svg_text(x0 + 12, y0 + 20, '包里有什么 · 达成了什么', 'ph'))
    course = summary.get('course') or {}
    platforms = course.get('platforms') or sorted({b['platform'] for b in summary.get('baselines') or []})
    ops = ['p1', 'p2', 'p3']
    names = {'cpu': 'CPU', 'gpu': 'GPU', 'accelerator': '加速器'}
    mx, my, cw, chh = x0 + 66, y0 + 30, 136, 34
    for j, op in enumerate(ops):
        out.append(svg_text(mx + j * (cw + 4) + cw / 2, my + 9, op.upper(), 'mh', 'middle'))
    for i, p in enumerate(platforms):
        ry = my + 14 + i * (chh + 4)
        out.append(svg_text(x0 + 12, ry + 21, names.get(p, p), 'mh'))
        for j, op in enumerate(ops):
            b = next((b for b in summary.get('baselines') or [] if b['platform'] == p and b['operator'] == op), None)
            if not b:
                continue
            cls = STATUS_CLASS.get(b['status'], 'info')
            bx = mx + j * (cw + 4)
            cycles = b.get('mean_cycles')
            line1 = f"{b['status']} {b['passed']}/{b['records']}"
            line2 = f"{b['power']} · {cycles:,.0f} cyc" if isinstance(cycles, (int, float)) else str(b['power'])
            tip = (f"{p} {op}：{b['status']}，{b['passed']}/{b['records']} 记录，{b['cases_passed']}/{b['cases']} case，"
                   f"平均 {cycles} cycles，功耗 {b['power']}（seed 均值）— 点击查看全部 case")
            out.append(f'<a href="#/records/{esc(p)}/{esc(op)}" class="cell st-{cls}"><title>{esc(tip)}</title>'
                       f'<rect x="{bx}" y="{ry}" width="{cw}" height="{chh}" rx="5" class="bg"/>'
                       + svg_text(bx + 7, ry + 14, line1, 'cs') + svg_text(bx + 7, ry + 27.5, fit(line2, 10.5, cw - 12), 'cv') + '</a>')
    # gates
    gy = my + 14 + len(platforms) * (chh + 4) + 8
    gates = summary.get('gates') or {}
    out.append(svg_text(x0 + 12, gy + 4, f'发布门 {sum(bool(v) for v in gates.values())}/{len(gates)} 通过', 'pk'))
    gx, gyy = x0 + 12, gy + 10
    for name, ok in gates.items():
        gw = text_width(name, 9.8) + 20
        if gx + gw > x1 - 10:
            gx, gyy = x0 + 12, gyy + 17
        out.append(f'<a href="#/node/{esc(gate_owner(bundle, name))}" class="gt st-{"pass" if ok else "fail"}"><title>{esc(name)}：{"PASS" if ok else "NOT MET"}</title>'
                   f'<rect x="{gx:.1f}" y="{gyy:.1f}" width="{gw:.1f}" height="14" rx="7" class="bg"/>'
                   f'{svg_text(gx + 7, gyy + 10.5, ("✓ " if ok else "✗ ") + name, "gtt")}</a>')
        gx += gw + 4
    # contents
    cy = gyy + 30
    records = sum(len(v.get('records', [])) for v in bundle.platforms.values())
    power = sum(len(((bundle.roots['physical'] or {}).get(k) or {}).get('power', {}).get('records') or []) for k in (bundle.roots['physical'] or {}))
    nano = sum(len(v.get('sessions') or []) for v in (bundle.roots['nano'] or {}).values())
    pkg = fmt_bytes(bundle.package_bytes())
    line1 = f'{records} 条记录（输入/golden/actual/delta）· {power} 条逐 seed 功耗 · {nano} 段 Nano 会话'
    line2 = (f'证据 {bundle.calc("evidence_files")} 个文件 + {bundle.calc("evidence_aliases")} 别名（SHA-256）· 省略 {bundle.calc("omitted_files")} 个 VCD '
             f'{fmt_bytes(bundle.calc("omitted_bytes"))} · 包内文件 {pkg}（渲染时）')
    out.append(f'<a href="#/node/contents" class="ctl"><title>包内容详情</title>{svg_text(x0 + 12, cy, fit(line1, 10.8, x1 - x0 - 24), "cl")}'
               f'{svg_text(x0 + 12, cy + 15, fit(line2, 10.8, x1 - x0 - 24), "cl")}</a>')
    kinds = {}
    for d in summary.get('disclosures') or []:
        kinds[d['kind']] = kinds.get(d['kind'], 0) + 1
    label = {'resource-record-hold': '受限记录 HOLD', 'note': '计划说明', 'accelerator-raw-hold': '加速器原始 HOLD→复验',
             'physical-reaudit': '物理复核', 'physical-eco-from': 'GPU ECO 续跑', 'one-hour': '一小时未达成'}
    text = f'HOLD 与披露 {sum(kinds.values())} 项：' + ' · '.join(f'{label.get(k, k)} {v}' for k, v in kinds.items())
    out.append(f'<a href="#/node/disclosures" class="ctl hold"><title>全部 HOLD 与披露事项</title>{svg_text(x0 + 12, cy + 34, fit(text, 11, x1 - x0 - 24, True), "dz")}</a>')
    return out


def gate_owner(bundle, gate):
    for node, _, _ in iter_nodes(bundle.graph):
        if gate in ((node.get('status') or {}).get('gates') or [] if isinstance(node.get('status'), dict) else []):
            return node['id']
    return 'pkg.assemble'
