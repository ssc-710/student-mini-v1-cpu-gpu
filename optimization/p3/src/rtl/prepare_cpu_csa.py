"""Preserve the core interface/cycles while compressing three multiplier terms."""
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parents[2];ROOT=BASE.parents[1]
source=ROOT/'rerun_sqrt3/VexRiscv_Full_4k.v'
text=source.read_text()
old='  assign memory_MUL_LOW = ($signed(_zz_memory_MUL_LOW) + $signed(_zz_memory_MUL_LOW_6));'
assert text.count(old)==1
new='''  wire [51:0] p3_mul_a = _zz_memory_MUL_LOW_2;
  wire [51:0] p3_mul_b = _zz_memory_MUL_LOW_4;
  wire [51:0] p3_mul_c = _zz_memory_MUL_LOW_6;
  wire [51:0] p3_mul_sum = p3_mul_a ^ p3_mul_b ^ p3_mul_c;
  wire [51:0] p3_mul_carry = ((p3_mul_a & p3_mul_b) | (p3_mul_a & p3_mul_c) | (p3_mul_b & p3_mul_c)) << 1;
  assign memory_MUL_LOW = p3_mul_sum + p3_mul_carry;'''
out=BASE/'build/rtl-csa';out.mkdir(parents=True,exist_ok=True)
dest=out/'VexRiscv_Full_4k.v';dest.write_text(text.replace(old,new))
(out/'binding.json').write_text(json.dumps(dict(status='CANDIDATE_NOT_TARGET_VERIFIED',
    original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    candidate_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
    change='52-bit modulo-equivalent carry-save compression; same registers, stalls, ISA and cycles'),indent=2)+'\n')
print(dest)
