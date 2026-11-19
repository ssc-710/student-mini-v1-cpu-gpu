#!/usr/bin/env python3
"""Prove reduced guard/sticky finish equivalent on the legal shift domain."""

import hashlib
import json
import subprocess
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
ORIGINAL = BASE / "src" / "rtl" / "cpu_p3_scale_apply.sv"
STAGED = BASE / "src" / "rtl" / "cpu_p3_scale_finish_staged.sv"
OUT = BASE / "runs" / "cpu-p3-scale-finish-staged-formal-retry"
OUT.mkdir(parents=True, exist_ok=True)
MITER = OUT / "miter.sv"
MITER.write_text(
    """module cpu_p3_scale_finish_staged_miter(
  input logic negative,
  input logic [55:0] product,
  input logic signed [5:0] shift
);
  logic signed [15:0] reference_result, candidate_result;
  cpu_p3_scale_finish reference(negative, product, shift, reference_result);
  cpu_p3_scale_finish_reduced candidate(negative, product, shift, candidate_result);
  always @* if ($signed(shift) >= -28 && $signed(shift) <= 4)
    assert(reference_result == candidate_result);
endmodule
""",
    encoding="utf-8",
)
script = OUT / "prove.ys"
script.write_text(
    f"read_verilog -sv {ORIGINAL.as_posix()} {STAGED.as_posix()} {MITER.as_posix()}\n"
    "prep -top cpu_p3_scale_finish_staged_miter; flatten\n"
    "sat -verify -prove-asserts -set-def-inputs\n",
    encoding="utf-8",
)
proc = subprocess.run(["yosys", "-s", str(script)], capture_output=True, text=True, timeout=300)
(OUT / "prove.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
passed = proc.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in proc.stdout
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
result = {
    "status": "CPU_P3_SCALE_FINISH_STAGED_EQUIVALENCE_SAT_PASS" if passed else "FAIL",
    "legal_shift_domain": [-28, 4],
    "return_code": proc.returncode,
    "bindings": {
        str(path.relative_to(BASE)): sha(path)
        for path in (ORIGINAL, STAGED, MITER, script, OUT / "prove.log")
    },
    "boundary": "Post-multiply arithmetic equivalence only; no Vex decode/hazard, 330 cases, root5 cycles, or physical qualification.",
}
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
if not passed:
    raise SystemExit(1)
