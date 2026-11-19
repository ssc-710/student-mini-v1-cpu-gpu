#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
RUN_NAME = os.environ.get("P3_COUNTER_RUN", "gpu-p3-counter-v1-qualified-pair-01")
RUN = BASE / "runs" / RUN_NAME
PARENTS = {
    "baseline": BASE / "runs" / "gpu-baseline-driver-retry" / "execute.log",
    "candidate": BASE / "runs" / "gpu-algorithm-abs-fix" / "execute.log",
}
PROFILE = re.compile(
    r"P3_CYCLE_PROFILE abi=(\d+) routed_calls=(\d+) shared_calls=(\d+) failed_calls=(\d+) "
    r"routed_cycles=(\d+) shared_cycles=(\d+) empty_cycles=(\d+) commit=([0-9a-fA-F]+)"
)


def semantic_lines(text):
    return [line for line in text.splitlines() if line.startswith("STUDENT_NATIVE_TOKEN ")]


def main():
    receipt = json.loads((RUN / "receipt.json").read_text())
    result = {"schema": 1, "status": "PASS", "cycle_semantics": "bracketed-inclusive", "variants": {}}
    for name, parent_path in PARENTS.items():
        text = (RUN / name / "execute.log").read_text()
        parent = parent_path.read_text()
        matches = PROFILE.findall(text)
        assert len(matches) == 1
        abi, routed, shared, failed, routed_cycles, shared_cycles, empty_cycles, magic = matches[0]
        values = {"abi": int(abi), "routed_calls": int(routed), "shared_calls": int(shared),
                  "failed_calls": int(failed), "routed_cycles": int(routed_cycles),
                  "shared_cycles": int(shared_cycles), "empty_cycles": int(empty_cycles),
                  "commit_magic": magic.lower()}
        assert values["abi"] == 1 and values["commit_magic"] == "50334331"
        assert (values["routed_calls"], values["shared_calls"], values["failed_calls"]) == (20, 20, 0)
        assert values["routed_calls"] + values["shared_calls"] == 40
        assert values["routed_cycles"] > 0 and values["shared_cycles"] > 0 and values["empty_cycles"] > 0
        assert semantic_lines(text) == semantic_lines(parent)
        disassembly = (RUN / name / "device" / "device.dis").read_text()
        clock_groups = re.findall(
            r"0000700b[^\n]*<unknown>[^\n]*\n"
            r"[^\n]+\tcsrr\t[^,\n]+, mcycleh[^\n]*\n"
            r"[^\n]+\tcsrr\t[^,\n]+, mcycle[^\n]*\n"
            r"[^\n]+\tcsrr\t[^,\n]+, mcycleh",
            disassembly,
        )
        assert len(clock_groups) >= 6
        complete = re.findall(r"STUDENT_NATIVE_GPU_COMPLETE count=(\d+) p1=(\d+) p2=(\d+) p3=(\d+)", text)
        assert complete == [("11", "1", "10", "40")]
        full_cycles = int(re.findall(r"PERF: instrs=\d+, cycles=(\d+)", text)[-1])
        assert values["routed_cycles"] + values["shared_cycles"] <= full_cycles
        values["full_simx_cycles"] = full_cycles
        values["semantic_parent"] = str(parent_path.relative_to(BASE))
        values["semantic_steps_match"] = 11
        values["synchronized_cycle_read_groups"] = len(clock_groups)
        result["variants"][name] = values
    result["candidate_over_baseline_isolated_speedup"] = (
        (result["variants"]["baseline"]["routed_cycles"] + result["variants"]["baseline"]["shared_cycles"])
        / (result["variants"]["candidate"]["routed_cycles"] + result["variants"]["candidate"]["shared_cycles"])
    )
    result["receipt_variants"] = sorted(receipt["variants"])
    (RUN / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
