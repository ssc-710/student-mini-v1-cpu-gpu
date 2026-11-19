"""Serialize explicit inputs only, never goldens, for target CPU/GPU runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

RECORD_BYTES=1936
def flatten(value):
    return [v for row in value for v in flatten(row)] if isinstance(value,list) else [value]

def encode(item,ordinal):
    inp=item['inputs'];shape=item['case']['shape'];op=item['case']['operator'];s=inp['scales']
    words=[0]*32
    words[:14]=[0x31494e4d,int(op[-1]),ordinal,item['seed'],shape.get('query',shape.get('rows',0)),shape.get('length',0),shape.get('topk',0),shape.get('splits',0),shape.get('hidden',0),shape.get('intermediate',0),inp['layout']['page_size'],int(inp['layout']['causal']),int(inp['protocol']['inject_dma_error']),len(inp['layout']['pages'])]
    for i,v in enumerate(inp.get('expert_ids',[])):words[14+i]=v
    floats=[s[k] for k in ('input','gate','up','intermediate','down','score','value')]+inp.get('route_weights',[0.,0.])
    floats=floats+[0.]*(9-len(floats))
    for i,value in enumerate(floats):
        value={'NaN':float('nan'),'+Inf':float('inf'),'-Inf':-float('inf')}.get(value,value) if isinstance(value,str) else value
        words[16+i]=struct.unpack('<I',struct.pack('<f',value))[0]
    witness=inp.get('primitive_witness',{})
    if witness.get('kind')=='rne-integer-division':words[25:28]=[1,witness['numerator']&0xffffffff,witness['denominator']]
    if witness.get('kind')=='int8-saturation':words[25]=2;words[28]=witness['value']&0xffffffff
    for i,page in enumerate(inp['layout']['pages']):words[29+i]=page
    result=bytearray(struct.pack('<32I',*words))
    for key,size in [('activations' if op=='p3' else 'query',32),('keys',96),('values',64),('index_query',16),('index_keys',64),('gate',512),('up',512),('down',512)]:
        values=flatten(inp.get(key,[]))
        if len(values)>size:raise ValueError(f'{key} exceeds mini record')
        result.extend(bytes(v&255 for v in values)+bytes(size-len(values)))
    assert len(result)==RECORD_BYTES
    return bytes(result)

def build(vectors,output):
    rows=[json.loads(line) for line in vectors.read_text().splitlines()]
    bindings={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (vectors,Path(__file__),ROOT/'software/student_mini_scalar.c',ROOT/'software/include/student_mini_scalar.h',ROOT/'software/operator_scalar.c',ROOT/'software/include/numeric_luts.h')}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=output/identity;work.mkdir(parents=True,exist_ok=False)
    image=b''.join(encode(item,i) for i,item in enumerate(rows))
    (work/'inputs.bin').write_bytes(image)
    report=dict(schema_version=1,status='HOLD',record_bytes=RECORD_BYTES,count=len(rows),bindings=bindings,input_sha256=identity,artifacts={'inputs.bin':sha(work/'inputs.bin')},boundary='Input-only data; target computation and protocol evidence required; no expected outputs embedded')
    (work/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),bytes=len(image),records=len(rows))))
    return work

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True);parser.add_argument('--output',type=Path,default=ROOT/'build/student-mini/input-images')
    args=parser.parse_args();build(args.vectors.resolve(),args.output.resolve())
