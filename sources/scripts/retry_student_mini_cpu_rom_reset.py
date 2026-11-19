"""Strengthen the local ROM proof after a reset mutation survived its test."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def stronger_bench(text):
    marker='    $display("ROM_REQUEST_CUT_PASS seeds=10 transactions=%0d cancel_reset_recovery=20",checks);'
    probe='''    // Keep the request asserted through reset. Masking ACK during reset
    // alone is not enough: the pending state must actually be discarded.
    @(negedge clk);address=55;cyc=1;stb=1;
    @(posedge clk);#1;if(ack) $fatal(1,"held reset setup early ACK");
    @(negedge clk);reset=1;
    @(posedge clk);#1;if(ack) $fatal(1,"held reset ACK");
    @(negedge clk);reset=0;address=56;
    #1;if(ack) $fatal(1,"stale ACK immediately after reset release");
    @(posedge clk);#1;
    if(ack || rom_address!==56) $fatal(1,"fresh request not captured after reset");
    @(posedge clk);#1;
    if(!ack || rom_address!==56) $fatal(1,"fresh response missing after reset");
'''
    if text.count(marker)!=1:raise ValueError('reset test extension seam changed')
    return text.replace(marker,probe+marker)


def derive(source, bench, root):
    edits={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        "handshake=ROOT/'tests/rtl/student_mini_cpu_rom_request_cut_tb.sv'":'handshake=Path('+repr(str(bench))+')',
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/prove_student_mini_cpu_rom_request.py',ROOT/'scripts/retry_student_mini_cpu_rom_reset.py',",
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('proof retry seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mapping',type=Path,required=True)
    args=parser.parse_args()
    original=ROOT/'scripts/prove_student_mini_cpu_rom_request.py'
    old_bench=ROOT/'tests/rtl/student_mini_cpu_rom_request_cut_tb.sv'
    bindings={str(p):sha(p) for p in (Path(__file__),original,old_bench,args.mapping.resolve()/'completion.json')}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-request-reset-proof'/key;work.mkdir(parents=True,exist_ok=False)
    bench=work/'reset-held-bench.sv';bench.write_text(stronger_bench(old_bench.read_text()))
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),bench,ROOT))
    bindings.update({str(p):sha(p) for p in (bench,producer)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    with (work/'proof.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--mapping',str(args.mapping.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'proof.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['proof']=rows[-1]
    verify(bindings)
    if not code and result.get('proof',{}).get('status')=='CPU_ROM_REQUEST_LOCAL_PROOF_STAGE_PASS':
        result['status']='CPU_ROM_REQUEST_RESET_QUALIFIED_LOCAL_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('proof'))),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_RESET_QUALIFIED_LOCAL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
