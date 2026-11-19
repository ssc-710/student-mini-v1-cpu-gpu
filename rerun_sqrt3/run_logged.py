"""Run a subprocess with persistent output and a bounded completion marker."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser()
p.add_argument('--log', type=Path, required=True)
p.add_argument('--cwd', type=Path)
p.add_argument('--marker')
p.add_argument('--timeout', type=int, default=7200)
p.add_argument('command', nargs=argparse.REMAINDER)
a=p.parse_args()
command=a.command[1:] if a.command and a.command[0]=='--' else a.command
a.log.parent.mkdir(parents=True, exist_ok=True)
start=time.time()
child=subprocess.Popen(command,cwd=a.cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                       text=True,errors='replace',bufsize=1)
complete=False
try:
    with a.log.open('w',encoding='utf-8',buffering=1) as f:
        for line in child.stdout:
            f.write(line)
            print(line,end='',flush=True)
            if a.marker and line.startswith(a.marker):
                complete=True
                child.terminate()
                break
            if time.time()-start>a.timeout:
                child.terminate()
                raise TimeoutError('execution time limit')
    code=child.wait(timeout=20)
finally:
    if child.poll() is None:child.kill()
receipt=dict(command=command,cwd=str(a.cwd),exit_code=child.returncode,
             completion_marker_observed=complete,elapsed_seconds=time.time()-start,
             started_at=datetime.datetime.fromtimestamp(start,datetime.timezone.utc).isoformat(),
             log_sha256=hashlib.sha256(a.log.read_bytes()).hexdigest())
a.log.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
raise SystemExit(0 if complete or (not a.marker and code==0) else 1)
