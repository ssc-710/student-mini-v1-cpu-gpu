import json
import os
from pathlib import Path
import subprocess
import time

here=Path(__file__).resolve().parent
out=here/'fresh-baselines'
plan=json.loads((out/'plan.json').read_text())
gpu=Path(plan['gpu'])
old=here.parent/'sources/build/student-mini/native-gpu/fc14e0f618eacaeb78fd0df4626bab2fd19315064842dab6b7c12084b13bb61c/vortex-build'
env=dict(os.environ,CHIP_BE='opencl',HIP_CLANG_PATH='/mnt/d/open-soc-ai-labs-vortex-tools/llvm-vortex/bin',
         OCL_ICD_VENDORS=str(here/'opencl-vendors'),MAKEFLAGS='-j2',THREADS='2',VORTEX_CP_POLL_TIMEOUT_S='45',CHIP_LOGLEVEL='err')
logs=out/'gpu-batches';logs.mkdir(exist_ok=False)
codes=[]
for start in range(0,1000,10):
    cmd=['make','-j2',f'VORTEX_BUILD={old}',
         'CONFIGS=-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_FPU_TYPE=STD',
         f'OPTS={out}/inputs.bin {start} 10','run-simx']
    then=time.monotonic()
    with (logs/f'{start:04}.log').open('x') as f:
        p=subprocess.run(cmd,cwd=gpu,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
    codes.append(dict(start=start,count=10,exit_code=p.returncode,seconds=time.monotonic()-then))
    (logs/'progress.json').write_text(json.dumps(codes,indent=2))
    print(start,p.returncode,flush=True)
    if p.returncode:break
