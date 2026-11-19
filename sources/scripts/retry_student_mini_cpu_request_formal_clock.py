"""Use the pinned Yosys-required edge-check normalization before lowering."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.retry_student_mini_cpu_request_formal_lower import derive


def main():
    original=ROOT/'scripts/prove_student_mini_cpu_request_formal.py'
    lower=ROOT/'scripts/retry_student_mini_cpu_request_formal_lower.py'
    bindings={str(p):sha(p) for p in (Path(__file__),original,lower)}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-request-formal-clock'/key;work.mkdir(parents=True,exist_ok=False)
    text=derive(original.read_text(),ROOT)
    old=r'\nchformal -lower\nsat -verify'
    if text.count(old)!=1:raise ValueError('edge normalization seam changed')
    text=text.replace(old,r'\nasync2sync\nchformal -lower\nsat -verify')
    old='paths=[Path(__file__),'
    if text.count(old)!=1:raise ValueError('formal clock binding seam changed')
    text=text.replace(old,old+"ROOT/'scripts/retry_student_mini_cpu_request_formal_clock.py',")
    producer=work/'producer.py';producer.write_text(text);bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    with (work/'proof.log').open('x') as log:code=subprocess.call([sys.executable,str(producer)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'proof.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['proof']=rows[-1]
    verify(bindings)
    if not code and result.get('proof',{}).get('status')=='CPU_ROM_REQUEST_BOUNDED_FORMAL_STAGE_PASS':
        packet=Path(result['proof']['work'])/'completion.json';child=json.loads(packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(packet)]=sha(packet)
        result['status']='CPU_ROM_REQUEST_FORMAL_CLOCK_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('proof'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
