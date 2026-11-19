import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

here=Path(__file__).resolve().parent
root=here.parent/'sources'
sys.path.insert(0,str(root))
from scripts.export_student_mini_input import encode
from scripts.prepare_student_mini_gpu import prepare

out=here/'fresh-baselines'
out.mkdir(exist_ok=False)
vectors=here.parent/'data/golden/vectors.jsonl'
rows=[json.loads(s) for s in vectors.read_text().splitlines()]
assert len(rows)==1000
image=out/'inputs.bin'
image.write_bytes(b''.join(encode(r,i) for i,r in enumerate(rows)))
paths=[root/'software/student_mini_scalar.c',root/'software/include/student_mini_scalar.h',root/'software/operator_scalar.c',root/'software/include/numeric_luts.h']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(out/'manifest.json').write_text(json.dumps(dict(count=1000,bindings={str(p.relative_to(root)):sha(p) for p in paths},artifacts={'inputs.bin':sha(image)},golden_sha256=sha(vectors)),indent=2))
gpu=prepare(out)
(out/'plan.json').write_text(json.dumps(dict(gpu=str(gpu),cpu='/mnt/d/sqrt3-rerun/baselines-cpu',golden=str(vectors),input_sha256=sha(image),scope='Fresh scalar operator execution; DMA/protocol witnesses separate'),indent=2))
env=dict(os.environ,CHIP_BE='opencl',HIP_CLANG_PATH='/mnt/d/open-soc-ai-labs-vortex-tools/llvm-vortex/bin',
         OCL_ICD_VENDORS=str(here/'opencl-vendors'),MAKEFLAGS='-j2',THREADS='2')
old=root/'build/student-mini/native-gpu/fc14e0f618eacaeb78fd0df4626bab2fd19315064842dab6b7c12084b13bb61c/vortex-build'
def launch(cmd,log,cwd):
    stream=(out/log).open('x')
    p=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    stream.close()
    return p
cpu=launch([sys.executable,str(here/'build_baseline_cpu.py'),str(image)],'cpu-build.log',root)
print('CPU_BUILD_STARTED',cpu.pid,flush=True)
configs='-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_FPU_TYPE=STD'
cmd=['make','-j2',f'VORTEX_BUILD={old}',f'CONFIGS={configs}',f'OPTS={image}']
g=launch(cmd+['run-simx'],'gpu-execute.log',gpu)
print('GPU_SIMX_STARTED',g.pid,flush=True)
processes={'cpu-build':cpu,'gpu':g}
codes={}
while processes:
    for name,p in list(processes.items()):
        if name=='cpu' and (out/'cpu-console.log').is_file() and 'STUDENT_CPU_COMPLETE count=1000' in (out/'cpu-console.log').read_text(errors='replace'):
            p.terminate()
        code=p.poll()
        if code is None:continue
        codes[name]=code;del processes[name]
        print(name,'EXIT',code,flush=True)
        if name=='cpu-build' and code==0:
            work=Path('/mnt/d/sqrt3-rerun/baselines-cpu/soc/gateware')
            processes['cpu']=launch([str(work/'obj_dir/Vsim')],'cpu-console.log',work)
    (out/'progress.json').write_text(json.dumps(dict(codes=codes,running={n:p.pid for n,p in processes.items()})))
    if processes:time.sleep(2)
print(json.dumps(codes),flush=True)
