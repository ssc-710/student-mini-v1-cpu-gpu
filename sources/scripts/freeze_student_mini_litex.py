"""Resolve the actually installed LiteX closure, including Git submodules.

Source checkout hashes and installed-file agreement are distinct from clean
environment qualification. No software archives belong in the student ZIPs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

ROOTS=['litex','migen','litedram','liteeth','pythondata-cpu-vexriscv',
       'pythondata-software-picolibc','pythondata-software-compiler-rt','pythondata-misc-tapcfg']


def git(path,*args):
    result=subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True,timeout=180)
    if result.returncode:raise ValueError('source probe failed: '+' '.join(args))
    return result.stdout.strip()


def public_url(url):
    value=url.removesuffix('.git')
    if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):
        raise ValueError('source must have a credential-free official HTTPS repository URL')
    return value


def active_requirements(requirements):
    result=[]
    for text in requirements or []:
        requirement=Requirement(text)
        if not requirement.marker or requirement.marker.evaluate({'extra':''}):result.append(requirement)
    return result


def source_record(path):
    revision=git(path,'rev-parse','HEAD')
    if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('unresolved source revision')
    raw_clean=not git(path,'status','--porcelain','--untracked-files=no','--ignore-submodules=dirty')
    # Windows checks out CRLF; WSL's default Git settings otherwise report every
    # text file as edited. Override only this read-only probe, never repository
    # configuration or working files. Byte hashes below remain unnormalized.
    # A raw status can retain cached stat/EOL flags. Diff against HEAD checks
    # content (including staged changes), not that cached flag. Nested working
    # trees are checked separately below instead of repeatedly recursing.
    if git(path,'-c','core.autocrlf=true','-c','core.filemode=false','diff','--name-only','HEAD','--ignore-submodules=dirty'):
        raise ValueError('source checkout differs from commit after explicit EOL policy')
    url=public_url(git(path,'remote','get-url','origin'))
    # Git status recursively flags modified submodules. Record each actual pin,
    # not just a parent archive that omits the nested Picolibc/VexRiscv sources.
    children=[]
    for line in git(path,'submodule','status','--recursive').splitlines():
        match=re.fullmatch(r' ?([a-f0-9]{40}) ([^ ]+)(?: \(.*\))?',line)
        if not match:raise ValueError('uninitialized/modified/ambiguous submodule: '+line)
        commit,relative=match.groups();nested=(path/relative).resolve()
        if not nested.is_relative_to(path.resolve()):raise ValueError('submodule outside checkout')
        actual=git(nested,'rev-parse','HEAD')
        if actual!=commit:raise ValueError('submodule HEAD differs')
        if git(nested,'-c','core.autocrlf=true','-c','core.filemode=false','diff','--name-only','HEAD','--ignore-submodules=dirty'):
            raise ValueError('submodule content differs from commit')
        child_url=public_url(git(nested,'remote','get-url','origin'))
        children.append(dict(path=relative,commit=commit,url=child_url,
            exact_source_url=child_url+'/tree/'+commit))
    files={}
    for base,relative in [(path,''),*((path/c['path'],c['path']+'/') for c in children)]:
        listing=subprocess.run(['git','-C',str(base),'ls-files','-z'],capture_output=True,check=True,timeout=30).stdout
        for raw in listing.split(b'\0'):
            if not raw:continue
            name=raw.decode();candidate=base/name
            if candidate.is_file():files[relative+name]=dict(sha256=sha(candidate),bytes=candidate.stat().st_size)
    if not files:raise ValueError('empty Git source manifest')
    return dict(url=url,commit=revision,exact_source_url=url+'/tree/'+revision,submodules=children,
        source_files=files,source_tree_sha256=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
        source_bytes=sum(r['bytes'] for r in files.values()),canonical_git_content_verified=True,
        checkout_policy=dict(raw_status_clean=raw_clean,core_autocrlf=True,core_filemode=False,
            working_bytes_hashed_without_normalization=True,upstream_byte_identity_not_claimed=True))


def installed_agreement(dist,source):
    compared=[];different=[]
    for file in dist.files or []:
        name=str(file)
        if '.dist-info/' in name or '.egg-info/' in name or '__pycache__/' in name or name.startswith('../'):continue
        original=source/name
        if original.is_file():
            installed=Path(dist.locate_file(file))
            if not installed.is_file() or sha(installed)!=sha(original):different.append(name)
            else:compared.append(name)
    if not compared or different:raise ValueError('installed/source mismatch: '+str(different[:8]))
    return dict(matching_files=len(compared),verified_file_list_sha256=hashlib.sha256('\n'.join(sorted(compared)).encode()).hexdigest())


def pypi_record(name,dist,out):
    url=f'https://pypi.org/pypi/{name}/{dist.version}/json'
    with urllib.request.urlopen(url,timeout=30) as response:raw=response.read()
    data=json.loads(raw);tags={tag:i for i,tag in enumerate(sys_tags())};candidates=[]
    for artifact in data['urls']:
        if artifact['yanked']:continue
        if artifact['filename'].endswith('.whl'):
            compatible=parse_wheel_filename(artifact['filename'])[3]&tags.keys()
            if compatible:candidates.append((min(tags[t] for t in compatible),artifact))
        elif artifact['packagetype']=='sdist':candidates.append((10**9,artifact))
    if not candidates:raise ValueError('no compatible pinned artifact for '+name)
    artifact=min(candidates,key=lambda x:x[0])[1];target=out/'downloaded-artifacts'/artifact['filename']
    with urllib.request.urlopen(artifact['url'],timeout=60) as response,target.open('xb') as output:
        while block:=response.read(1024*1024):output.write(block)
    if sha(target)!=artifact['digests']['sha256'] or target.stat().st_size!=artifact['size']:
        raise ValueError('download SHA/size mismatch')
    return dict(download_url=artifact['url'],filename=artifact['filename'],sha256=sha(target),
        download_bytes=target.stat().st_size,official_page=f'https://pypi.org/project/{name}/{dist.version}/',
        metadata_sha256=hashlib.sha256(raw).hexdigest(),archive_verified=True,
        license=data['info'].get('license_expression') or data['info'].get('license'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'downloaded-artifacts').mkdir();pending=list(ROOTS);rows={};bindings={str(Path(__file__)):sha(Path(__file__))}
    report=dict(status='HOLD',clean_environment_qualified=False,roots=ROOTS,created_at=datetime.now(timezone.utc).isoformat(),
        bindings=bindings,scope='CPU functionality dependencies for A and B; no Vortex/CUDA required by route A',packages=[])
    try:
        while pending:
            name=canonicalize_name(pending.pop())
            if name in rows:continue
            dist=metadata.distribution(name);requires=active_requirements(dist.requires)
            for requirement in requires:
                if metadata.version(requirement.name) not in requirement.specifier:raise ValueError('dependency conflict: '+str(requirement))
                pending.append(requirement.name)
            row=dict(name=name,version=dist.version,dependencies=[str(r) for r in requires],
                installed_bytes=sum(Path(dist.locate_file(p)).stat().st_size for p in dist.files or [] if Path(dist.locate_file(p)).is_file()))
            direct=json.loads(dist.read_text('direct_url.json') or '{}')
            if direct:
                parsed=urllib.parse.urlparse(direct.get('url',''))
                if parsed.scheme!='file' or parsed.netloc:raise ValueError('unresolved direct dependency')
                source=Path(urllib.parse.unquote(parsed.path)).resolve()
                if not source.is_relative_to(ROOT/'third_party/src'):raise ValueError('unexpected source checkout')
                row.update(kind='git-source',**source_record(source),installed_agreement=installed_agreement(dist,source))
                licenses=[p for p in source.iterdir() if p.is_file() and p.name.lower().startswith(('license','copying'))]
                row['license_files']={p.name:sha(p) for p in licenses}
                row['license_note']='Exact upstream license files pinned; subcomponent licenses remain in source manifest'
                bindings.update({str(source/p):record['sha256'] for p,record in row['source_files'].items()})
            else:row.update(kind='pypi',**pypi_record(name,dist,out))
            rows[name]=row;print(json.dumps(dict(name=name,version=dist.version,kind=row['kind'])),flush=True)
        report.update(status='SOURCE_CLOSURE_OBSERVED_NOT_ENVIRONMENT_QUALIFIED',
            reason='Actual installed versions and clean source/submodule closure resolved; fresh venv/full CPU build still required')
        requirements=''.join(f"{r['name']}=={r['version']} --hash=sha256:{r['sha256']}\n" for r in sorted(rows.values(),key=lambda x:x['name']) if r['kind']=='pypi')
        (out/'runtime-requirements-hashed.txt').write_text(requirements)
    except Exception as error:report['reason']=f'{type(error).__name__}: {error}'
    report['packages']=list(rows.values())
    (out/'litex-lock.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(out/'litex-lock.json'),status=report['status'],reason=report['reason'])),flush=True)
    return 1 if report['status']=='HOLD' else 0


if __name__=='__main__':raise SystemExit(main())
