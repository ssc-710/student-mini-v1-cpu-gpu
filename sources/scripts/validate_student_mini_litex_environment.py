"""Reconstruct LiteX offline in a fresh venv; never mutate installed tools.

This verifies package installation/imports and selected generator regressions,
not a full CPU baseline, physical implementation or Nano session.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import venv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.complete_student_mini_litex_runtime import validate_closure


def merge_versions(*groups):
    rows={}
    for group in groups:
        for row in group:
            if row['name'] in rows and row['version']!=rows[row['name']]['version']:
                raise ValueError('conflicting bootstrap/runtime package: '+row['name'])
            rows[row['name']]=row
    return rows


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-lock',type=Path,required=True)
    parser.add_argument('--python-lock',type=Path,required=True)
    args=parser.parse_args();runtime_path=args.runtime_lock.resolve();python_path=args.python_lock.resolve()
    runtime=json.loads(runtime_path.read_text());python=json.loads(python_path.read_text())
    if runtime['status']!='ARCHIVE_DEPENDENCIES_RESOLVED_NOT_ENVIRONMENT_QUALIFIED':raise ValueError('runtime lock incomplete')
    validate_closure(runtime['packages']);merge_versions(runtime['packages'],python['packages'])
    source_lock=next(Path(p) for p in runtime['bindings'] if Path(p).name=='litex-lock.json')
    source=json.loads(source_lock.read_text())
    bindings=dict(runtime['bindings']);bindings.update(source['bindings'])
    paths=[runtime_path,python_path,Path(__file__),ROOT/'scripts/complete_student_mini_litex_runtime.py']
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/litex-environment'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',complete_student_environment=False,full_cpu_replay=False,
        scope='Isolated Python/LiteX source reconstruction and generator smoke only',bindings=bindings,checks=[])
    started=time.monotonic()
    def verify():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('environment input changed')
    def execute(name,command):
        with (work/(name+'.log')).open('x') as log:
            code=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900).returncode
        result['checks'].append(dict(name=name,exit_code=code,log=name+'.log',sha256=sha(work/(name+'.log'))))
        print(json.dumps(result['checks'][-1]),flush=True)
        if code:raise RuntimeError('isolated environment check failed: '+name)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify()
            archives=work/'archives';archives.mkdir();archive_paths={}
            for lockfile,packages in ((python_path,python['packages']),(runtime_path,[r for r in runtime['packages'] if r['kind']=='pypi'])):
                for row in packages:
                    original=lockfile.parent/'downloaded-artifacts'/row['filename']
                    if sha(original)!=row['sha256']:raise ValueError('install archive differs')
                    target=archives/row['filename']
                    if target.exists() and sha(target)!=row['sha256']:raise ValueError('colliding archive filename')
                    if not target.exists():shutil.copyfile(original,target)
                    archive_paths[row['name']]=target
            environment=work/'venv';venv.EnvBuilder(with_pip=True,symlinks=False).create(environment)
            executable=environment/'bin/python'
            env=dict(os.environ,PYTHONNOUSERSITE='1',PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',
                     MAKEFLAGS='-j2',CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='')
            env.pop('PYTHONPATH',None)
            execute('bootstrap',[str(executable),'-m','pip','install','--no-index','--no-deps',*[str(archive_paths[n]) for n in ('pip','setuptools','wheel')]])
            merged=merge_versions(python['packages'],[r for r in runtime['packages'] if r['kind']=='pypi'])
            requirements=work/'requirements-hashed.txt'
            requirements.write_text(''.join(f"{n}=={r['version']} --hash=sha256:{r['sha256']}\n" for n,r in sorted(merged.items())))
            # Source projects installed next; --no-deps prevents a premature
            # search for LiteX while installing the LiteICLink sdist offline.
            execute('runtime',[str(executable),'-m','pip','install','--no-index','--no-deps','--no-build-isolation',
                '--no-cache-dir','--require-hashes','--find-links',str(archives),'-r',str(requirements)])
            for row in runtime['packages']:
                if row['kind']!='git-source':continue
                source_dir=ROOT/'third_party/src'/row['name'].replace('compiler-rt','compiler_rt')
                # All paths come from the verified source manifest. Copy only
                # tracked source/submodule content, never .git/build/install state.
                target=work/'sources'/row['name'];target.mkdir(parents=True)
                for name,record in row['source_files'].items():
                    path=source_dir/name
                    if sha(path)!=record['sha256']:raise ValueError('Git source changed before installation')
                    destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(path,destination)
                execute('source-'+row['name'],[str(executable),'-m','pip','install','--no-index','--no-deps','--no-build-isolation','--no-cache-dir',str(target)])
            execute('pip-check',[str(executable),'-m','pip','check'])
            execute('imports',[str(executable),'-c',
                'import litex,migen,litedram,liteeth,liteiclink,requests; import pythondata_cpu_vexriscv,pythondata_software_picolibc,pythondata_software_compiler_rt,pythondata_misc_tapcfg; from integration.litex.soc import build_soc; print("STUDENT_LITEX_IMPORTS_PASS")'])
            execute('generator-tests',[str(executable),'-m','pytest','tests/test_student_mini_cpu_reset_boundary.py',
                'tests/test_student_mini_native_rtl_inputs.py','tests/test_student_mini_input_image.py','-q'])
            verify()
            result.update(status='PYTHON_LITEX_ENVIRONMENT_STAGE_PASS',
                reason='Offline isolated dependencies/imports/tests passed; actual CPU firmware/simulation in this venv and system toolchain qualification still required')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['elapsed_seconds']=time.monotonic()-started
    result['installed_bytes']=sum(p.stat().st_size for p in (work/'venv').rglob('*') if p.is_file())
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='PYTHON_LITEX_ENVIRONMENT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
