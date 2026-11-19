"""Audit the static ELF gate for the private native-ctx GC integration candidate."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
RUN = BASE / "runs/cpu-native-ctx-gc-layout-gate"
PARENT = BASE / "build/cpu-native-ctx-layout"
CANDIDATE = BASE / "build/cpu-native-ctx-gc"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol_table(path):
    text = path.read_text()
    result = {}
    for symbol in ["p3_native_candidate_ctx", "mini_native_scalar_expert", "mini_native_generate"]:
        match = re.search(rf"^([0-9a-f]+) ([0-9a-f]+) T {symbol}$", text, re.M)
        if match:
            result[symbol] = {"address": int(match[1], 16), "size": int(match[2], 16)}
    return result


parent_symbols = symbol_table(RUN / "cpu-native-ctx-layout.nm.txt")
candidate_symbols = symbol_table(RUN / "cpu-native-ctx-gc.nm.txt")
assert "mini_native_scalar_expert" in parent_symbols
assert "mini_native_scalar_expert" not in candidate_symbols
assert candidate_symbols["p3_native_candidate_ctx"]["address"] == 0x2ED0
assert candidate_symbols["mini_native_generate"]["address"] == 0x3B44

candidate_map = CANDIDATE / "soc/software/bios/bios.elf.map"
map_text = candidate_map.read_text(errors="replace")
discard = re.search(
    r"^ \.text\.mini_native_scalar_expert\s*$\n"
    r"\s+0x0+\s+0x([0-9a-f]+)\s+student_mini_native_nano\.o$",
    map_text,
    re.M,
)
assert discard and int(discard[1], 16) > 0

parent_bin = PARENT / "soc/software/bios/bios.bin"
candidate_bin = CANDIDATE / "soc/software/bios/bios.bin"
parent_elf = PARENT / "soc/software/bios/bios.elf"
candidate_elf = CANDIDATE / "soc/software/bios/bios.elf"
assert candidate_bin.stat().st_size < parent_bin.stat().st_size
assert candidate_elf.stat().st_size < parent_elf.stat().st_size

artifacts = [
    BASE / "tools/build_cpu.py",
    CANDIDATE / "build-binding.json",
    CANDIDATE / "bios/Makefile",
    CANDIDATE / "bios/student_mini_native_nano.c",
    parent_bin,
    candidate_bin,
    parent_elf,
    candidate_elf,
    PARENT / "soc/software/bios/bios.elf.map",
    candidate_map,
    CANDIDATE / "soc/gateware/sim_rom.init",
    CANDIDATE / "soc/gateware/obj_dir/Vsim",
    *sorted(RUN.glob("*.txt")),
]
assert all(path.is_file() for path in artifacts)

result = {
    "status": "NATIVE_CTX_GC_STATIC_LAYOUT_GATE_PASS",
    "parent": "cpu-native-ctx-layout",
    "candidate": "cpu-native-ctx-gc",
    "flags": ["-ffunction-sections", "-fdata-sections"],
    "existing_link_flag": "--gc-sections",
    "discarded": {
        "mini_native_scalar_expert_bytes": int(discard[1], 16),
        "evidence": "candidate bios.elf.map discarded input sections",
    },
    "symbols": {"parent": parent_symbols, "candidate": candidate_symbols},
    "sizes": {
        "parent_bios_bin": parent_bin.stat().st_size,
        "candidate_bios_bin": candidate_bin.stat().st_size,
        "bios_bin_reduction": parent_bin.stat().st_size - candidate_bin.stat().st_size,
        "parent_elf": parent_elf.stat().st_size,
        "candidate_elf": candidate_elf.stat().st_size,
        "elf_reduction": parent_elf.stat().st_size - candidate_elf.stat().st_size,
    },
    "decision": "ELF/ROM layout changed materially; allow one fresh root5 VexRiscv RTL screening run.",
    "attribution_boundary": (
        "Whole private BIOS translation units receive section splitting. Any measured benefit is "
        "P3 runtime integration/link-layout benefit, not P3 arithmetic, RTL front-end, Fmax or PPA."
    ),
    "bindings": {str(path.relative_to(ROOT)): sha(path) for path in artifacts},
}
(RUN / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
