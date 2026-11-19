"""330-call exact screen plus RV32 object/disassembly receipt."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess

BASE=Path(__file__).resolve().parents[1]; ROOT=BASE.parents[1]
run=BASE/'runs/p3-pair-host-330'; run.mkdir(parents=True,exist_ok=True)
include=ROOT/'sources/software/include'
sources=[ROOT/'sources/software/student_mini_native_nano.c',
         ROOT/'sources/software/operator_scalar.c', BASE/'src/p3_native_candidate.c',
         BASE/'src/p3_native_candidate_pair.c', BASE/'src/p3_native_candidate_ctx.c']
env=dict(os.environ,TMPDIR=str(BASE/'build/cache/tmp'))
host=['gcc','-shared','-fPIC','-O2','-ffp-contract=off','-fno-fast-math',
      '-I'+str(include),*[str(p) for p in sources],'-o',str(run/'pair.so')]
subprocess.run(host,check=True,env=env)
lib=C.CDLL(str(run/'pair.so'))
class Model(C.Structure):
    _fields_=[('weight',C.POINTER(C.c_int8)*19),('scale',C.c_float*19)]
args=[C.c_void_p,C.c_uint,C.POINTER(C.c_int8),C.c_float,C.POINTER(Model),C.POINTER(C.c_uint16)]
names=['mini_native_scalar_expert','p3_native_candidate','p3_native_candidate_pair','p3_native_candidate_ctx']
for name in names:getattr(lib,name).argtypes=args
rng=random.Random(0x50303330); weights=[(C.c_int8*512)() for _ in range(19)]; m=Model()
for i,w in enumerate(weights):m.weight[i]=w
calls=0
for case in range(110):
    for i,w in enumerate(weights):
        for j in range(512):w[j]=rng.randint(-128,127)
        m.scale[i]=2**rng.randint(-16,12)
    x=(C.c_int8*16)(*[rng.randint(-128,127) for _ in range(16)])
    scale=C.c_float(2**rng.randint(-16,12))
    for expert in range(3):
        outputs=[]; codes=[]
        for name in names:
            out=(C.c_uint16*16)(); codes.append(getattr(lib,name)(None,expert,x,scale,C.byref(m),out)); outputs.append(list(out))
        assert codes[0]==codes[1]==codes[2] and (codes[0]!=0 or outputs[0]==outputs[1]==outputs[2]),(case,expert,codes)
        calls+=1

flags=['-O2','-ffp-contract=off','-fno-fast-math','-march=rv32im_zicsr','-mabi=ilp32','-I'+str(include)]
objects={}
for stem in ['p3_native_candidate','p3_native_candidate_pair','p3_native_candidate_ctx']:
    obj=run/(stem+'.o'); subprocess.run(['riscv64-unknown-elf-gcc',*flags,'-c',str(BASE/'src'/f'{stem}.c'),'-o',str(obj)],check=True,env=env)
    dis=subprocess.run(['riscv64-unknown-elf-objdump','-dr',str(obj)],check=True,text=True,capture_output=True).stdout
    (run/(stem+'.dis')).write_text(dis)
    # Each object is compiled from one translation unit with one externally
    # visible function. Local .L labels are part of that function, not an end
    # marker, so count every decoded instruction in the object's .text.
    insns=[line for line in dis.splitlines() if re.match(r'^\s*[0-9a-f]+:',line)]
    objects[stem]=dict(instructions=len(insns),stack_loads=sum(bool(re.search(r'\b(?:lb|lbu|lh|lhu|lw)\s+\w+,\s*\d+\(sp\)',x)) for x in insns),
        stack_stores=sum(bool(re.search(r'\b(?:sb|sh|sw)\s+\w+,\s*\d+\(sp\)',x)) for x in insns),
        mul=sum(bool(re.search(r'\bmul\w*\b',x)) for x in insns),branches=sum(bool(re.search(r'\b(?:b\w+|j|jal)\b',x)) for x in insns),
        object_bytes=obj.stat().st_size,sha256=hashlib.sha256(obj.read_bytes()).hexdigest())
result=dict(status='HOST_330_EXACT_PASS_RV32_COMPILED',expert_calls=calls,seed='0x50303330',objects=objects,
 source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources[-3:]},
 limitation='Synthetic deterministic expert calls, not the frozen 33x10 end-to-end P3 vectors or target cycle qualification.')
(run/'result.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
