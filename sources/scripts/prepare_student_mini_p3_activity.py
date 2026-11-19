"""Export frozen P3-MINI-01 seed 1..10 inputs for real gate-level workloads."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def prepare(vectors,run_tag=None):
    # Reuse the exact packer already exercised by the full RTL functional run.
    from tests.rtl.test_student_mini_p3 import fill
    records=[json.loads(line) for line in vectors.read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=[r for r in records if r['case']['id']=='P3-MINI-01']
    if sorted(r['seed'] for r in rows)!=list(range(1,11)):raise ValueError('missing or duplicated activity seed')
    files=[vectors,Path(__file__),ROOT/'tests/rtl/test_student_mini_p3.py',ROOT/'tests/rtl/test_p3_litex_b0.py',ROOT/'tests/rtl/student_mini_p3_gate_activity_tb.sv',ROOT/'shared/python/soc_ai_labs/deepseek_v32.py']
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    # run_tag (optional): fresh, separately identified manifest of unchanged inputs; without it the identity is unchanged
    identity=hashlib.sha256(json.dumps(dict(bindings,run_tag=run_tag) if run_tag else bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'build/student-mini/p3-activity-inputs'/identity;out.mkdir(parents=True,exist_ok=False)
    samples=[]
    for row in sorted(rows,key=lambda row:row['seed']):
        if row['case']['shape']['rows']!=1 or row['case']['shape']['hidden']!=16 or row['golden']['expected_status']!='OK':raise ValueError('unexpected activity workload shape')
        contents,address=fill(row)
        if address!=0xa000 or any(p>=65536 for p in contents):raise ValueError('image address overflow')
        image=bytes(contents.get(i,0) for i in range(65536))
        path=out/f'seed-{row["seed"]}.hex'
        path.write_text('\n'.join(f'{value:02x}' for value in image)+'\n',encoding='ascii')
        samples.append(dict(case_id=row['case']['id'],seed=row['seed'],image=path.name,image_sha256=sha(path),
                            input_sha256=hashlib.sha256(json.dumps(row['inputs'],sort_keys=True).encode()).hexdigest(),expected_bits=row['golden']['output_bits']))
    report=dict(status='INPUTS_ONLY',operator='p3',case_id='P3-MINI-01',clock_hz=100000000,bindings=bindings,samples=samples,
                note='One frozen representative case per seed; not all-case power coverage. Expected bits are external checker data, never DUT memory.')
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(out/'manifest.json'),sha256=sha(out/'manifest.json'))))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True);parser.add_argument('--run-tag')
    args=parser.parse_args();prepare(args.vectors.resolve(),args.run_tag)
