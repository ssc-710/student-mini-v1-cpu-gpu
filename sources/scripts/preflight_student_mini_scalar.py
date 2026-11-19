"""Native scalar preflight, explicitly NOT VexRiscv/GPU hardware evidence."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.export_student_mini_input import build,RECORD_BYTES
from scripts.student_mini import sha

class Result(ctypes.Structure):
    _fields_=[('status',ctypes.c_uint32),('count',ctypes.c_uint32),('selected_count',ctypes.c_uint32),('output',ctypes.c_uint16*32),('selected',ctypes.c_uint8*8),('primitive',ctypes.c_int32)]

def main(vectors):
    work=build(vectors,ROOT/'build/student-mini/input-images')
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off','-shared','-fPIC',str(ROOT/'software/student_mini_scalar.c'),str(ROOT/'software/operator_scalar.c'),'-o',str(work/'preflight.so')],check=True)
    kernel=ctypes.CDLL(str(work/'preflight.so')).student_mini_execute
    kernel.argtypes=[ctypes.c_void_p,ctypes.POINTER(Result)]
    image=(work/'inputs.bin').read_bytes();rows=[json.loads(line) for line in vectors.read_text().splitlines()]
    statuses={'OK':0,'BAD_DESCRIPTOR':1,'BAD_LENGTH':2,'BAD_PAGE':3,'NUMERIC_ERROR':4,'BUS_ERROR':5}
    records=[]
    for i,row in enumerate(rows):
        data=ctypes.create_string_buffer(image[i*RECORD_BYTES:(i+1)*RECORD_BYTES]);r=Result();kernel(data,ctypes.byref(r))
        expected=row['golden'];bits=list(r.output)[:r.count]
        match=r.status==statuses[expected['expected_status']] and bits==expected['output_bits']
        if 'primitive_witness_result' in expected:match=match and r.primitive==expected['primitive_witness_result']
        if row['case']['operator']=='p1' and expected['output_bits']:match=match and list(r.selected)[:r.selected_count]==[x for ids in expected['selected_token_ids'] for x in ids]
        records.append(dict(case_id=row['case']['id'],seed=row['seed'],status='UNSUPPORTED_BUS_INJECTION' if r.status==6 else 'PASS' if match else 'FAIL',actual_status=r.status,actual_bits=bits,selected=list(r.selected)[:r.selected_count],primitive=r.primitive))
    report=dict(status='HOLD',kind='native-preflight-only',hardware_execution=False,counts={s:sum(r['status']==s for r in records) for s in ('PASS','FAIL','UNSUPPORTED_BUS_INJECTION')},records=records,bindings={p.name:sha(p) for p in (work/'inputs.bin',work/'preflight.so',Path(__file__))})
    (work/'native-preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),counts=report['counts'],hardware_execution=False)))
    return int(report['counts']['FAIL']!=0)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True);args=parser.parse_args();raise SystemExit(main(args.vectors.resolve()))
