"""Snapshot actual executable/runtime bytes, not just tool launcher scripts.

Read-only observation. Does not retroactively attest earlier invocations and
does not claim a reproducible source build or authorize release.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest_file(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('runtime file changed during snapshot: '+str(path))
    return dict(sha256=digest.hexdigest(), bytes=after.st_size)


def linked_files(text):
    if 'not found' in text:
        raise ValueError('unresolved runtime library')
    result = []
    for line in text.splitlines():
        match = re.match(r'\s*(?:\S+\s+=>\s+)?(/\S+)\s+\(', line)
        if match:
            result.append(Path(match[1]))
    return sorted(set(result))


def tree_files(root):
    paths = []
    for name in ('bin', 'lib', 'libexec', 'share', 'license', 'VERSION', 'environment'):
        base = root/name
        if not base.exists():
            raise ValueError('runtime prefix incomplete: '+str(base))
        if base.is_file():
            paths.append(base)
        else:
            paths.extend(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return sorted(set(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('snapshot already exists')
    started_at = datetime.now(timezone.utc).isoformat()
    suite = Path('/home/soclab/tools/oss-cad-suite')
    files = tree_files(suite)
    # Wrapper and real executable are both required. The suite loader and its
    # private libraries are captured by the tree, not host-default ldd output.
    tools = {
        'yosys': [suite/'bin/yosys', suite/'libexec/yosys'],
        'openroad': [Path('/home/soclab/.local/bin/openroad')],
        'cpu-verilator': [Path('/home/soclab/tools/verilator-5.040/bin')/n for n in ('verilator', 'verilator_bin')],
        'gpu-verilator': [Path('/mnt/d/open-soc-ai-labs-vortex-tools/verilator/bin')/n for n in ('verilator', 'verilator_bin')],
    }
    library_probes = {}
    for role, paths in tools.items():
        for path in paths:
            files.append(path)
            with path.open('rb') as handle:
                elf = handle.read(4) == b'\x7fELF'
            if elf and role != 'yosys':
                run = subprocess.run(['ldd', str(path)], capture_output=True, text=True, timeout=30)
                if run.returncode:
                    raise ValueError('runtime dependency probe failed: '+str(path))
                library_probes[str(path)] = run.stdout
                files.extend(linked_files(run.stdout))
    entries = {}
    for path in sorted(set(files)):
        entries[str(path)] = dict(digest_file(path), resolved=str(path.resolve()),
                                  symlink_target=str(path.readlink()) if path.is_symlink() else None)
    required = [suite/'lib/ld-linux-x86-64.so.2', suite/'libexec/yosys']
    if any(str(path) not in entries for path in required):
        raise ValueError('suite executable or private loader missing')
    payload = dict(schema='student-mini-tool-runtime-observation-v1',
        status='OBSERVED_NOT_RELEASE_QUALIFIED', runtime_snapshot_complete=True,
        prior_invocations_attested=False, reproducible_source_build=False,
        started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(),
        producer_sha256=digest_file(Path(__file__))['sha256'],
        suite_version=(suite/'VERSION').read_text().strip(),
        tools={role: [str(p) for p in paths] for role, paths in tools.items()},
        files=entries, dependency_probes=library_probes,
        logical_file_bytes=sum(row['bytes'] for row in entries.values()),
        limitations=['Snapshot binds current bytes, not historical invocations.',
            'Verilator include/share trees, external compiler and GPU libraries remain separately required.',
            'Source archives, patches, licenses and fresh reconstruction qualification remain mandatory.',
            'Logical file bytes may count symlink targets more than once; not installation-space measurement.'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(payload, handle, indent=2)
    print(json.dumps(dict(path=str(args.output), sha256=digest_file(args.output)['sha256'],
        files=len(entries), status=payload['status'])), flush=True)


if __name__ == '__main__':
    main()
