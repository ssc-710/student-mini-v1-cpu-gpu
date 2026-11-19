"""Export one frozen P1/P2 workload per seed, with golden data checker-only."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def prepare(vectors,operator,run_tag=None):
    fill=importlib.import_module('tests.rtl.test_student_mini_'+operator).fill
    records=[json.loads(line) for line in vectors.read_text(encoding='utf-8').splitlines() if line.strip()]
    case=operator.upper()+'-MINI-01'
    rows=[r for r in records if r['case']['id']==case]
    if sorted(r['seed'] for r in rows)!=list(range(1,11)):raise ValueError('missing/duplicate workload seed')
    files=[vectors,Path(__file__),ROOT/f'tests/rtl/test_student_mini_{operator}.py',
        ROOT/f'tests/rtl/test_{operator}_litex_b0.py',ROOT/'tests/rtl/test_student_mini_p3.py',
        ROOT/'tests/rtl/student_mini_attention_gate_activity_tb.sv',ROOT/'shared/python/soc_ai_labs/deepseek_v32.py']
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    # run_tag (optional): fresh, separately identified manifest of unchanged inputs; without it the identity is unchanged
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,operator=operator,**({'run_tag':run_tag} if run_tag else {})),sort_keys=True).encode()).hexdigest()
    out=ROOT/'build/student-mini/attention-activity-inputs'/identity;out.mkdir(parents=True,exist_ok=False)
    samples=[]
    for row in sorted(rows,key=lambda row:row['seed']):
        if row['case']['shape']['query']!=1 or row['case']['shape']['length']!=1 or row['golden']['expected_status']!='OK':
            raise ValueError('gate workload contract changed: one row, one valid token required')
        contents,address,_=fill(row)
        if address!=0x9000 or any(p>=65536 or p<0 for p in contents):raise ValueError('workload address overflow')
        image=bytes(contents.get(i,0) for i in range(65536))
        path=out/f'seed-{row["seed"]}.hex'
        path.write_text('\n'.join(f'{value:02x}' for value in image)+'\n',encoding='ascii')
        sample=dict(operator=operator,case_id=case,seed=row['seed'],image=path.name,image_sha256=sha(path),
            input_sha256=hashlib.sha256(json.dumps(row['inputs'],sort_keys=True).encode()).hexdigest(),
            expected_bits=row['golden']['output_bits'])
        if operator=='p1':sample['expected_selected']=[v for ids in row['golden']['selected_token_ids'] for v in ids]
        samples.append(sample)
    path=out/'manifest.json'
    path.write_text(json.dumps(dict(status='INPUTS_ONLY',operator=operator,clock_hz=100000000,
        case_id=case,bindings=bindings,samples=samples,note='Representative per-seed loads, not all-case power; expected values remain outside DUT memory'),indent=2)+'\n')
    print(json.dumps(dict(path=str(path),sha256=sha(path))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors',type=Path,required=True)
    parser.add_argument('--operator',choices=['p1','p2'],required=True)
    parser.add_argument('--run-tag')
    args=parser.parse_args();prepare(args.vectors.resolve(),args.operator,args.run_tag)
