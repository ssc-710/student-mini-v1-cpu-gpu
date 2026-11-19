"""SAT-prove the radix-11 carry-save decomposition for arbitrary signed33 inputs."""
import hashlib,json,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];out=BASE/'runs/gpu-radix11-formal-v2';out.mkdir(exist_ok=False)
rtl='''module m(input signed [32:0] a,b,output equal);
wire signed [11:0] a0={1'b0,a[10:0]},a1={1'b0,a[21:11]}; wire signed [10:0] a2=a[32:22];
wire signed [11:0] b0={1'b0,b[10:0]},b1={1'b0,b[21:11]}; wire signed [10:0] b2=b[32:22];
wire signed [23:0] p00=a0*b0,p01=a0*b1,p02=a0*b2,p10=a1*b0,p11=a1*b1,p12=a1*b2,p20=a2*b0,p21=a2*b1,p22=a2*b2; wire signed [65:0] reference=a*b;
wire [65:0] r0={{42{p00[23]}},p00},r1={{42{p01[23]}},p01}<<11,r2={{42{p02[23]}},p02}<<22,r3={{42{p10[23]}},p10}<<11,r4={{42{p11[23]}},p11}<<22,r5={{42{p12[23]}},p12}<<33,r6={{42{p20[23]}},p20}<<22,r7={{42{p21[23]}},p21}<<33,r8={{42{p22[23]}},p22}<<44;
`define C(n,x,y,z) wire [65:0] n``s=(x)^(y)^(z); wire [65:0] n``c=(((x)&(y))|((x)&(z))|((y)&(z)))<<1
`C(c0,r0,r1,r2);`C(c1,r3,r4,r5);`C(c2,r6,r7,r8);`C(c3,c0s,c0c,c1s);`C(c4,c1c,c2s,c2c);`C(c5,c3s,c3c,c4s);`C(c6,c5s,c5c,c4c);
assign equal=(c6s+c6c)==reference; endmodule
'''
src=out/'miter.sv';src.write_text(rtl)
cmd=['yosys','-Q','-T','-p',f'read_verilog -sv {src}; prep -top m; flatten; sat -verify -prove equal 1 -show-inputs']
with (out/'proof.log').open('x') as f:p=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=180)
assert p.returncode==0 and 'SUCCESS' in (out/'proof.log').read_text()
(out/'receipt.json').write_text(json.dumps(dict(status='RADIX11_ARITHMETIC_SAT_PASS',command=cmd,
 bindings={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in [src,Path(__file__),out/'proof.log']},
 limitation='Combinational signed33 decomposition only; sequential enable latency is covered separately by RTL simulation.'),indent=2)+'\n')
print('P3_RADIX11_SAT_PASS')
