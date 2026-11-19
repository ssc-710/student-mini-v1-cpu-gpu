"""Compare the pinned official OSS CAD archive with an observed installation.

Never extracts or executes downloaded files; never edits the active installation.
Archive identity is not retrospective workload attestation or release approval.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.request

RELEASE='2026-09-22'
NAME='oss-cad-suite-linux-x64-20260922.tgz'
EXPECTED_SHA='8b989606925c642da3ea78d7beda2972106ba66a9cdf507c9ba4c0a4d718d012'
EXPECTED_BYTES=742014227
API='https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/tags/'+RELEASE
URL='https://github.com/YosysHQ/oss-cad-suite-build/releases/download/'+RELEASE+'/'+NAME


def digest(handle):
    value=hashlib.sha256();count=0
    while block:=handle.read(1024*1024):
        value.update(block);count+=len(block)
    return value.hexdigest(),count


def relative_member(name):
    while name.startswith('./'):name=name[2:]
    parts=name.rstrip('/').split('/')
    if parts[0]!='oss-cad-suite' or any(p in ('','.', '..') for p in parts) or '\\' in name:
        raise ValueError('unexpected archive path')
    return '/'.join(parts[1:])


def validate_asset(payload):
    if payload.get('tag_name')!=RELEASE:raise ValueError('release tag differs')
    matches=[a for a in payload['assets'] if a.get('name')==NAME]
    if len(matches)!=1:raise ValueError('missing or duplicate pinned asset')
    asset=matches[0]
    if (asset.get('digest'),asset.get('size'),asset.get('browser_download_url'))!=(
            'sha256:'+EXPECTED_SHA,EXPECTED_BYTES,URL):
        raise ValueError('official asset changed from pinned identity')
    return asset


def compare_row(row, observed):
    if observed is None:return 'NOT_IN_PRIOR_SNAPSHOT'
    if row['kind']=='file':
        return 'MATCH' if (row['sha256'],row['bytes'])==(observed['sha256'],observed['bytes']) else 'DIFFERENT_BYTES'
    if row['kind']=='symlink':
        return 'MATCH' if row['target']==observed.get('symlink_target') else 'DIFFERENT_LINK'
    return 'UNSUPPORTED_ENTRY'


def check_archive(path,expected_sha=EXPECTED_SHA,expected_bytes=EXPECTED_BYTES):
    with path.open('rb') as handle:actual=digest(handle)
    if actual!=(expected_sha,expected_bytes):raise ValueError('download identity differs')
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observation',type=Path,required=True)
    parser.add_argument('--suite-root',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--archive',type=Path,help='Previously downloaded archive; read-only and fully SHA-verified')
    args=parser.parse_args()
    work=args.output_dir.resolve();work.mkdir(parents=True,exist_ok=False)
    observation_raw=args.observation.read_bytes()
    observation=json.loads(observation_raw)
    if observation.get('schema')!='student-mini-tool-runtime-observation-v1':
        raise ValueError('unexpected runtime snapshot schema')
    request=urllib.request.Request(API,headers={'User-Agent':'student-mini-source-audit'})
    with urllib.request.urlopen(request,timeout=60) as response:metadata=response.read()
    asset=validate_asset(json.loads(metadata))
    (work/'official-release.json').write_bytes(metadata)
    archive=args.archive.resolve() if args.archive else work/NAME
    if not args.archive:
        print(json.dumps(dict(stage='DOWNLOADING_PINNED_TOOL_ARCHIVE',bytes=EXPECTED_BYTES,output=str(work))),flush=True)
        with urllib.request.urlopen(URL,timeout=60) as response,archive.open('xb') as output:
            count=0
            while block:=response.read(1024*1024):
                count+=len(block)
                if count>EXPECTED_BYTES:raise ValueError('archive exceeds pinned size')
                output.write(block)
    check_archive(archive)
    print(json.dumps(dict(stage='COMPARING_ARCHIVE_MEMBERS',sha256=EXPECTED_SHA)),flush=True)
    rows=[];seen=set();suite=str(args.suite_root).rstrip('/')
    # Streaming mode avoids retaining tar payloads or an extracted software tree.
    with tarfile.open(archive,mode='r|gz') as source:
        for member in source:
            name=relative_member(member.name)
            if not name or member.isdir():continue
            if name in seen:raise ValueError('duplicate archive member')
            seen.add(name)
            if member.isfile():
                with source.extractfile(member) as handle:sha,size=digest(handle)
                row=dict(path=name,kind='file',sha256=sha,bytes=size)
                if size!=member.size:raise ValueError('truncated archive member')
            elif member.issym():
                row=dict(path=name,kind='symlink',target=member.linkname)
            else:
                row=dict(path=name,kind='other',target=member.linkname)
            row['comparison']=compare_row(row,observation['files'].get(suite+'/'+name))
            rows.append(row)
    by_name={r['path']:r for r in rows}
    missing=[name for name in observation['files'] if name.startswith(suite+'/') and name[len(suite)+1:] not in by_name]
    differences=[r for r in rows if r['comparison'] in ('DIFFERENT_BYTES','DIFFERENT_LINK','UNSUPPORTED_ENTRY')]
    report=dict(schema='student-mini-official-archive-audit-v1',
        status='ARCHIVE_IDENTITY_STAGE_PASS' if not missing and not differences else 'HOLD_INSTALLED_ARCHIVE_DIFFERS',
        formal_baseline=False,release_complete=False,prior_invocations_attested=False,
        observed_installation_unchanged=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        observation_sha256=hashlib.sha256(observation_raw).hexdigest(),
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        archive=dict(url=URL,sha256=EXPECTED_SHA,bytes=EXPECTED_BYTES,release=RELEASE),
        official_metadata_sha256=hashlib.sha256(metadata).hexdigest(),
        files=rows,missing_observed_paths=missing,differences=differences,
        scope='Pinned archive compared to earlier byte snapshot; no historical execution attestation, source rebuild, or whole environment qualification')
    output=work/'audit.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),status=report['status'],
        members=len(rows),differences=len(differences),missing=len(missing))),flush=True)
    return 0 if not missing and not differences else 2


if __name__=='__main__':raise SystemExit(main())
