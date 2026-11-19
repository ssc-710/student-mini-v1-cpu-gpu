"""Install a SHA-verified test stack offline into a fresh, isolated venv."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import venv

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock-directory',type=Path,required=True)
    parser.add_argument('--environment',type=Path,required=True)
    args=parser.parse_args();lock=args.lock_directory.resolve();environment=args.environment.resolve()
    if environment.exists():raise ValueError('never overwrite an existing Python environment')
    payload=json.loads((lock/'python-lock.json').read_text())
    paths={}
    for row in payload['packages']:
        path=lock/'downloaded-artifacts'/row['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('artifact changed')
        paths[row['name']]=path
    started=time.monotonic();venv.EnvBuilder(with_pip=True,symlinks=False).create(environment)
    python=environment/'bin/python';checks=[]
    commands=[('bootstrap',[str(python),'-m','pip','install','--no-index','--no-deps',*[str(paths[n]) for n in ('pip','setuptools','wheel')]]),
              ('install',[str(python),'-m','pip','install','--no-index','--no-cache-dir','--no-build-isolation','--find-links',str(lock/'downloaded-artifacts'),'--require-hashes','-r',str(lock/'requirements-hashed.txt')]),
              ('pip-check',[str(python),'-m','pip','check']),
              ('regression',[str(python),'-m','pytest','tests/test_student_mini.py','tests/test_student_mini_vectors.py','tests/test_assemble_student_mini_results.py','tests/test_student_mini_cpu_results.py','tests/test_student_mini_gpu_results.py','tests/test_student_mini_gpu_counters.py','tests/test_student_mini_input_image.py','tests/test_student_mini_semantic.py','-q'])]
    for name,command in commands:
        result=subprocess.run(command,capture_output=True,timeout=300)
        log=environment/(name+'.log');log.write_bytes(result.stdout+result.stderr)
        checks.append(dict(name=name,exit_code=result.returncode,sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(json.dumps(checks[-1]),flush=True)
        if result.returncode:break
    report=dict(status='PASS' if len(checks)==len(commands) and all(c['exit_code']==0 for c in checks) else 'HOLD',
                scope='Python numerical/test stack only; LiteX, GPU tools, EDA, teacher training remain separate',
                complete_student_environment=False,network_used_for_install=False,checks=checks,
                elapsed_seconds=time.monotonic()-started,installed_bytes=sum(p.stat().st_size for p in environment.rglob('*') if p.is_file()),
                lock_sha256=hashlib.sha256((lock/'python-lock.json').read_bytes()).hexdigest())
    (environment/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
