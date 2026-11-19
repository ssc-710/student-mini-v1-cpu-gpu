#!/usr/bin/env python3
"""Run protocol simulation and structural no-second-multiplier screening."""

import hashlib
import json
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RTL = BASE / "src/rtl/cpu_p3_vex_blocking_adapter.sv"
FINISH = BASE / "src/rtl/cpu_p3_scale_finish_staged.sv"
TB = BASE / "tests/cpu_p3_vex_blocking_adapter_tb.sv"
OUT = BASE / "runs/cpu-p3-vex-blocking-adapter-screen"
OUT.mkdir(parents=True, exist_ok=True)


def run(command, log_name):
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=300)
        log = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log = stdout + stderr + "\nTIMEOUT after 300 seconds\n"
        proc = subprocess.CompletedProcess(command, 124, stdout, stderr)
    (OUT / log_name).write_text(log, encoding="utf-8")
    return proc


compile_proc = run(
    ["iverilog", "-g2012", "-s", "cpu_p3_vex_blocking_adapter_tb",
     "-o", str(OUT / "simv"), str(FINISH), str(RTL), str(TB)],
    "compile.log",
)
sim_proc = run(["vvp", str(OUT / "simv")], "simulation.log") if compile_proc.returncode == 0 else None

ys = OUT / "structure.ys"
ys.write_text(
    f"read_verilog -sv {FINISH.as_posix()} {RTL.as_posix()}\n"
    "hierarchy -check -top cpu_p3_vex_blocking_adapter\n"
    "proc; opt; stat\n",
    encoding="utf-8",
)
yosys_proc = run(["yosys", "-s", str(ys)], "structure.log")
iverilog_version = run(["iverilog", "-V"], "iverilog-version.log")
yosys_version = run(["yosys", "-V"], "yosys-version.log")
structure_log = (OUT / "structure.log").read_text(encoding="utf-8")
simulation_log = (OUT / "simulation.log").read_text(encoding="utf-8") if sim_proc else ""

passed = (
    compile_proc.returncode == 0
    and sim_proc is not None and sim_proc.returncode == 0
    and "CPU_P3_VEX_BLOCKING_ADAPTER_PASS" in simulation_log
    and yosys_proc.returncode == 0
    and "$mul" not in structure_log
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


result = {
    "status": "CPU_P3_VEX_BLOCKING_ADAPTER_SCREEN_PASS" if passed else "FAIL",
    "simulation_return_code": None if sim_proc is None else sim_proc.returncode,
    "yosys_return_code": yosys_proc.returncode,
    "dut_contains_yosys_mul_cell": "$mul" in structure_log,
    "random_seed": "0x50335eed",
    "commands": {
        "compile": ["iverilog", "-g2012", "-s", "cpu_p3_vex_blocking_adapter_tb", "-o", "<run>/simv", "<finish>", "<adapter>", "<tb>"],
        "simulate": ["vvp", "<run>/simv"],
        "structure": ["yosys", "-s", "<run>/structure.ys"],
    },
    "bindings": {str(p.relative_to(BASE)): sha(p) for p in (RTL, FINISH, TB, Path(__file__), ys, OUT / "compile.log", OUT / "structure.log", OUT / "iverilog-version.log", OUT / "yosys-version.log") if p.exists()},
    "boundary": (
        "Standalone blocking integration oracle with an external MulPlugin boundary. "
        "Not injected into the monolithic VexRiscv core; no 330-case, root5, whole-core timing, PnR, or tokens/s claim."
    ),
}
if (OUT / "simulation.log").exists():
    result["bindings"][str((OUT / "simulation.log").relative_to(BASE))] = sha(OUT / "simulation.log")
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
if not passed:
    raise SystemExit(1)
