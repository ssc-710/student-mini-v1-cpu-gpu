"""Exact host/domain check and RV32 code inspection for private i32 Q6."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
out=BASE/'runs/p3-i32-host';out.mkdir(exist_ok=False)
env=dict(os.environ,TMPDIR=str(BASE/'build/cache/tmp'))
sources=[ROOT/'sources/software/student_mini_native_nano.c',ROOT/'sources/software/operator_scalar.c',
         BASE/'src/p3_native_candidate.c',BASE/'src/p3_native_candidate_i32.c']
cmd=['gcc','-shared','-fPIC','-O2','-ffp-contract=off','-fno-fast-math','-DP3_TEST_PRIMITIVE',
     '-I'+str(ROOT/'sources/software/include'),*map(str,sources),'-o',str(out/'candidate.so')]
subprocess.run(cmd,check=True,env=env)
lib=C.CDLL(str(out/'candidate.so'))
class Model(C.Structure):_fields_=[('weight',C.POINTER(C.c_int8)*19),('scale',C.c_float*19)]
args=[C.c_void_p,C.c_uint,C.POINTER(C.c_int8),C.c_float,C.POINTER(Model),C.POINTER(C.c_uint16)]
for name in ['p3_native_candidate','p3_native_candidate_i32']:
    getattr(lib,name).argtypes=args
lib.p3_test_requant.argtypes=[C.c_int64];lib.p3_test_requant_i32.argtypes=[C.c_int32]
rng=random.Random(0x50336933)
values=[-(1<<30),-(1<<30)+1,-1073709056,-1,0,1,(1<<30)-1,1<<30]
for q in range(-16384,16385):
    for r in [-32769,-32768,-32767,-1,0,1,32767,32768,32769]:
        value=q*65536+r
        if -1073709056<=value<=1<<30: values.append(value)
values += [rng.randint(-1073709056,1<<30) for _ in range(50000)]
for value in values:
    assert lib.p3_test_requant(value)==lib.p3_test_requant_i32(value),value
weights=[(C.c_int8*512)() for _ in range(19)];model=Model()
for i,w in enumerate(weights):model.weight[i]=w
calls=0
for case in range(330):
    for i,w in enumerate(weights):
        for j in range(512):w[j]=rng.randint(-128,127)
        model.scale[i]=2**rng.randint(-16,12)
    x=(C.c_int8*16)(*[rng.randint(-128,127) for _ in range(16)])
    scale=C.c_float(2**rng.randint(-16,12));expert=case%3
    a=(C.c_uint16*16)();b=(C.c_uint16*16)()
    ca=lib.p3_native_candidate(None,expert,x,scale,C.byref(model),a)
    cb=lib.p3_native_candidate_i32(None,expert,x,scale,C.byref(model),b)
    assert ca==cb and list(a)==list(b),(case,ca,cb)
    calls+=1
cc=ROOT/'rerun_sqrt3/tools/riscv32-gnu-toolchain/bin/riscv32-unknown-elf-gcc'
objdump=cc.with_name('riscv32-unknown-elf-objdump')
objects={}
for source in sources[-2:]:
    obj=out/(source.stem+'.o')
    command=[str(cc),'-O2','-ffp-contract=off','-fno-fast-math','-march=rv32im_zicsr','-mabi=ilp32',
             '-I'+str(ROOT/'sources/software/include'),'-c',str(source),'-o',str(obj)]
    subprocess.run(command,check=True,env=env)
    dis=subprocess.run([str(objdump),'-d',str(obj)],check=True,capture_output=True,text=True).stdout
    (out/(source.stem+'.dis')).write_text(dis)
    objects[source.stem]=dict(bytes=obj.stat().st_size,sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
                              mulh=dis.count('\tmulh\t'),instructions=sum('\t' in line for line in dis.splitlines()))
result=dict(status='PRIVATE_I32_Q6_HOST_EXACT_RV32_COMPILED',primitive_values=len(values),expert_calls=calls,
    objects=objects,bindings={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(__file__),*sources,out/'candidate.so']},
    limitation='Host synthetic exactness and RV32 static code only; frozen 330 target cases and same-ELF target cycles remain required.')
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
