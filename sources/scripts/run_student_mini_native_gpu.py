"""Serialized native Nano SimX execution, never wall-clock performance evidence."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args();work=args.work.resolve()
    manifest=json.loads((work/'manifest.json').read_text())
    bindings={**manifest['bindings'],str(work/'manifest.json'):sha(work/'manifest.json'),str(Path(__file__)):sha(Path(__file__))}
    bindings.update({str(work/name):digest for name,digest in manifest['artifacts'].items()})
    vendor=Path('/mnt/d/open-soc-ai-labs-vortex').resolve()
    names=subprocess.check_output(['git','-C',str(vendor),'ls-files','hw','sw','ci','sim','configure','config.mk.in','VX_config.toml'],text=True).splitlines()
    bindings.update({str(vendor/name):sha(vendor/name) for name in names if (vendor/name).is_file()})
    for dependency in ('softfloat/build/Linux-x86_64-GCC/softfloat.a', 'ramulator/libramulator.so'):
        path=vendor/'third_party'/dependency
        bindings[str(path)]=sha(path)
    if any(sha(Path(name))!=digest for name,digest in bindings.items()):raise ValueError('stale GPU source')
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    run=work/('simx-'+identity);run.mkdir(exist_ok=False)
    (run/'inputs.json').write_text(json.dumps(dict(bindings=bindings),indent=2)+'\n')
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',CHIP_BE='opencl',
        HIP_CLANG_PATH='/mnt/d/open-soc-ai-labs-vortex-tools/llvm-vortex/bin',MAKEFLAGS='-j2',THREADS='2')
    env['PATH']='/mnt/d/open-soc-ai-labs-vortex-tools/verilator/bin:'+env['PATH']
    env['OCL_ICD_VENDORS']=str(ROOT.parent/'rerun_sqrt3/opencl-vendors')
    build=work/'vortex-build';build.mkdir(exist_ok=True)
    configs='-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_FPU_TYPE=STD'
    commands=[('configure',[str(vendor/'configure'),'--xlen=32','--tooldir=/mnt/d/open-soc-ai-labs-vortex-tools','--osversion=ubuntu/focal',f'--prefix={work}/install'],build,120),
        ('kernel',['make','-j2','-C',str(build/'sw/kernel'),f'CONFIGS={configs}','THREADS=2'],work,600),
        ('compile',['make','-j2','-C',str(work),'all','THREADS=2'],work,600),
        ('execute',['make','-j2','-C',str(work),'run-simx','THREADS=2',f'OPTS={manifest["image_directory"]}/image.bin'],work,3600)]
    result=dict(status='HOLD',target_run_complete=False,accepted_nano_session=False,
        backend='simx',performance_eligible=False,entity_gpu_required=False,bindings=bindings,stages=[])
    started=time.monotonic();child=None
    def heartbeat(stage):
        (run/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            print(json.dumps(dict(work=str(run),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(name))!=digest for name,digest in bindings.items()):raise ValueError('GPU source changed while queued')
            for stage,command,cwd,timeout in commands:
                heartbeat(stage);then=time.monotonic()
                with (run/(stage+'.log')).open('x') as log:
                    child=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    code=child.wait(timeout=timeout)
                result['stages'].append(dict(stage=stage,exit_code=code,seconds=time.monotonic()-then))
                if code:raise RuntimeError(stage+' failed: '+str(code))
            text=(run/'execute.log').read_text(errors='replace')
            if sum(line.startswith('STUDENT_NATIVE_GPU_COMPLETE ') for line in text.splitlines())!=1:
                raise ValueError('missing or duplicate target completion')
            stamp=build/'sw/runtime/simx_config.stamp'
            if not stamp.is_file() or any(flag not in stamp.read_text() for flag in configs.split()):
                raise ValueError('SimX runtime configuration unbound')
            if any(sha(Path(name))!=digest for name,digest in bindings.items()):raise ValueError('GPU source changed during replay')
            result.update(target_run_complete=True,reason='Whole session executed on virtual GPU; independent complete-state join, quality and physical gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
        result['elapsed_seconds']=time.monotonic()-started
        heartbeat('TARGET_TRANSCRIPT_READY' if result['target_run_complete'] else 'HOLD')
        files=[p for p in run.iterdir() if p.is_file()]+[work/'native_nano']+list((build/'sw/runtime').glob('*.stamp'))+list((build/'sw/runtime').glob('*.so'))
        result['artifacts']={str(p):sha(p) for p in files if p.is_file()}
        (run/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(work=str(run),complete=result['target_run_complete'],reason=result['reason'])),flush=True)
    return 0 if result['target_run_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
