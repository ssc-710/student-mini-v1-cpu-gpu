"""Run input-only mini kernels on Full_4k VexRiscv, not the host CPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--build-child',type=Path)
    args=parser.parse_args()
    if args.build_child:
        # Locked LiteX's BIOS builder calls os.cpu_count() rather than honouring
        # MAKEFLAGS. This process-local override follows the actual affinity;
        # no installed tool sources or machine-wide configuration are changed.
        os.cpu_count=lambda: min(2,len(os.sched_getaffinity(0)))
        from integration.litex.soc import build_soc
        image=args.build_child/'inputs.bin'
        build_soc(output_dir=args.build_child/'soc',run=False,cpu_b0=True,control_smoke=True,cpu_variant='full',student_mini_image=image,student_mini_count=image.stat().st_size//1936)
        return 0
    source=args.input_dir.resolve();manifest=json.loads((source/'manifest.json').read_text())
    for name,digest in manifest['artifacts'].items():
        if sha(source/name)!=digest:raise ValueError('input artifact SHA mismatch')
    for name,digest in manifest['bindings'].items():
        if sha(ROOT/name)!=digest:raise ValueError('stale input source: '+name)
    count=manifest['count'] if not args.limit else min(args.limit,manifest['count'])
    if count<1:raise ValueError('limit must be nonnegative')
    paths=[Path(__file__),ROOT/'integration/litex/soc.py',ROOT/'integration/litex/bios/Makefile',ROOT/'integration/litex/bios/student_mini_session.c',ROOT/'build/vexriscv-profiles/VexRiscv_Full_4k.v',source/'manifest.json',source/'inputs.bin']
    paths += list((ROOT/'shared/rtl').glob('*.sv'))+list((ROOT/'shared/rtl').glob('*.svh'))
    paths += list((ROOT/'integration/litex/bios').glob('*.c'))+list((ROOT/'software/include').glob('*.h'))
    cgroup_relative=Path('/proc/self/cgroup').read_text().strip().split('::')[-1]
    cgroup=Path('/sys/fs/cgroup')/cgroup_relative.lstrip('/')
    limits={name:(cgroup/name).read_text().strip() if (cgroup/name).exists() else None for name in ('memory.max','memory.swap.max','cpu.max')}
    inputs=dict(files={str(p):sha(p) for p in paths},limit=count,threads=2,input_manifest=manifest,resource_limits=limits)
    identity=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    (work/'inputs.bin').write_bytes((source/'inputs.bin').read_bytes()[:count*1936])
    cpus=sorted(os.sched_getaffinity(0))[:2];os.sched_setaffinity(0,cpus)
    tool='/home/soclab/tools/verilator-5.040/bin/verilator'
    env=dict(os.environ,COURSE_STUDENT_MINI='1',COURSE_VERILATOR_BIN=tool,MAKEFLAGS='-j2',PYTHONUNBUFFERED='1')
    cap_enforced=limits=={'memory.max':str(8*1024**3),'memory.swap.max':'0','cpu.max':'200000 100000'}
    result=dict(status='HOLD',formal_baseline=False,input_sha256=identity,records_expected=count,cpu_affinity=cpus,aggregate_8gib_cap_validated=False,resource_limits=limits)
    started=time.monotonic();child=None
    print(json.dumps(dict(work=str(work),status='BUILDING',count=count)),flush=True)
    try:
        with (work/'build.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(Path(__file__)),'--input-dir',str(source),'--build-child',str(work)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            code=child.wait(timeout=1500)
            if code:raise RuntimeError(f'build exited {code}')
        simulator=work/'soc/gateware/obj_dir/Vsim'
        result['build_seconds']=time.monotonic()-started
        child=subprocess.Popen([str(simulator)],cwd=work/'soc/gateware',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',bufsize=1,start_new_session=True)
        messages=queue.Queue()
        def drain():
            for line in child.stdout:messages.put(line)
            messages.put(None)
        threading.Thread(target=drain,daemon=True).start()
        end=time.monotonic()+1800;complete=False
        with (work/'console.log').open('w',buffering=1) as log:
            while time.monotonic()<end:
                try:line=messages.get(timeout=.5)
                except queue.Empty:continue
                if line is None:break
                log.write(line)
                if line.startswith('STUDENT_CPU_COMPLETE '):complete=True;break
        if not complete:raise RuntimeError('CPU run missing completion marker')
        if any(sha(Path(p))!=digest for p,digest in inputs['files'].items()):raise ValueError('source changed during CPU replay')
        result.update(target_run_complete=True,reason='Target transcript collected; strict output join, adapter fault/protocol and remaining release gates still required')
    except Exception as error:
        result.update(target_run_complete=False,reason=f'{type(error).__name__}: {error}')
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
        result['elapsed_seconds']=time.monotonic()-started
        if cap_enforced:
            result['memory_peak_bytes']=int((cgroup/'memory.peak').read_text())
            result['memory_events']=(cgroup/'memory.events').read_text()
            result['aggregate_8gib_cap_validated']=bool(result.get('target_run_complete'))
        artifacts=[p for p in work.iterdir() if p.is_file()]+[work/'soc/software/bios/bios.bin',work/'soc/gateware/obj_dir/Vsim',work/'soc/gateware/sim.v',work/'soc/csr.csv']
        result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in artifacts if p.is_file()}
        (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(work=str(work),**result),indent=2),flush=True)
    return 0 if result.get('target_run_complete') else 1

if __name__=='__main__':raise SystemExit(main())
