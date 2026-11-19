"""Fresh target executions; no reference answers are used by either target."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OLD = ROOT / 'rerun_sqrt3'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def save(name, value):
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def prepare():
    # Reuse only the input transformation, not inference or saved outputs.
    text = (OLD/'prepare_image.py').read_text(encoding='utf-8')
    text = text.replace("question = '根号3等于几？'", "question = '根号5等于几？'")
    exec(compile(text, str(HERE/'prepare_image.py'), 'exec'), {'__file__':str(HERE/'prepare_image.py')})
    blob=(HERE/'image/image.bin').read_bytes()
    loader=Path('/mnt/d/sqrt3-rerun/cpu/loader.bin')
    assert loader.read_bytes() == blob+bytes((-len(blob))%1936), 'Rebuild RTL for changed encoded input'
    result=subprocess.run([sys.executable,str(ROOT/'sources/scripts/prepare_student_mini_native_gpu.py'),
        '--image-dir',str(HERE/'image')],check=True,capture_output=True,text=True)
    save('plan.json',dict(gpu=json.loads(result.stdout)['work'],cpu_loader_sha256=sha(loader),
        cpu_reuse_reason='New question has byte-identical encoded model input; reuse compiled RTL, never saved output.'))

def run(name,command,cwd,env=None,marker=None):
    log=HERE/(name+'.log'); events=HERE/(name+'.events.jsonl')
    assert not log.exists(), 'Never overwrite a prior run'
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat()
    start=time.monotonic();complete=False; boundary={}
    child=subprocess.Popen(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,errors='replace',bufsize=1,start_new_session=True)
    with log.open('x',encoding='utf-8',buffering=1) as f, events.open('x',encoding='utf-8',buffering=1) as e:
        for line in child.stdout:
            elapsed=time.monotonic()-start
            f.write(line)
            e.write(json.dumps(dict(seconds=elapsed,line=line.rstrip()),ensure_ascii=False)+'\n')
            if 'STUDENT_NATIVE_' in line:print(name,line[:150].rstrip(),flush=True)
            if line.startswith('STUDENT_NATIVE_CPU_BEGIN'):boundary['generation_begin_seconds']=elapsed
            if line.startswith('STUDENT_NATIVE_CPU status='):boundary['generation_summary_seconds']=elapsed
            if marker and line.startswith(marker):
                complete=True; boundary['completion_seconds']=elapsed
                if name=='cpu':os.killpg(child.pid,signal.SIGTERM)
                break
    code=child.wait(timeout=120)
    receipt=dict(command=command,cwd=str(cwd),started_at_utc=utc,pid=child.pid,exit_code=code,
        elapsed_seconds=time.monotonic()-start,complete=complete,log_sha256=sha(log),
        binary_sha256=sha(Path(command[0])) if Path(command[0]).is_file() else None,**boundary)
    save(name+'.receipt.json',receipt)
    assert (complete if marker else code==0),receipt
    return receipt

def execute():
    plan=json.loads((HERE/'plan.json').read_text())
    cpu=Path('/mnt/d/sqrt3-rerun/cpu/soc/gateware')
    save('cpu-bindings.json',{str(p):sha(p) for p in [cpu/'obj_dir/Vsim',cpu/'sim_mem.init',
         Path('/mnt/d/sqrt3-rerun/cpu/loader.bin'),HERE/'image/image.bin',HERE/'image/manifest.json']})
    run('cpu',[str(cpu/'obj_dir/Vsim')],cpu,marker='STUDENT_NATIVE_CPU_COMPLETE')
    gpu=Path(plan['gpu'])
    oldbuild=ROOT/'sources/build/student-mini/native-gpu/fc14e0f618eacaeb78fd0df4626bab2fd19315064842dab6b7c12084b13bb61c/vortex-build'
    env=dict(os.environ,CHIP_BE='opencl',HIP_CLANG_PATH='/mnt/d/open-soc-ai-labs-vortex-tools/llvm-vortex/bin',
        OCL_ICD_VENDORS=str(OLD/'opencl-vendors'),MAKEFLAGS='-j2',THREADS='2',VORTEX_CP_POLL_TIMEOUT_S='45',CHIP_LOGLEVEL='err')
    make=['make','-j2',f'VORTEX_BUILD={oldbuild}']
    run('gpu-build',make+['all'],gpu,env)
    dry=subprocess.run(make+['-n',f'OPTS={HERE}/image/image.bin','run-simx'],cwd=gpu,env=env,
        check=True,capture_output=True,text=True)
    (HERE/'gpu-command.txt').write_text(dry.stdout)
    print(dry.stdout,flush=True)
    commands=[x for x in dry.stdout.splitlines() if 'VORTEX_DRIVER=simx' in x and './native_nano' in x]
    assert len(commands)==1,commands
    save('gpu-bindings.json',{str(p):sha(p) for p in [gpu/'native_nano',gpu/'native_nano.cu',gpu/'manifest.json',
        oldbuild/'sw/runtime/libvortex.so',oldbuild/'sw/runtime/libvortex-simx.so',oldbuild/'sw/runtime/libsimx.so',HERE/'image/image.bin']})
    run('gpu',['/bin/bash','-c',commands[0]],gpu,env,marker='STUDENT_NATIVE_GPU_COMPLETE')

if __name__=='__main__':
    {'prepare':prepare,'execute':execute}[sys.argv[1]]()
