"""Host differential screening; not a replacement for CPU/GPU target execution."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
out=BASE/'runs/host-differential';out.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,TMPDIR=str(BASE/'build/cache/tmp'))
cmd=['gcc','-shared','-fPIC','-O2','-ffp-contract=off','-fno-fast-math','-DP3_TEST_PRIMITIVE',
    '-I'+str(ROOT/'sources/software/include'),str(ROOT/'sources/software/student_mini_native_nano.c'),
    str(ROOT/'sources/software/operator_scalar.c'),str(BASE/'src/p3_native_candidate.c'),'-o',str(out/'candidate.so')]
subprocess.run(cmd,check=True,env=env)
lib=C.CDLL(str(out/'candidate.so'))
class Model(C.Structure):_fields_=[('weight',C.POINTER(C.c_int8)*19),('scale',C.c_float*19)]
args=[C.c_void_p,C.c_uint,C.POINTER(C.c_int8),C.c_float,C.POINTER(Model),C.POINTER(C.c_uint16)]
for name in ['p3_native_candidate','mini_native_scalar_expert']:getattr(lib,name).argtypes=args
lib.p3_test_requant.argtypes=[C.c_int64]
lib.course_q22_requantize_int8.argtypes=[C.c_int64,C.c_float,C.POINTER(C.c_int8)]
rng=random.Random(1);primitive=0
values=[-(1<<30),1<<30,0,-1,1]
for q in range(-140,141):
    values.extend(q*65536+r for r in [-32769,-32768,-32767,-1,0,1,32767,32768,32769])
values.extend(rng.randint(-(1<<30),1<<30) for _ in range(20000))
for v in values:
    ref=C.c_int8();assert lib.course_q22_requantize_int8(v,C.c_float(2**-6),C.byref(ref))==0
    assert lib.p3_test_requant(v)==ref.value,(v,lib.p3_test_requant(v),ref.value)
    primitive+=1
weights=[(C.c_int8*512)() for _ in range(19)]
m=Model()
for i,w in enumerate(weights):m.weight[i]=w
calls=0
for case in range(1200):
    for i,w in enumerate(weights):
        for j in range(512):w[j]=rng.randint(-128,127)
        m.scale[i]=2**rng.randint(-16,12)
    x=(C.c_int8*16)(*[rng.randint(-128,127) for _ in range(16)])
    s=C.c_float(2**rng.randint(-16,12))
    for expert in range(4):
        a=(C.c_uint16*16)();b=(C.c_uint16*16)()
        ca=lib.mini_native_scalar_expert(None,expert,x,s,C.byref(m),a)
        cb=lib.p3_native_candidate(None,expert,x,s,C.byref(m),b)
        assert ca==cb and (ca!=0 or list(a)==list(b)),(case,expert,ca,cb)
        calls+=1
result=dict(status='HOST_DIFFERENTIAL_PASS',primitive_cases=primitive,expert_calls=calls,
    limitation='Random/boundary host screening only. Full-domain proof and target case/native verification remain.',
    command=cmd,source_sha256=hashlib.sha256((BASE/'src/p3_native_candidate.c').read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
