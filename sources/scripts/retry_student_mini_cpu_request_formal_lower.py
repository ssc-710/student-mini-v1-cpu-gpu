"""Lower modern Yosys check cells without removing or weakening assertions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source,root):
    edits={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'paths=[Path(__file__),rtl,bench,tool,':"paths=[Path(__file__),ROOT/'scripts/prove_student_mini_cpu_request_formal.py',ROOT/'scripts/retry_student_mini_cpu_request_formal_lower.py',rtl,bench,tool,",
        r'prep -top contract -flatten\nsat -verify':r'prep -top contract -flatten\nchformal -lower\nsat -verify',
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('formal lowering seam changed')
        source=source.replace(old,new)
    return source


def main():
    original=ROOT/'scripts/prove_student_mini_cpu_request_formal.py'
    bindings={str(p):sha(p) for p in (Path(__file__),original)}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-request-formal-lowering'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings),indent=2)+'\n');verify(bindings)
    with (work/'proof.log').open('x') as log:code=subprocess.call([sys.executable,str(producer)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'proof.log').read_text().splitlines() if x.startswith('{')]
    result=dict(status='HOLD',bindings=bindings,physical_evidence_complete=False,formal_baseline=False)
    if rows:result['proof']=rows[-1]
    verify(bindings)
    if not code and result.get('proof',{}).get('status')=='CPU_ROM_REQUEST_BOUNDED_FORMAL_STAGE_PASS':
        result['status']='CPU_ROM_REQUEST_FORMAL_LOWERING_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('proof'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
