#!/usr/bin/env python3
"""Fail-closed aggregate audit for five fresh paired GPU P3 counter runs."""

import hashlib
import json
import re
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
WORKSPACE = BASE.parents[1]
OUT = BASE / "runs" / "gpu-p3-counter-v1-qualified-repeat5"
RUNS = [BASE / "runs" / f"gpu-p3-counter-v1-qualified-pair-{index:02d}" for index in range(1, 6)]
PARENTS = {
    "baseline": BASE / "runs" / "gpu-baseline-driver-retry" / "execute.log",
    "candidate": BASE / "runs" / "gpu-algorithm-abs-fix" / "execute.log",
}
PROFILE_RE = re.compile(
    r"^P3_CYCLE_PROFILE abi=(\d+) routed_calls=(\d+) shared_calls=(\d+) "
    r"failed_calls=(\d+) routed_cycles=(\d+) shared_cycles=(\d+) "
    r"empty_cycles=(\d+) commit=([0-9a-fA-F]{8})$",
    re.MULTILINE,
)
PERF_RE = re.compile(r"^PERF: instrs=(\d+), cycles=(\d+), IPC=([0-9.]+)$", re.MULTILINE)
COMPLETE_RE = re.compile(
    r"^STUDENT_NATIVE_GPU_COMPLETE count=(\d+) p1=(\d+) p2=(\d+) p3=(\d+)$", re.MULTILINE
)
CLOCK_GROUP_RE = re.compile(
    r"0000700b[^\n]*<unknown>[^\n]*\n"
    r"[^\n]+\tcsrr\t[^,\n]+, mcycleh[^\n]*\n"
    r"[^\n]+\tcsrr\t[^,\n]+, mcycle[^\n]*\n"
    r"[^\n]+\tcsrr\t[^,\n]+, mcycleh"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one_match(pattern, text, label):
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise AssertionError(f"{label}: expected one match, found {len(matches)}")
    return matches[0]


def semantic_lines(text):
    lines = [line for line in text.splitlines() if line.startswith("STUDENT_NATIVE_TOKEN ")]
    if len(lines) != 11:
        raise AssertionError(f"expected 11 token/state lines, found {len(lines)}")
    return lines


def audit_variant(run, variant, receipt):
    receipt_variant = receipt["variants"][variant]
    assert receipt_variant["exit_code"] == 0
    assert receipt_variant["synchronized_cycle_read_groups"] == 6
    for relative, expected in receipt_variant["artifacts"].items():
        artifact = WORKSPACE / relative
        assert artifact.is_file(), f"missing artifact: {relative}"
        assert sha256(artifact) == expected, f"hash mismatch: {relative}"

    log = run / variant / "execute.log"
    text = log.read_text(encoding="utf-8", errors="strict")
    profile_values = one_match(PROFILE_RE, text, f"{run.name}/{variant} profile")
    abi, routed, shared, failed, routed_cycles, shared_cycles, empty_cycles, commit = profile_values
    profile = {
        "abi": int(abi),
        "routed_calls": int(routed),
        "shared_calls": int(shared),
        "failed_calls": int(failed),
        "routed_cycles": int(routed_cycles),
        "shared_cycles": int(shared_cycles),
        "empty_cycles": int(empty_cycles),
        "commit_magic": commit.lower(),
    }
    assert profile["abi"] == 1 and profile["commit_magic"] == "50334331"
    assert (profile["routed_calls"], profile["shared_calls"], profile["failed_calls"]) == (20, 20, 0)
    assert profile["routed_calls"] + profile["shared_calls"] == 40
    assert profile["routed_cycles"] > 0 and profile["shared_cycles"] > 0
    assert profile["empty_cycles"] == 234

    instructions, full_cycles, ipc = one_match(PERF_RE, text, f"{run.name}/{variant} perf")
    complete = tuple(map(int, one_match(COMPLETE_RE, text, f"{run.name}/{variant} completion")))
    assert complete == (11, 1, 10, 40)
    full_cycles = int(full_cycles)
    isolated_total = profile["routed_cycles"] + profile["shared_cycles"]
    assert isolated_total < full_cycles

    tokens = semantic_lines(text)
    parent_tokens = semantic_lines(PARENTS[variant].read_text(encoding="utf-8", errors="strict"))
    assert tokens == parent_tokens

    disassembly_path = run / variant / "device" / "device.dis"
    disassembly = disassembly_path.read_text(encoding="utf-8", errors="strict")
    clock_groups = CLOCK_GROUP_RE.findall(disassembly)
    assert len(clock_groups) == 6, f"{run.name}/{variant}: expected six synchronized clock groups"

    return {
        "profile": profile,
        "isolated_total_cycles": isolated_total,
        "full_simx": {"instructions": int(instructions), "cycles": full_cycles, "ipc": float(ipc)},
        "semantic_steps_match_parent": len(tokens),
        "synchronized_cycle_read_groups": len(clock_groups),
        "receipt_sha256": sha256(run / "receipt.json"),
        "log_sha256": sha256(log),
        "device_disassembly_sha256": sha256(disassembly_path),
        "semantic_lines": tokens,
    }


def stable_projection(record):
    return {
        "profile": record["profile"],
        "isolated_total_cycles": record["isolated_total_cycles"],
        "full_simx": record["full_simx"],
        "synchronized_cycle_read_groups": record["synchronized_cycle_read_groups"],
    }


def main():
    records = []
    first = None
    for run in RUNS:
        assert run.is_dir(), f"missing run directory: {run}"
        receipt = json.loads((run / "receipt.json").read_text(encoding="utf-8"))
        record = {variant: audit_variant(run, variant, receipt) for variant in ("baseline", "candidate")}
        assert record["baseline"]["semantic_lines"] == record["candidate"]["semantic_lines"]
        stable = {variant: stable_projection(record[variant]) for variant in ("baseline", "candidate")}
        if first is None:
            first = stable
        else:
            assert stable == first, f"counter instability in {run.name}"
        records.append({
            "run": run.name,
            "baseline": {key: value for key, value in record["baseline"].items() if key != "semantic_lines"},
            "candidate": {key: value for key, value in record["candidate"].items() if key != "semantic_lines"},
        })

    baseline_cycles = first["baseline"]["isolated_total_cycles"]
    candidate_cycles = first["candidate"]["isolated_total_cycles"]
    speedup = baseline_cycles / candidate_cycles
    expected_speedup = 1.0509572645055183
    assert abs(speedup - expected_speedup) < 1e-12

    result = {
        "schema": 1,
        "status": "PASS",
        "measurement_scope": "bracketed-inclusive P3 cycles from Vortex SimX device mcycle CSR",
        "not_claimed": [
            "physical GPU token/s",
            "Vortex RTLSIM cycle speedup",
            "four-thread cooperative microkernel speedup",
            "Fmax, WNS, area, power, or full-chip PPA",
        ],
        "fresh_pair_count": len(records),
        "all_pair_counters_identical": True,
        "all_token_hidden_logits_exact_to_parents": True,
        "baseline_isolated_cycles": baseline_cycles,
        "candidate_isolated_cycles": candidate_cycles,
        "candidate_over_baseline_isolated_speedup": speedup,
        "candidate_isolated_cycle_reduction_percent": (baseline_cycles - candidate_cycles) * 100.0 / baseline_cycles,
        "pairs": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "result.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
