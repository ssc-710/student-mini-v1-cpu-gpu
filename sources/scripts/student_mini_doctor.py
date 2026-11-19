"""Read-only student preflight. This is not clean-install or release qualification.

No downloads, installation, GPU probing, training or hardware simulation occur.
Tool prefixes are chosen by the student; no development-machine path is needed.
"""
import argparse
import hashlib
from importlib import metadata
import json
import platform
from pathlib import Path
import re
import shutil
import sys


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def locked_json(path, expected):
    if not expected or not re.fullmatch('[0-9a-f]{64}', expected) or digest(path) != expected:
        raise ValueError('lock SHA differs; use the published full SHA-256')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def python_checks(lock, version=metadata.version):
    rows = []
    seen = set()
    for package in lock['packages']:
        name = re.sub('[-_.]+', '-', package['name']).lower()
        if name in seen: raise ValueError('duplicate Python distribution in lock')
        seen.add(name)
        try: actual = version(name)
        except metadata.PackageNotFoundError: actual = None
        rows.append(dict(component=name, expected=package['version'], actual=actual,
                         status='MATCH' if actual == package['version'] else 'MISSING_OR_DIFFERENT',
                         scope='installed version only; not an installed-file integrity certificate'))
    if not rows: raise ValueError('empty Python lock')
    return rows


def tool_checks(lock, route, mode, prefixes):
    wanted = [('CPU / accelerator RTL', 'cpu')]
    if route == 'B': wanted.append(('GPU RTLSIM / source export', 'gpu'))
    if mode == 'physical':
        wanted += [('Synthesis / formal', 'eda'), ('Post-route gate simulation', 'eda'),
                   ('Gate simulation runtime', 'eda'), ('Bounded formal orchestration', 'eda'),
                   ('Bounded formal solver', 'eda'), ('Placement / route / STA / power', 'openroad')]
    rows = []
    for role, prefix in wanted:
        selected = [row for row in lock['tools'] if row['role'] == role]
        if len(selected) != 1: raise ValueError('unique locked tool role required: '+role)
        for binary in selected[0]['binaries']:
            name = binary['name']
            if Path(name).name != name or name in ('.', '..'):
                raise ValueError('tool lock must contain binary basenames')
            expected = binary['sha256']
            if not re.fullmatch('[0-9a-f]{64}', expected): raise ValueError('invalid binary SHA')
            folder = prefixes.get(prefix)
            path = Path(folder)/name if folder else None
            actual = digest(path) if path and path.is_file() else None
            rows.append(dict(component=role+' / '+name, prefix_option='--'+prefix+'-bin',
                             expected_sha256=expected, actual_sha256=actual,
                             status='MATCH' if actual == expected else 'MISSING_OR_DIFFERENT',
                             scope='named executable only; runtime libraries and source closure are separate'))
    return rows


def build_report(route, mode, *, python_lock=None, tool_lock=None, prefixes=None,
                 system=None, python_version=None, which=shutil.which):
    if route not in ('A', 'B') or mode not in ('report', 'functional', 'physical'):
        raise ValueError('choose route A/B and report/functional/physical')
    observed_system = system or dict(os=platform.system(), machine=platform.machine())
    version = python_version or list(sys.version_info[:3])
    rows = [dict(component='Python reader', status='MATCH' if tuple(version) >= (3, 11) else 'MISSING_OR_DIFFERENT',
                 actual=version, expected='>=3.11 for the standard-library offline readers')]
    if mode != 'report':
        rows.append(dict(component='simulation host', actual=observed_system,
                         expected='Linux x86-64 (Ubuntu 24.04, including WSL2)',
                         status='MATCH' if observed_system == dict(os='Linux', machine='x86_64') else 'MISSING_OR_DIFFERENT'))
        rows.append(dict(component='locked Python ABI', actual=version[:2], expected=[3, 12],
                         status='MATCH' if list(version[:2]) == [3, 12] else 'MISSING_OR_DIFFERENT'))
        if python_lock is None or tool_lock is None:
            raise ValueError('functional/physical preflight requires both SHA-verified locks')
        rows += python_checks(python_lock)
        rows += tool_checks(tool_lock, route, mode, prefixes or {})
        for name in ('gcc', 'g++', 'make', 'pkg-config', 'riscv64-unknown-elf-gcc', 'riscv64-unknown-elf-objcopy'):
            found = which(name)
            rows.append(dict(component=name, resolved=found, status='FOUND_UNQUALIFIED' if found else 'MISSING_OR_DIFFERENT',
                             scope='PATH discovery only; exact compiler/library verification remains'))
    failures = [row['component'] for row in rows if row['status'] == 'MISSING_OR_DIFFERENT']
    return dict(schema='student-mini-doctor-v1', route=route, mode=mode,
                status='PREFLIGHT_NEEDS_ATTENTION' if failures else 'SCOPED_PREFLIGHT_PASS',
                checks=rows, failed_checks=failures, hardware_executed=False, real_gpu_required=False,
                environment_qualified=False, baseline_qualified=False, release_qualified=False,
                remaining=[] if mode == 'report' else [
                    'exact system/compiler/runtime-library integrity and licenses',
                    'LiteX/source/firmware provenance and clean-environment execution',
                    *(['Vortex SimX/RTLSIM and LLVM/POCL/chipStar workload execution'] if route == 'B' else []),
                    *(['ORFS/SKY130HD/macro views and actual route/power workload'] if mode == 'physical' else []),
                    '2 vCPU / 8 GiB bounded workload and full six-baseline qualification'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', choices=('A', 'B'), required=True)
    parser.add_argument('--mode', choices=('report', 'functional', 'physical'), default='report')
    for name in ('python', 'tool'):
        parser.add_argument('--'+name+'-lock', type=Path)
        parser.add_argument('--'+name+'-lock-sha256')
    for name in ('cpu', 'gpu', 'eda', 'openroad'): parser.add_argument('--'+name+'-bin', type=Path)
    args = parser.parse_args()
    try:
        locks = {}
        if args.mode != 'report':
            for name in ('python', 'tool'):
                path = getattr(args, name+'_lock')
                if path is None: raise ValueError('--'+name+'-lock is required')
                locks[name+'_lock'] = locked_json(path, getattr(args, name+'_lock_sha256'))
        report = build_report(args.route, args.mode, **locks,
                              prefixes={name:getattr(args, name+'_bin') for name in ('cpu', 'gpu', 'eda', 'openroad')})
        report['doctor_source_sha256'] = digest(Path(__file__))
        report['lock_sha256'] = {name:getattr(args, name+'_lock_sha256') for name in ('python', 'tool')} if locks else {}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report['failed_checks'] else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(status='PREFLIGHT_ERROR', reason=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__': raise SystemExit(main())
