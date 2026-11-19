#!/usr/bin/env python3
"""Static synchronization qualification and native fixed-Q6 host differential."""

import json
import re
import subprocess
import sys
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
WORKSPACE = BASE.parents[1]
HEADER = BASE / "src" / "p3_gpu_4thread_kernel.cuh"


def check_static() -> None:
    text = HEADER.read_text(encoding="utf-8")
    assert "template <bool Candidate>" in text
    assert text.count("__global__ void p3_gpu_4thread_kernel") == 1
    assert text.count("__syncthreads();") == 5
    assert "const unsigned first = tid * 4u;" in text
    assert "const bool publish = tid == 0u;" in text
    assert text.count("\n    if (publish) {\n") == 3
    assert text.count("for (unsigned k = 0; k < 16u; ++k)") == 3
    assert "__shared__ volatile int8_t intermediate0" in text
    assert "intermediate15" in text
    assert "__shared__ unsigned error_mask" in text
    assert "__shared__ unsigned stop" in text
    assert "__shared__ volatile unsigned lane_error0" in text
    assert "lane_error0 = lane_error1 = lane_error2 = lane_error3" in text
    assert "if (!stop && tid < 4u)" in text
    assert text.count("if (!stop && tid < 4u)") == 2
    assert "if (tid < 1u)" not in text
    assert "lane_error[tid]" not in text
    assert "const unsigned lane_result = Candidate" in text
    assert "error_mask |= lane_error0 | lane_error1 | lane_error2 | lane_error3;" in text
    assert "atomicOr" not in text
    assert "if (status) *status = error_mask;" in text
    assert "if (completed) *completed = stop ? 0u : 1u;" in text
    kernel = re.search(r"template <bool Candidate>\s+__global__ void.*?\n}\n#endif", text, re.S)
    assert kernel is not None
    assert "return;" not in kernel.group(0)


def check_golden_inventory() -> None:
    vectors = []
    with (WORKSPACE / "data" / "golden" / "vectors.jsonl").open(encoding="utf-8") as stream:
        vectors = [json.loads(line) for line in stream if line.strip()]
    p3 = [row for row in vectors if row["case"]["operator"] == "p3"]
    assert len(p3) == 330
    cases = {row["case"]["id"] for row in p3}
    assert cases == {f"P3-MINI-{index:02d}" for index in range(1, 34)}
    for case in cases:
        assert sorted(row["seed"] for row in p3 if row["case"]["id"] == case) == list(range(1, 11))


def main() -> None:
    check_static()
    check_golden_inventory()
    subprocess.run([sys.executable, str(BASE / "tools" / "prepare_gpu_p3_4thread.py")], check=True)
    receipt = json.loads((BASE / "runs" / "gpu-p3-4thread-host-reference" / "receipt.json").read_text())
    assert receipt["status"] == "PASS"
    assert "calls=1536" in receipt["stdout"]
    print("gpu P3 4-thread static/native-host qualification: PASS")


if __name__ == "__main__":
    main()
