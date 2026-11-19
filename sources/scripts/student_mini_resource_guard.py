"""Limit an entire task tree with cgroup v2; fail closed if unavailable."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--timeout',type=int,default=1800);parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:raise ValueError('missing command')
    if args.output.exists():raise ValueError('resource report already exists')
    started=time.monotonic();root=Path('/sys/fs/cgroup');group=root/f'codex-student-mini-{os.getpid()}';child=None
    result=dict(schema_version=1,status='HOLD',limits_enforced=False,command=command,cgroup=str(group),cpu_limit=2,memory_limit_bytes=8*1024**3,swap_limit_bytes=0,timeout_seconds=args.timeout,created_at=datetime.now(timezone.utc).isoformat())
    try:
        if os.geteuid()!=0:raise PermissionError('root required only to create an isolated cgroup; target runs as soclab')
        controllers=(root/'cgroup.controllers').read_text().split()
        if not {'cpu','memory'}.issubset(controllers):raise RuntimeError('missing CPU/memory controllers')
        group.mkdir()
        enabled=(root/'cgroup.subtree_control').read_text().split()
        missing=[f'+{name}' for name in ('cpu','memory') if name not in enabled]
        if missing:(root/'cgroup.subtree_control').write_text(' '.join(missing))
        (group/'cpu.max').write_text('200000 100000')
        (group/'memory.max').write_text(str(8*1024**3))
        (group/'memory.swap.max').write_text('0')
        (group/'memory.oom.group').write_text('1')
        # Two CPUs for this task, chosen among those least used by other live
        # guarded tasks (each still limited to 2 CPUs by cpu.max).
        usage={c:0 for c in os.sched_getaffinity(0)}
        for other in root.glob('codex-student-mini-*'):
            try:
                pids=(other/'cgroup.procs').read_text().split()
                busy=os.sched_getaffinity(int(pids[0])) if pids else set()
            except (OSError,ValueError):busy=set()
            if len(busy)<len(usage):
                for c in busy:
                    if c in usage:usage[c]+=1
        cpus=sorted(sorted(usage,key=lambda c:(usage[c],c))[:2])
        result['cpus']=cpus
        def enter():
            (group/'cgroup.procs').write_text(str(os.getpid()))
            os.sched_setaffinity(0,cpus)
        result['limits_enforced']=True
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.with_suffix('.log').open('x') as log:
            child=subprocess.Popen(['runuser','-u','soclab','--',*command],preexec_fn=enter,start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
            result['exit_code']=child.wait(timeout=args.timeout)
        result.update(status='PASS' if result['exit_code']==0 else 'HOLD',memory_peak_bytes=int((group/'memory.peak').read_text()),memory_events=(group/'memory.events').read_text(),cpu_stat=(group/'cpu.stat').read_text())
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
        if group.exists():
            # Only this empty task cgroup, never the root or another task.
            if not (group/'cgroup.procs').read_text().strip():group.rmdir()
        result['elapsed_seconds']=time.monotonic()-started
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
