"""Verify local OpenROAD source exports and the exact install-time RPATH change.

Read-only source audit; only a new private executable copy is modified by CMake.
Does not execute EDA, rebuild a tool, or grant whole-environment qualification.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

COMMIT='90e29809c3d41f5ad289576e4c0c05b80c700bcd'


def file_digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        while block:=handle.read(1024*1024):digest.update(block)
    return digest.hexdigest()


def install_rpaths(text):
    blocks=re.findall(r'file\(RPATH_CHANGE\s+FILE\s+"\$ENV\{DESTDIR\}\$\{CMAKE_INSTALL_PREFIX\}/bin/openroad"\s+OLD_RPATH\s+"([^"\n]+)"\s+NEW_RPATH\s+"([^"\n]+)"\s*\)',text)
    if len(blocks)!=1:raise ValueError('ambiguous OpenROAD RPATH installation rule')
    old,new=blocks[0]
    if old!=new+':' or any(c in old for c in (';','\n','\r','${','"')):
        raise ValueError('unexpected install transform; only trailing padding removal audited')
    return old,new


def parse_tree(raw):
    result=[]
    for entry in raw.split(b'\0'):
        if not entry:continue
        identity,name=entry.split(b'\t',1)
        mode,kind,oid=identity.decode('ascii').split()
        name=name.decode('utf-8')
        if name.startswith('/') or any(p in ('','.','..') for p in name.split('/')):
            raise ValueError('unsafe tracked source path')
        if kind not in ('blob','commit') or not re.fullmatch('[0-9a-f]{40}',oid):
            raise ValueError('unsupported source tree entry')
        result.append(dict(mode=mode,kind=kind,git_blob_or_commit=oid,path=name))
    return result


def blob_identity(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()


def symlink_content(path):
    # Path.readlink() returns a Path and normalizes a meaningful trailing slash.
    return os.fsencode(os.readlink(path))


def export_classification(original,actual,archive_content=None):
    if original==actual:return 'MATCH'
    if b'\r\n' in original and original.replace(b'\r\n',b'\n')==actual:
        return 'MATCH_DECLARED_CRLF_TO_LF_EXPORT'
    if archive_content is not None and archive_content==actual:
        return 'MATCH_GIT_ARCHIVE_EXPORT'
    return 'DIFFERENT_BYTES'


def source_inventory(repository,source,commit,prefix='',depth=0):
    if depth>10:raise ValueError('unexpected recursive submodule depth')
    command=['git','-C',str(repository),'ls-tree','-rz','--full-tree',commit]
    raw=subprocess.check_output(command,timeout=60)
    rows=[];repositories=[dict(path=prefix or '.',commit=commit)]
    for entry in parse_tree(raw):
        name=entry['path'];relative=prefix+name;path=source/name
        if entry['kind']=='commit':
            subrows,subrepos=source_inventory(repository/name,path,entry['git_blob_or_commit'],relative+'/',depth+1)
            rows.extend(subrows);repositories.extend(subrepos);continue
        row=dict(entry,path=relative)
        if entry['mode']=='120000':
            if path.is_symlink():content=symlink_content(path)
            else:row['status']='MISSING_SYMLINK';rows.append(row);continue
        elif path.is_file() and not path.is_symlink():content=path.read_bytes()
        else:row['status']='MISSING_FILE';rows.append(row);continue
        row.update(bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),
            status='MATCH' if blob_identity(content)==entry['git_blob_or_commit'] else 'DIFFERENT_BYTES')
        if row['status']=='DIFFERENT_BYTES' and entry['mode']!='120000':
            original=subprocess.check_output(['git','-C',str(repository),'cat-file','blob',entry['git_blob_or_commit']],timeout=30)
            row['status']=export_classification(original,content)
            if row['status']=='DIFFERENT_BYTES':
                raw_archive=subprocess.check_output(['git','-C',str(repository),'archive','--format=tar',commit,name],timeout=30)
                with tarfile.open(fileobj=io.BytesIO(raw_archive),mode='r:') as archive:
                    members=[member for member in archive.getmembers() if member.name==name and member.isfile()]
                    if len(members)==1:
                        archive_content=archive.extractfile(members[0]).read()
                        row['status']=export_classification(original,content,archive_content)
        rows.append(row)
    return rows,repositories


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    work=args.output_dir.resolve();work.mkdir(parents=True,exist_ok=False)
    repo=Path('/home/soclab/src/OpenROAD-90e29809')
    source=Path('/home/soclab/src/OpenROAD-clean-90e29809')
    built=source/'build/bin/openroad';installed=Path('/home/soclab/.local/bin/openroad')
    install_script=source/'build/src/cmake_install.cmake';cache=source/'build/CMakeCache.txt'
    cmake=Path(shutil.which('cmake'));paths=(built,installed,install_script,cache,Path(__file__),cmake)
    bindings={str(p):file_digest(p) for p in paths}
    old,new=install_rpaths(install_script.read_text())
    copied=work/'openroad-install-replay'
    shutil.copy2(built,copied)
    script=work/'replay-install.cmake'
    script.write_text(f'file(RPATH_CHANGE FILE "{copied}" OLD_RPATH "{old}" NEW_RPATH "{new}")\n')
    with (work/'install-replay.log').open('x') as log:
        code=subprocess.run([str(cmake),'-P',str(script)],stdout=log,stderr=subprocess.STDOUT,timeout=60).returncode
    if code:raise ValueError('CMake install replay failed')
    binary_matches=file_digest(copied)==bindings[str(installed)]
    print(json.dumps(dict(stage='INSTALL_TRANSFORM_CHECKED',installed_binary_matches=binary_matches)),flush=True)
    rows,repositories=source_inventory(repo,source,COMMIT)
    explained={'MATCH_DECLARED_CRLF_TO_LF_EXPORT','MATCH_GIT_ARCHIVE_EXPORT'}
    differences=[row for row in rows if row['status'] not in {'MATCH',*explained}]
    transforms=[row for row in rows if row['status'] in explained]
    if any(file_digest(Path(p))!=value for p,value in bindings.items()):raise ValueError('tool/build evidence changed during audit')
    result=dict(schema='student-mini-openroad-source-audit-v1',
        status='SOURCE_AND_INSTALL_STAGE_PASS' if binary_matches and not differences else 'HOLD_SOURCE_OR_INSTALL_DIFFERS',
        created_at=datetime.now(timezone.utc).isoformat(),bindings=bindings,
        install_transform=dict(old_rpath=old,new_rpath=new,matched_installed_binary=binary_matches,
            replay_sha256=file_digest(copied)),
        source_commit=COMMIT,source_repositories=repositories,files=rows,differences=differences,
        declared_export_transforms=transforms,byte_identical_git_checkout=not transforms and not differences,
        complete_student_environment=False,reproducible_build=False,prior_invocations_attested=False,
        limitations=['Tracked source export and install transformation only; generated build dependencies require their own lock.',
            'No source archive download or clean compiler/linker reconstruction was performed.',
            'No existing source, tool executable, physical input or result was modified.'])
    output=work/'audit.json';output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),sha256=file_digest(output),status=result['status'],files=len(rows),differences=len(differences))),flush=True)
    return 0 if result['status']=='SOURCE_AND_INSTALL_STAGE_PASS' else 2


if __name__=='__main__':raise SystemExit(main())
