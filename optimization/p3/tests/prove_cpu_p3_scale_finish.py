"""SAT-check the optimized post-multiply scale/round/saturate unit."""
import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[1]
RTL = BASE / "src/rtl/cpu_p3_scale_apply.sv"
RUN = BASE / "runs/cpu-p3-scale-finish-formal"
assert not RUN.exists(), "formal evidence directory must be fresh"
RUN.mkdir(parents=True)

miter = RUN / "miter.sv"
miter.write_text(r'''
module cpu_p3_scale_finish_miter(
    input logic negative,
    input logic [55:0] product,
    input logic signed [5:0] shift,
    output logic valid_domain,
    output logic equal_when_valid
);
    wire signed [15:0] candidate;
    cpu_p3_scale_finish dut(negative, product, shift, candidate);
    logic [63:0] scaled, q, remainder, mask, half;
    logic signed [15:0] reference;
    integer s;
    always_comb begin
        valid_domain = shift >= -28 && shift <= 4;
        scaled = 0; q = 0; remainder = 0; mask = 0; half = 0; s = 0;
        if (shift >= 0) begin
            scaled = {8'd0, product} << shift;
        end else begin
            s = -shift;
            q = {8'd0, product} >> s;
            mask = (64'd1 << s) - 1;
            remainder = {8'd0, product} & mask;
            half = 64'd1 << (s - 1);
            scaled = q + (remainder > half || (remainder == half && q[0]));
        end
        if (negative)
            reference = scaled >= 32768 ? -16'sd32768 : -$signed(scaled[15:0]);
        else
            reference = scaled >= 32767 ? 16'sd32767 : $signed(scaled[15:0]);
        equal_when_valid = !valid_domain || candidate == reference;
    end
endmodule
''')

log = RUN / "prove.log"
script = (
    f"read_verilog -sv {RTL} {miter}; "
    "prep -top cpu_p3_scale_finish_miter; flatten; "
    "sat -verify -prove equal_when_valid 1 -set-def-inputs "
    "-show negative,product,shift,candidate,reference"
)
with log.open("w") as stream:
    process = subprocess.run(["yosys", "-Q", "-T", "-p", script],
                             stdout=stream, stderr=subprocess.STDOUT, timeout=300)
text = log.read_text()
passed = process.returncode == 0 and "SUCCESS" in text
result = {
    "status": "CPU_P3_PREPARED_SCALE_FINISH_SAT_PASS" if passed else "FAIL",
    "exit_code": process.returncode,
    "proven_domain": "arbitrary sign and uint56 product, signed shift in [-28,4]",
    "rtl_sha256": hashlib.sha256(RTL.read_bytes()).hexdigest(),
    "boundary": (
        "Proves post-multiply shift, RNE ties-even, sign and int16 saturation only. "
        "The exact uint32*uint24 multiplier is structural RTL; pipeline protocol, VexRiscv integration, "
        "frozen P3 cases, LLM cycles and physical timing remain unqualified."
    ),
}
(RUN / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if not passed:
    raise SystemExit(1)
