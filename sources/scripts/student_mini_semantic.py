"""Independent FP32 semantic errors, kept separate from bit-exact RTL errors."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def reference(row):
    if row['golden']['expected_status']!='OK':return None
    inp=row['inputs'];case=row['case'];s=inp['scales']
    a=lambda key:np.asarray(inp[key],dtype=np.float32)
    if case['operator'] in ('p1','p2'):
        outputs=[];q=a('query');keys=a('keys');v=a('values')
        for query in range(case['shape']['query']):
            n=case['shape']['length']-case['shape']['query']+query+1 if inp['layout']['causal'] else case['shape']['length']
            ids=list(range(n))
            if case['operator']=='p1':
                index=a('index_keys')@a('index_query')[query]
                ids=sorted(ids,key=lambda i:(-float(index[i]),i))[:case['shape']['topk']]
            score=(keys[ids]@q[query])*np.float32(s['score'])
            weights=np.exp(score-score.max(),dtype=np.float32)
            outputs.append((weights/weights.sum(dtype=np.float32))@v[ids]*np.float32(s['value']))
        output=np.asarray(outputs,dtype=np.float32)
    else:
        outputs=[]
        for i,expert in enumerate(inp['expert_ids']):
            x=a('activations')[i]*np.float32(s['input'])
            gate=(a('gate')[expert]*np.float32(s['gate']))@x
            up=(a('up')[expert]*np.float32(s['up']))@x
            z=np.exp(-np.abs(gate),dtype=np.float32)
            sigmoid=np.where(gate>=0,1/(1+z),z/(1+z)).astype(np.float32)
            # No Q5.11 clipping, LUT approximation, INT8 intermediate saturation
            # or BF16 output rounding in this semantic reference.
            outputs.append(((a('down')[expert]*np.float32(s['down']))@(gate*sigmoid*up))*np.float32(inp['route_weights'][i]))
        output=np.asarray(outputs,dtype=np.float32)
    if not np.isfinite(output).all():raise ValueError('nonfinite FP32 reference')
    return output.reshape(-1).astype(float).tolist()

def compare(reference,actual):
    if len(reference)!=len(actual):raise ValueError('semantic output shape mismatch')
    expected=np.asarray(reference,dtype=np.float64);observed=np.asarray(actual,dtype=np.float64)
    if not len(expected) or not np.isfinite(observed).all():raise ValueError('invalid semantic sample')
    delta=observed-expected
    return dict(reference_fp32=reference,actual_bf16=actual,delta=delta.tolist(),mae=float(np.abs(delta).mean()),rmse=float(np.sqrt(np.square(delta).mean())),max_abs_error=float(np.abs(delta).max()),element_count=len(expected),kind='semantic-quantization-error-not-bit-exact')

def build():
    pointer=json.loads((ROOT/'grading/student-mini/page-evidence.json').read_text())
    paths=[Path(__file__),ROOT/pointer['golden']]+[ROOT/r['path'] for r in pointer['results']]
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in paths};identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'grading/evidence/student-mini-v1/semantic'/identity;work.mkdir(parents=True,exist_ok=False)
    goldens=[json.loads(line) for line in paths[1].read_text().splitlines()]
    refs={(r['case']['id'],r['seed']):reference(r) for r in goldens}
    records=[]
    for source in pointer['results']:
        if sha(ROOT/source['path'])!=source['sha256']:raise ValueError('result SHA mismatch')
        for row in json.loads((ROOT/source['path']).read_text(encoding='utf-8'))['records']:
            expected=refs[(row['case']['id'],row['seed'])];obs=row['observation']
            value=compare(expected,obs['actual']) if expected is not None and obs.get('actual_status')=='OK' else None
            records.append(dict(platform=obs['platform'],case_id=row['case']['id'],seed=row['seed'],comparison=value,status='MEASURED' if value else 'NOT_APPLICABLE_ERROR_STATUS'))
    report=dict(schema_version=1,status='DIAGNOSTIC_ONLY',formal_baseline=False,definition='Full FP32 operator semantics on identical dequantized inputs; no fixed-point clipping/LUT/requantization/BF16 output rounding. Never substitute these errors for bit-exact acceptance.',bindings=bindings,records=records)
    path=work/'semantic.json';path.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),records=len(records),measured=sum(r['comparison'] is not None for r in records))))

if __name__=='__main__':build()
