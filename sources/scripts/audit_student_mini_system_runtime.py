"""Bind observed host ELF dependencies to exact Ubuntu binary packages.

Downloads only into a new audit directory, never installs or extracts packages.
This qualifies the selected ELF runtime files, not the complete student image.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.collect_student_mini_tool_runtime import linked_files
from scripts.audit_student_mini_oss_archive import digest


def parse_fields(text):
    result = {}; key = None
    for line in text.splitlines():
        if not line: break
        if line.startswith((' ', '\t')):
            if key is None: raise ValueError('orphan metadata continuation')
            result[key] += '\n'+line[1:]
        else:
            key, separator, value = line.partition(':')
            if not separator or key in result or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]*', key):
                raise ValueError('ambiguous package metadata')
            result[key] = value.lstrip(' \t')
    return result


def canonical_member(name):
    while name.startswith('./'): name = name[2:]
    if any(part in ('', '.', '..') for part in name.split('/')) or name.startswith('/'):
        raise ValueError('unsafe package member')
    if name.startswith(('lib/', 'lib64/')): name = 'usr/'+name
    return name


def command(args):
    run = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if run.returncode: raise ValueError('package metadata command failed: '+str(args))
    return run.stdout


def package_for(path):
    candidates = [str(path.resolve()), str(path)]
    for candidate in dict.fromkeys(candidates):
        run = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True, timeout=30)
        matches = [line.rsplit(': ', 1)[0] for line in run.stdout.splitlines() if line.endswith(': '+candidate)]
        if run.returncode == 0 and len(set(matches)) == 1: return matches[0]
    raise ValueError('no unique installed package owns '+str(path))


def snapshot_options(work, snapshot):
    if not re.fullmatch(r'20[0-9]{6}T[0-9]{6}Z', snapshot):
        raise ValueError('invalid bounded snapshot identity')
    state = work/'apt-snapshot'; state.mkdir()
    (state/'lists/partial').mkdir(parents=True)
    source = state/'sources.list'
    source.write_text(''.join(f'deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] '
        f'https://snapshot.ubuntu.com/ubuntu/{snapshot}/ {suite} main\n'
        for suite in ('noble', 'noble-updates', 'noble-security')))
    settings = {'Dir::State::lists': str(state/'lists'), 'Dir::Etc::sourcelist': str(source),
        'Dir::Etc::sourceparts': '-', 'Dir::Cache::pkgcache': str(state/'pkgcache.bin'),
        'Dir::Cache::srcpkgcache': str(state/'srcpkgcache.bin'),
        'Acquire::AllowInsecureRepositories': 'false', 'APT::Get::AllowUnauthenticated': 'false',
        'APT::Get::List-Cleanup': 'false', 'Acquire::Languages': 'none'}
    options = [argument for key, value in settings.items() for argument in ('-o', key+'='+value)]
    with (state/'update.log').open('x') as log:
        run = subprocess.run(['apt-get', *options, 'update'], stdout=log, stderr=subprocess.STDOUT, timeout=300)
    if run.returncode: raise ValueError('signed snapshot index acquisition failed')
    return options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observation', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--fallback-snapshot', help='Read-only, private signed index for superseded installed versions')
    args = parser.parse_args()
    work = args.output_dir.resolve(); work.mkdir(parents=True, exist_ok=False)
    observation = json.loads(args.observation.read_text())
    if observation.get('schema') != 'student-mini-tool-runtime-observation-v1': raise ValueError('wrong runtime snapshot')
    selected = sorted({path for probe in observation['dependency_probes'].values() for path in linked_files(probe)
                       if str(path).startswith(('/lib/', '/lib64/', '/usr/lib/'))})
    if not selected: raise ValueError('no system runtime dependencies')
    owners = {}; dependencies = []
    for path in selected:
        record = observation['files'][str(path)]
        if sha(path) != record['sha256']: raise ValueError('runtime file changed since snapshot')
        owner = package_for(path); owners.setdefault(owner, []).append(path)
    packages = []; snapshot = None
    for owner, paths in sorted(owners.items()):
        installed = parse_fields(command(['dpkg-query', '-s', owner]))
        version = installed['Version']; package = installed['Package']
        metadata_text = command(['apt-cache', 'show', owner+'='+version])
        metadata = parse_fields(metadata_text)
        apt_options = []
        if not re.fullmatch('[a-f0-9]{64}', metadata.get('SHA256', '')) and args.fallback_snapshot:
            if snapshot is None: snapshot = snapshot_options(work, args.fallback_snapshot)
            apt_options = snapshot
            metadata_text = command(['apt-cache', *apt_options, 'show', owner+'='+version])
            metadata = parse_fields(metadata_text)
        if (metadata.get('Package'), metadata.get('Version')) != (package, version): raise ValueError('archive version differs')
        if not re.fullmatch('[a-f0-9]{64}', metadata.get('SHA256', '')): raise ValueError('missing authoritative package SHA256')
        lines = command(['apt-get', *apt_options, '--print-uris', 'download', owner+'='+version]).splitlines()
        uris = [shlex.split(line) for line in lines if line.startswith("'")]
        if len(uris) != 1 or len(uris[0]) != 4: raise ValueError('ambiguous archive URI')
        url, filename, size, checksum = uris[0]
        if Path(filename).name != filename or not filename.endswith('.deb'): raise ValueError('unsafe download name')
        if int(size) != int(metadata['Size']): raise ValueError('archive size disagreement')
        if not re.fullmatch(r'https?://(?:(?:archive|security)\.ubuntu\.com/ubuntu/|snapshot\.ubuntu\.com/ubuntu/20[0-9]{6}T[0-9]{6}Z/).*', url):
            raise ValueError('nonofficial Ubuntu archive origin')
        url = re.sub('^http:', 'https:', url)
        archive = work/filename
        subprocess.run(['curl', '--fail', '--location', '--retry', '2', '--silent', '--show-error',
            '--output', str(archive), url], check=True, timeout=180)
        if archive.stat().st_size != int(size) or sha(archive) != metadata['SHA256']:
            raise ValueError('download differs from package index')
        wanted = {canonical_member(str(path.resolve()).lstrip('/')): path for path in paths}
        found = set(); members = []
        proc = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=proc.stdout, mode='r|') as contents:
                for member in contents:
                    if not member.isfile(): continue
                    name = canonical_member(member.name)
                    if name not in wanted: continue
                    if name in found: raise ValueError('duplicate runtime member')
                    found.add(name); path = wanted[name]
                    with contents.extractfile(member) as stream: value, length = digest(stream)
                    expected = observation['files'][str(path)]
                    match = (value, length) == (expected['sha256'], expected['bytes']) and sha(path) == value
                    row = dict(path=name, sha256=value, bytes=length, status='MATCH' if match else 'DIFFERENT_BYTES')
                    members.append(row); dependencies.append(dict(package=package, version=version, **row))
            if proc.wait(timeout=30): raise ValueError('package archive reader failed')
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
            proc.stdout.close(); proc.stderr.close()
        if found != set(wanted): raise ValueError('observed runtime not found in package')
        copyright_path = Path('/usr/share/doc')/package/'copyright'
        packages.append(dict(name=package, version=version, architecture=installed['Architecture'],
            metadata_source='signed-private-snapshot:'+args.fallback_snapshot if apt_options else 'system-package-index',
            download_url=url, archive_sha256=metadata['SHA256'], archive_bytes=int(size),
            installed_kib=int(metadata.get('Installed-Size', '0')), dependencies=metadata.get('Depends', ''),
            pre_dependencies=metadata.get('Pre-Depends', ''), source=metadata.get('Source', package),
            homepage=metadata.get('Homepage'), license_notice=copyright_path.read_text() if copyright_path.is_file() else None,
            matched_runtime_files=members))
        print(json.dumps(dict(package=package, version=version, files=len(members))), flush=True)
    differences = [row for row in dependencies if row['status'] != 'MATCH']
    report = dict(schema='student-mini-system-runtime-packages-v1',
        status='SYSTEM_ELF_RUNTIME_ARCHIVE_STAGE_PASS' if not differences else 'HOLD_RUNTIME_DIFFERS',
        created_at=datetime.now(timezone.utc).isoformat(), packages=packages, runtime_files=dependencies,
        differences=differences, complete_student_environment=False, prior_invocations_attested=False,
        scope='Observed ELF runtime only; complete package dependency resolution and clean-image replay remain',
        bindings={str(p): sha(p) for p in (Path(__file__), args.observation,
            ROOT/'scripts/collect_student_mini_tool_runtime.py', ROOT/'scripts/audit_student_mini_oss_archive.py')})
    if snapshot is not None:
        report['snapshot_index_bindings'] = {p.relative_to(work).as_posix(): sha(p)
            for p in (work/'apt-snapshot').rglob('*') if p.is_file()}
        report['bindings']['/usr/share/keyrings/ubuntu-archive-keyring.gpg'] = sha(Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg'))
    output = work/'audit.json'; output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(path=str(output), sha256=sha(output), status=report['status'],
        packages=len(packages), runtime_files=len(dependencies))), flush=True)
    return 0 if not differences else 2


if __name__ == '__main__': raise SystemExit(main())
