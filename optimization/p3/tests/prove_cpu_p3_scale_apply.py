"""SAT-check the prepared-scale combinational RTL against its exact contract."""
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[1]
RTL = BASE / "src/rtl/cpu_p3_scale_apply.sv"
RUN = BASE / "runs/cpu-p3-scale-apply-formal"
assert not RUN.exists(), "formal evidence directory must be fresh"
RUN.mkdir(parents=True)

miter = RUN / "miter.sv"
miter.write_text(r'''
module cpu_p3_scale_apply_miter(
    input logic signed [31:0] value,
    input logic [23:0] significand,
    input logic signed [5:0] shift,
    output logic equal
);
    wire signed [15:0] candidate;
    cpu_p3_scale_apply_comb dut(value, significand, shift, candidate);
    logic [31:0] magnitude;
    logic [63:0] product, expected_scaled, q, r, half, mask;
    logic signed [15:0] reference;
    integer s;
    always_comb begin
        magnitude = value[31] ? (32'd0 - value[31:0]) : value[31:0];
        product = magnitude * significand;
        expected_scaled = 0; q = 0; r = 0; half = 0; mask = 0; s = 0;
        if (shift >= 0) begin
            expected_scaled = product << shift;
        end else begin
            s = -shift;
            q = product >> s;
            mask = (64'd1 << s) - 1;
            r = product & mask;
            half = 64'd1 << (s - 1);
            expected_scaled = q + (r > half || (r == half && q[0]));
        end
        if (value[31])
            reference = expected_scaled >= 32768 ? -16'sd32768 : -$signed(expected_scaled[15:0]);
        else
            reference = expected_scaled >= 32767 ? 16'sd32767 : $signed(expected_scaled[15:0]);
        equal = candidate == reference;
    end
endmodule
''')

log = RUN / "prove.log"
script = (
    f"read_verilog -sv {RTL} {miter}; "
    "prep -top cpu_p3_scale_apply_miter; flatten; "
    "sat -verify -prove equal 1 "
    "-set-def-inputs -set-assumes "
    "-show value,significand,shift,candidate,reference"
)
timed_out = False
with log.open("w") as stream:
    try:
        process = subprocess.run(["yosys", "-Q", "-T", "-p", script],
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=300)
    except subprocess.TimeoutExpired:
        timed_out = True
        process = subprocess.CompletedProcess([], 124)
text = log.read_text()
passed = process.returncode == 0 and "SUCCESS" in text
result = {
    "status": "CPU_P3_PREPARED_SCALE_COMBINATIONAL_SAT_PASS" if passed else "FAIL",
    "exit_code": process.returncode,
    "timed_out": timed_out,
    "domain": {
        "value": "arbitrary signed int32",
        "significand": "arbitrary uint24; software-qualified contexts use [0x800000,0xffffff]",
        "shift": "arbitrary signed 6-bit; integration must constrain to [-28,4]",
    },
    "boundary": (
        "Combinational arithmetic equivalence only. Pipeline protocol, VexRiscv decode/hazard/flush, "
        "330 frozen P3 records, root5 cycles, and macro-aware physical timing are not proven."
    ),
}
(RUN / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if not passed:
    raise SystemExit(1)
