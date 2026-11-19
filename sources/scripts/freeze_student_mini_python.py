"""Resolve the actually exercised Linux Python set to verified public artifacts."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import urllib.request
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name,parse_wheel_filename

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    wheels=args.output/'downloaded-artifacts';wheels.mkdir()
    roots=['numpy','ml-dtypes','pytest','cocotb','cocotb-test','pip','setuptools','wheel']
    pending=list(roots);distributions={};tags={tag:i for i,tag in enumerate(sys_tags())}
    while pending:
        name=canonicalize_name(pending.pop())
        if name in distributions:continue
        dist=metadata.distribution(name);distributions[name]=dist
        for text in dist.requires or []:
            requirement=Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({'extra':''}):continue
            actual=metadata.version(requirement.name)
            if actual not in requirement.specifier:raise ValueError('installed dependency conflict: '+text)
            pending.append(requirement.name)
    rows=[]
    for name,dist in sorted(distributions.items()):
        url=f'https://pypi.org/pypi/{name}/{dist.version}/json'
        with urllib.request.urlopen(url,timeout=30) as response:raw=response.read()
        data=json.loads(raw);candidates=[]
        for artifact in data['urls']:
            if artifact['yanked']:continue
            filename=artifact['filename']
            if filename.endswith('.whl'):
                try:compatible=parse_wheel_filename(filename)[3]&tags.keys()
                except ValueError:continue
                if compatible:candidates.append((min(tags[t] for t in compatible),artifact))
            elif artifact['packagetype']=='sdist':candidates.append((10**9,artifact))
        if not candidates:raise ValueError('no compatible non-yanked public artifact: '+name)
        artifact=min(candidates,key=lambda item:item[0])[1]
        target=wheels/artifact['filename'];digest=hashlib.sha256();size=0
        with urllib.request.urlopen(artifact['url'],timeout=60) as response,target.open('xb') as output:
            while block:=response.read(1024*1024):output.write(block);digest.update(block);size+=len(block)
        if digest.hexdigest()!=artifact['digests']['sha256'] or size!=artifact['size']:raise ValueError('download SHA/size mismatch')
        info=data['info'];installed_bytes=sum(Path(dist.locate_file(p)).stat().st_size for p in dist.files or [] if Path(dist.locate_file(p)).is_file())
        rows.append(dict(name=name,version=dist.version,scope='AB function/RTL tests; excludes LiteX editable sources and teacher training',
                         official_page=f'https://pypi.org/project/{name}/{dist.version}/',metadata_url=url,metadata_sha256=hashlib.sha256(raw).hexdigest(),
                         download_url=artifact['url'],filename=artifact['filename'],sha256=digest.hexdigest(),download_bytes=size,
                         installed_bytes=installed_bytes,license=info.get('license_expression') or info.get('license'),
                         dependencies=dist.requires or [],archive_download_verified=True,clean_environment_tested=False))
        print(json.dumps(dict(name=name,version=dist.version,bytes=size,sha256=digest.hexdigest())),flush=True)
    (args.output/'requirements-hashed.txt').write_text(''.join(f"{r['name']}=={r['version']} --hash=sha256:{r['sha256']}\n" for r in rows))
    result=dict(schema_version=1,status='ARTIFACTS_VERIFIED_ENVIRONMENT_NOT_YET_QUALIFIED',roots=roots,packages=rows,
                includes_software_in_student_package=False,build_isolation_policy='For sdist install pinned pip/setuptools/wheel first, then use --no-build-isolation; validate in a fresh venv before release')
    (args.output/'python-lock.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
