"""Exhaustive SAT proof of the 52-bit combinational arithmetic identity."""
import json
from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parents[1]
out=BASE/'runs/rtl-proof';out.mkdir(parents=True,exist_ok=True)
source=out/'csa_miter.v'
source.write_text('''module csa_miter(input [51:0] a,b,c,output equal);
wire [51:0] reference_sum=(a+b)+c;
wire [51:0] carry=((a&b)|(a&c)|(b&c))<<1;
wire [51:0] candidate_sum=(a^b^c)+carry;
assign equal=reference_sum==candidate_sum;
endmodule
''')
cmd=['yosys','-Q','-T','-p',f'read_verilog {source}; prep -top csa_miter; flatten; sat -verify -prove equal 1 -show-inputs']
with (out/'cpu-csa-proof.log').open('w') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=120)
text=(out/'cpu-csa-proof.log').read_text()
passed=p.returncode==0 and 'SUCCESS' in text
(out/'cpu-csa-result.json').write_text(json.dumps(dict(status='COMBINATIONAL_IDENTITY_PASS' if passed else 'FAIL',
    command=cmd,exit_code=p.returncode,scope='Arbitrary 52-bit a/b/c only; full core and timing not proven'),indent=2)+'\n')
print('CPU_CSA_IDENTITY_PASS',passed)
if not passed:raise SystemExit(1)
