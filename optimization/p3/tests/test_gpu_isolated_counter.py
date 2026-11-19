#!/usr/bin/env python3
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def main():
    receipt = json.loads((BUILD / "gpu-p3-counter-preparation.json").read_text(encoding="utf-8"))
    sources = {}
    for name in ("baseline", "candidate"):
        path = ROOT / receipt["variants"][name]["source"]
        text = path.read_text(encoding="utf-8")
        sources[name] = text
        assert text.count("native_nano_kernel<<<1,1>>>") == 1
        assert text.count("P3_CYCLE_PROFILE abi=") == 1
        assert text.count("P3_COMMIT_PROFILE();return -3") == 2
        assert text.count("++p3_routed_calls") == 1
        assert text.count("++p3_shared_calls") == 1
        assert text.count("volatile p3_cycle_profile *p3_out") == 1
        assert text.count("p3_out->commit_magic=P3_CYCLE_PROFILE_COMMIT_MAGIC") == 1
        commit = text.index("p3_out->commit_magic=P3_CYCLE_PROFILE_COMMIT_MAGIC")
        assert text.index("p3_out->empty_cycles_hi") < commit
        assert "VX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4" in (path.parent / "Makefile").read_text(encoding="utf-8")
        assert text.count("__spirv_ReadClockKHR(1u)") == 2
    normalized = {}
    for name, text in sources.items():
        block = re.search(r"uint64_t p3_routed_cycles=0.*?#undef P3_COMMIT_PROFILE", text, re.S).group(0)
        block = block.replace("mini_native_scalar_expert", "P3_EXPERT").replace("p3_native_candidate", "P3_EXPERT")
        normalized[name] = block
    assert normalized["baseline"] == normalized["candidate"]
    assert struct.calcsize("<11I") == 44
    print("gpu isolated counter static qualification: PASS")


if __name__ == "__main__":
    main()
