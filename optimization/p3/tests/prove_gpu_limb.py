"""Prove the new limb merge for all abstract partial-product bit patterns."""
import json
from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parents[1]
out=BASE/'runs/gpu-limb-formal';out.mkdir(parents=True,exist_ok=False)
source=out/'miter.v'
source.write_text('''module limb_miter(input [31:0] p00,input [32:0] p01,p10,input [33:0] p11,output equal);
wire [65:0] ref00={34'b0,p00};
wire [65:0] ref01={{17{p01[32]}},p01,16'b0};
wire [65:0] ref10={{17{p10[32]}},p10,16'b0};
wire [65:0] ref11={p11,32'b0};
wire [65:0] reference_sum=ref00+ref01+ref10+ref11;
wire [34:0] a={{2{p01[32]}},p01},b={{2{p10[32]}},p10},c={19'b0,p00[31:16]};
wire [34:0] carry=((a&b)|(a&c)|(b&c))<<1;
wire [34:0] mid=(a^b^c)+carry;
wire [33:0] upper=p11+{{15{mid[34]}},mid[34:16]};
wire [65:0] candidate_sum={upper,mid[15:0],p00[15:0]};
assign equal=reference_sum==candidate_sum;
endmodule
''')
cmd=['/usr/bin/yosys','-Q','-T','-p',f'read_verilog {source}; prep -top limb_miter; flatten; sat -verify -prove equal 1 -show-inputs']
with (out/'proof.log').open('x') as f:
    p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=120)
passed=p.returncode==0 and 'SUCCESS' in (out/'proof.log').read_text()
(out/'receipt.json').write_text(json.dumps(dict(status='ABSTRACT_MERGE_IDENTITY_PASS' if passed else 'FAIL',
    command=cmd,exit_code=p.returncode,scope='All 32/33/33/34-bit abstract partial products; not entire sequential multiplier/core proof'),indent=2)+'\n')
print('GPU_LIMB_MERGE_IDENTITY_PASS',passed);assert passed
