"""SAT prove the one-cell CSA invariant used at every Wallace-tree node."""
import hashlib,json,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];out=BASE/'runs/gpu-radix11-csa-cell-formal';out.mkdir(exist_ok=False)
src=out/'miter.sv';src.write_text('''module m(input [65:0] x,y,z,output equal); wire [65:0] s=x^y^z; wire [65:0] c=((x&y)|(x&z)|(y&z))<<1; assign equal=(s+c)==(x+y+z); endmodule''')
cmd=['yosys','-Q','-T','-p',f'read_verilog -sv {src}; prep -top m; flatten; sat -verify -prove equal 1 -show-inputs']
with (out/'proof.log').open('x') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=120)
assert p.returncode==0 and 'SUCCESS' in (out/'proof.log').read_text()
(out/'receipt.json').write_text(json.dumps(dict(status='ARBITRARY_66BIT_CSA_CELL_SAT_PASS',command=cmd,
 bindings={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in [Path(__file__),src,out/'proof.log']},
 limitation='One arbitrary-width-preserving modulo-2^66 CSA identity. Repeated tree conservation follows by substitution; multiplier cell products remain RTL-tested, not exhaustively proven here.'),indent=2)+'\n')
print('P3_RADIX11_CSA_CELL_SAT_PASS')
