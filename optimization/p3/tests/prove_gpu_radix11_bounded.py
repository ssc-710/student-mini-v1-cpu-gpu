"""Bounded SAT gates: signed limb reconstruction and arbitrary-row CSA conservation."""
import hashlib,json,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];out=BASE/'runs/gpu-radix11-formal-bounded';out.mkdir(exist_ok=False)
sources={
'limbs':'''module m(input signed [32:0] a,output equal); wire signed [11:0] a0={1'b0,a[10:0]},a1={1'b0,a[21:11]}; wire signed [10:0] a2=a[32:22]; wire signed [32:0] x0=a0,x1=a1,x2=a2; wire signed [32:0] rebuilt=x0+(x1<<<11)+(x2<<<22); assign equal=rebuilt==a; endmodule''',
'csa':'''module m(input [65:0] r0,r1,r2,r3,r4,r5,r6,r7,r8,output equal);
`define C(n,x,y,z) wire [65:0] n``s=(x)^(y)^(z); wire [65:0] n``c=(((x)&(y))|((x)&(z))|((y)&(z)))<<1
`C(c0,r0,r1,r2);`C(c1,r3,r4,r5);`C(c2,r6,r7,r8);`C(c3,c0s,c0c,c1s);`C(c4,c1c,c2s,c2c);`C(c5,c3s,c3c,c4s);`C(c6,c5s,c5c,c4c);
wire [65:0] reference=r0+r1+r2+r3+r4+r5+r6+r7+r8; assign equal=(c6s+c6c)==reference; endmodule'''}
records={}
for name,rtl in sources.items():
 src=out/(name+'.sv');src.write_text(rtl)
 cmd=['yosys','-Q','-T','-p',f'read_verilog -sv {src}; prep -top m; flatten; sat -verify -prove equal 1 -show-inputs']
 with (out/(name+'.log')).open('x') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=120)
 assert p.returncode==0 and 'SUCCESS' in (out/(name+'.log')).read_text()
 records[name]=dict(command=cmd,log_sha256=hashlib.sha256((out/(name+'.log')).read_bytes()).hexdigest())
(out/'receipt.json').write_text(json.dumps(dict(status='RADIX11_BOUNDED_SAT_PASS',records=records,
 bindings={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*[out/(n+'.sv') for n in sources]]},
 limitation='Proves signed limb reconstruction and CSA conservation for arbitrary rows. It does not prove the nine multiplier cells equal signed33 multiplication; end-to-end coverage is randomized RTL, not exhaustive formal equivalence.'),indent=2)+'\n')
print('P3_RADIX11_BOUNDED_SAT_PASS')
