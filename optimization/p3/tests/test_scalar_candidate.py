"""Independent original/candidate host differential across the frozen input set."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE/'tools'));from prepare_scalar_candidate import prepare
sys.path.insert(0,str(ROOT/'sources'));from scripts.export_student_mini_input import encode
candidate=prepare()
out=BASE/'runs/scalar-host-differential';out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ,TMPDIR=str(BASE/'build/cache/tmp'))
for name,path in [('original',ROOT/'sources/software/student_mini_scalar.c'),('candidate',candidate)]:
    subprocess.run(['gcc','-shared','-fPIC','-O2','-ffp-contract=off','-fno-fast-math',
        '-I'+str(ROOT/'sources/software/include'),str(path),str(ROOT/'sources/software/operator_scalar.c'),
        '-o',str(out/(name+'.so'))],env=env,check=True)
class Result(C.Structure):
    _fields_=[('status',C.c_uint32),('count',C.c_uint32),('selected_count',C.c_uint32),
              ('output',C.c_uint16*32),('selected',C.c_uint8*8),('primitive',C.c_int32)]
libs=[C.CDLL(str(out/(n+'.so'))) for n in ['original','candidate']]
for lib in libs:lib.student_mini_execute.argtypes=[C.c_void_p,C.POINTER(Result)]
vectors=[json.loads(s) for s in (ROOT/'data/golden/vectors.jsonl').read_text().splitlines()]
records=[]
for ordinal,v in enumerate(vectors):
    raw=encode(v,ordinal);buf=C.create_string_buffer(raw);a=Result();b=Result()
    libs[0].student_mini_execute(buf,C.byref(a));libs[1].student_mini_execute(buf,C.byref(b))
    assert bytes(a)==bytes(b),(ordinal,v['case']['id'])
    records.append(dict(ordinal=ordinal,case_id=v['case']['id'],seed=v['seed'],status=int(b.status),match=True))
(out/'result.json').write_text(json.dumps(dict(status='HOST_DIFFERENTIAL_PASS',records=records,
    candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
    limitation='Host only; unsupported bus injection is not BUS_ERROR qualification; no target/protocol claim.'),indent=2)+'\n')
print('HOST_SCALAR_DIFFERENTIAL_PASS',len(records))
