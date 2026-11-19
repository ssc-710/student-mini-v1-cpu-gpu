"""Actual local RTL differential; not whole GPU or physical qualification."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
out=BASE/'runs/gpu-limb-rtl';out.mkdir(parents=True,exist_ok=False)
files=[BASE/'src/rtl/gpu_signed33_limb_mul3.sv',ROOT/'sources/integration/student-mini/gpu_signed33_mul3.sv',
       BASE/'tests/gpu_limb_tb.sv',BASE/'tests/gpu_limb_main.cpp']
env=dict(os.environ,TMPDIR=str(BASE/'build/cache/tmp'),HOME=str(BASE/'build/cache/home'))
cmd=['/usr/bin/verilator','--cc','--exe','--build','-j','2','-Wno-fatal','--top-module','gpu_limb_tb',
    '--Mdir',str(out/'obj')]+[str(p) for p in files]
with (out/'compile.log').open('x') as f:
    p=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=300)
assert p.returncode==0
with (out/'execute.log').open('x') as f:
    p=subprocess.run([str(out/'obj/Vgpu_limb_tb')],env=env,stdout=f,stderr=subprocess.STDOUT,timeout=120)
text=(out/'execute.log').read_text();passed=p.returncode==0 and text.startswith('GPU_LIMB_PASS ')
(out/'receipt.json').write_text(json.dumps(dict(status='LOCAL_RTL_DIFFERENTIAL_PASS' if passed else 'FAIL',
    command=cmd,exit_code=p.returncode,result=text,
    bindings={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    limitation='No full-domain formal proof, whole-core/reset/flush qualification, mapped timing/PPA, or promotion.'),indent=2)+'\n')
print(text);assert passed
