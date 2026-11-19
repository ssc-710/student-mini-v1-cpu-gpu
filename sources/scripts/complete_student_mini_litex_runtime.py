"""Resolve public-archive dependencies omitted by distro Python metadata.

Ubuntu requests metadata may omit Requires-Dist and use chardet instead of the
upstream wheel's charset-normalizer. Never mistake an observed distro install
for an already qualified PyPI reconstruction. This is preparation, not PASS.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.freeze_student_mini_litex import active_requirements,pypi_record
from packaging.utils import canonicalize_name

# Explicit compatible reconstruction choice, not an observed installed version
# and not a floating latest dependency. Only a fresh environment can qualify it.
RECONSTRUCTION_PINS={'charset-normalizer':'3.3.2'}


def validate_closure(rows):
    by_name={canonicalize_name(row['name']):row for row in rows}
    if len(by_name)!=len(rows):raise ValueError('duplicate package')
    for row in rows:
        for requirement in active_requirements(row['dependencies']):
            child=by_name.get(canonicalize_name(requirement.name))
            if child is None:raise ValueError('missing transitive dependency: '+str(requirement))
            if child['version'] not in requirement.specifier:raise ValueError('dependency version conflict: '+str(requirement))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-lock',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();parent_path=args.source_lock.resolve();parent=json.loads(parent_path.read_text())
    if parent.get('status')!='SOURCE_CLOSURE_OBSERVED_NOT_ENVIRONMENT_QUALIFIED':raise ValueError('unresolved source closure')
    for path,digest in parent['bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('source lock stale: '+path)
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'downloaded-artifacts').mkdir();(out/'metadata').mkdir()
    rows={canonicalize_name(row['name']):dict(row) for row in parent['packages']}
    pending=[name for name,row in rows.items() if row['kind']=='pypi'];done=set()
    report=dict(status='HOLD',clean_environment_qualified=False,source_lock_sha256=sha(parent_path),
        bindings={str(p):sha(p) for p in (parent_path,Path(__file__),ROOT/'scripts/freeze_student_mini_litex.py')},
        reconstruction_policy='Public archive dependency closure differs from Ubuntu dist-packages metadata; fresh venv and actual CPU build required',packages=[])
    try:
        while pending:
            name=pending.pop()
            if name in done:continue
            row=rows[name];url=f'https://pypi.org/pypi/{name}/{row["version"]}/json'
            with urllib.request.urlopen(url,timeout=30) as response:raw=response.read()
            info=json.loads(raw);(out/'metadata'/f'{name}.json').write_bytes(raw)
            row['observed_installed_dependencies']=row['dependencies']
            row['dependencies']=[str(r) for r in active_requirements(info['info'].get('requires_dist'))]
            row['published_metadata_sha256']=hashlib.sha256(raw).hexdigest()
            row['public_archive_equals_installed_distro_not_claimed']=True
            source=parent_path.parent/'downloaded-artifacts'/row['filename']
            if source.is_file():
                if sha(source)!=row['sha256']:raise ValueError('parent archive changed')
                shutil.copyfile(source,out/'downloaded-artifacts'/row['filename'])
            elif not (out/'downloaded-artifacts'/row['filename']).is_file():raise ValueError('missing archive')
            for requirement in active_requirements(row['dependencies']):
                dependency=canonicalize_name(requirement.name)
                if dependency not in rows:
                    try:version=metadata.version(dependency);observed=True
                    except metadata.PackageNotFoundError:
                        if dependency not in RECONSTRUCTION_PINS:raise ValueError('unresolved unobserved dependency: '+dependency)
                        version=RECONSTRUCTION_PINS[dependency];observed=False
                    if version not in requirement.specifier:raise ValueError('observed/pinned dependency conflict')
                    package=pypi_record(dependency,SimpleNamespace(version=version),out)
                    rows[dependency]=dict(name=dependency,version=version,kind='pypi',dependencies=[],
                        observed_installed_version=observed,installed_bytes=None,**package)
                if rows[dependency]['kind']=='pypi':pending.append(dependency)
            done.add(name);print(json.dumps(dict(name=name,dependencies=row['dependencies'])),flush=True)
        validate_closure(list(rows.values()))
        (out/'runtime-requirements-hashed.txt').write_text(''.join(f"{r['name']}=={r['version']} --hash=sha256:{r['sha256']}\n" for _,r in sorted(rows.items()) if r['kind']=='pypi'))
        report.update(status='ARCHIVE_DEPENDENCIES_RESOLVED_NOT_ENVIRONMENT_QUALIFIED',
            reason='Public runtime transitive dependencies resolved; source build and clean venv tests not yet run')
    except Exception as error:report['reason']=f'{type(error).__name__}: {error}'
    report['packages']=list(rows.values())
    report['artifacts']={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'runtime-lock.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(out/'runtime-lock.json'),status=report['status'],reason=report['reason'])),flush=True)
    return 1 if report['status']=='HOLD' else 0


if __name__=='__main__':raise SystemExit(main())
