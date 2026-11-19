"""Read-only exact runtime/archive comparison; never extracts downloaded files."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_student_mini_oss_archive import digest,check_archive


def split_member(name):
    while name.startswith('./'):name=name[2:]
    parts=name.rstrip('/').split('/')
    if any(p in ('','.','..') for p in parts) or '\\' in name:
        raise ValueError('unsafe archive path')
    return parts[0],'/'.join(parts[1:])


def validate_lock(lock):
    if not re.fullmatch('[a-f0-9]{64}',lock.get('sha256','')) or type(lock.get('bytes')) is not int or lock['bytes']<=0:
        raise ValueError('pinned archive SHA and size required')
    if not lock.get('download_url','').startswith('https://github.com/'):
        raise ValueError('explicit upstream release URL required')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('lock','archive','installed-root','observation','output-dir'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    lock=json.loads(args.lock.read_text());validate_lock(lock)
    check_archive(args.archive,lock['sha256'],lock['bytes'])
    work=args.output_dir.resolve();work.mkdir(parents=True,exist_ok=False)
    installed=args.installed_root.resolve();observation=json.loads(args.observation.read_text())
    rows=[];seen=set();prefixes=set()
    with tarfile.open(args.archive,mode='r|gz') as archive:
        for member in archive:
            prefix,name=split_member(member.name);prefixes.add(prefix)
            if len(prefixes)!=1:raise ValueError('multiple archive roots')
            if not name or member.isdir():continue
            if name in seen:raise ValueError('duplicate archive member')
            seen.add(name);path=installed/name
            row=dict(path=name,bytes=member.size)
            if member.isfile():
                with archive.extractfile(member) as handle:expected,size=digest(handle)
                if size!=member.size:raise ValueError('truncated archive member')
                row.update(kind='file',sha256=expected)
                if path.is_file() and not path.is_symlink():
                    with path.open('rb') as handle:actual=digest(handle)
                    row['status']='MATCH' if actual==(expected,size) else 'DIFFERENT_BYTES'
                else:row['status']='MISSING_OR_WRONG_TYPE'
            elif member.issym():
                row.update(kind='symlink',target=member.linkname,
                    status='MATCH' if path.is_symlink() and os.readlink(path)==member.linkname else 'DIFFERENT_LINK')
            else:row.update(kind='other',status='UNSUPPORTED_ARCHIVE_ENTRY')
            rows.append(row)
    earlier=[]
    for name,record in observation['files'].items():
        path=Path(name)
        if not path.is_relative_to(installed):continue
        relative=path.relative_to(installed).as_posix()
        if relative not in seen:raise ValueError('prior dependency not present in archive')
        with path.open('rb') as handle:current,size=digest(handle)
        earlier.append(dict(path=relative,status='MATCH' if (current,size)==(record['sha256'],record['bytes']) else 'DIFFERENT_BYTES'))
    if not earlier:raise ValueError('no earlier observed runtime dependency matches selected installation')
    differences=[r for r in [*rows,*earlier] if r['status']!='MATCH']
    report=dict(schema='student-mini-runtime-archive-audit-v1',
        status='RUNTIME_ARCHIVE_IDENTITY_STAGE_PASS' if not differences else 'HOLD_RUNTIME_ARCHIVE_DIFFERS',
        created_at=datetime.now(timezone.utc).isoformat(),archive=lock,files=rows,prior_snapshot_files=earlier,differences=differences,
        bindings={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.lock,args.observation,Path(__file__),ROOT/'scripts/audit_student_mini_oss_archive.py')},
        expanded_regular_bytes=sum(r['bytes'] for r in rows if r['kind']=='file'),
        complete_student_environment=False,prior_invocations_attested=False,
        scope='Installed runtime files match pinned archive and earlier observation; not historical execution or complete toolchain qualification')
    output=work/'audit.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),status=report['status'],
        files=len(rows),prior_dependencies=len(earlier),differences=len(differences))),flush=True)
    return 0 if not differences else 2


if __name__=='__main__':raise SystemExit(main())
