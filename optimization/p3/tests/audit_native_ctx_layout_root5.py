"""Audit the fresh native-ctx-layout VexRiscv RTL root5 execution."""
import hashlib
import json
from pathlib import Path
import re


BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
BUILD = BASE / "build/cpu-native-ctx-layout"
RUN = BASE / "runs/cpu-native-ctx-layout-root5-fresh"
PARENT_RUN = BASE / "runs/cpu-native-ctx-root5-fresh"
MODE3 = BASE / "runs/cpu-ablation-v2/comparison-audited.json"
IMAGE = ROOT / "rerun_sqrt5/image"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic(line):
    return re.sub(r" elapsed_cycles=\d+:\d+", "", line)


def u64(hi, lo):
    return (int(hi) << 32) + int(lo)


log = RUN / "execute.log"
receipt_path = RUN / "execute.receipt.json"
receipt = json.loads(receipt_path.read_text())
text = log.read_text(errors="replace")
assert receipt["completion_marker_observed"] is True
assert receipt["log_sha256"] == sha(log)
assert text.count("STUDENT_NATIVE_CPU status=0 count=11") == 1
assert text.count("STUDENT_NATIVE_CPU_COMPLETE count=11 p1=1 p2=10 p3=40") == 1

states = [line for line in text.splitlines() if line.startswith("STUDENT_NATIVE_TOKEN ")]
parent_states = [
    line for line in (PARENT_RUN / "execute.log").read_text(errors="replace").splitlines()
    if line.startswith("STUDENT_NATIVE_TOKEN ")
]
mode3 = json.loads(MODE3.read_text())
mode3_states = next(row for row in mode3["records"] if row["mode"] == 3)["states"]
assert len(states) == len(parent_states) == len(mode3_states) == 11
assert [semantic(line) for line in states] == [semantic(line) for line in parent_states]
assert [semantic(line) for line in states] == [semantic(line) for line in mode3_states]

rows = []
for line in states:
    fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
    rows.append(
        {
            "step": int(fields["step"]),
            "token": int(fields["token"]),
            "elapsed_cycles": u64(*fields["elapsed_cycles"].split(":")),
            "hidden": fields["hidden"].split(","),
            "logits": fields["logits"].split(","),
        }
    )
assert [row["step"] for row in rows] == list(range(11))
assert rows[-1]["token"] == 4
assert all(len(row["hidden"]) == 16 and len(row["logits"]) == 256 for row in rows)

cpu = re.search(
    r"^STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+) "
    r"instructions=(\d+):(\d+) ibus_bytes=(\d+):(\d+) "
    r"dbus_bytes=(\d+):(\d+) dma_bytes=(\d+):(\d+)$",
    text,
    re.M,
)
p3 = re.search(r"^STUDENT_NATIVE_OPERATOR op=3 cycles=(\d+):(\d+)$", text, re.M)
assert cpu and p3
metrics = {
    "generation_cycles": u64(cpu[1], cpu[2]),
    "instructions": u64(cpu[3], cpu[4]),
    "ibus_bytes": u64(cpu[5], cpu[6]),
    "dbus_bytes": u64(cpu[7], cpu[8]),
    "dma_bytes": u64(cpu[9], cpu[10]),
    "p3_cycles": u64(p3[1], p3[2]),
}
parent = json.loads((PARENT_RUN / "result.json").read_text(encoding="utf-8"))
assert metrics["generation_cycles"] == parent["generation_cycles"] == 12_386_416
assert metrics["p3_cycles"] == parent["p3_cycles"] == 880_633
assert metrics["ibus_bytes"] == 3_994_592

nm_path = RUN / "bios.nm.txt"
nm_text = nm_path.read_text()
symbols = {}
for symbol in ["p3_native_candidate_ctx", "mini_native_scalar_expert", "mini_native_generate"]:
    match = re.search(rf"^([0-9a-f]+) ([0-9a-f]+) T {symbol}$", nm_text, re.M)
    assert match
    symbols[symbol] = {"address": "0x" + match[1], "size": "0x" + match[2]}
assert symbols == {
    "p3_native_candidate_ctx": {"address": "0x000033b8", "size": "0x00000394"},
    "mini_native_scalar_expert": {"address": "0x0000402c", "size": "0x00000224"},
    "mini_native_generate": {"address": "0x00004250", "size": "0x00000874"},
}
map_path = BUILD / "soc/software/bios/bios.elf.map"
map_text = map_path.read_text(errors="replace")
assert all(map_text.count(symbol) >= 1 for symbol in symbols)

binding = json.loads((BUILD / "build-binding.json").read_text())
assert binding["variant"] == "native-ctx-layout"
assert binding["native_candidate_sha256"] == sha(BASE / "src/p3_native_candidate_ctx.c")
assert binding["image_sha256"] == sha(IMAGE / "image.bin")

artifacts = [
    BUILD / "build-binding.json",
    BUILD / "bios/student_mini_native_nano.c",
    BUILD / "bios/student_mini_native_session.c",
    BUILD / "bios/Makefile",
    BUILD / "loader.bin",
    BUILD / "soc/software/bios/bios.bin",
    BUILD / "soc/software/bios/bios.elf",
    map_path,
    BUILD / "soc/gateware/obj_dir/Vsim",
    BUILD / "soc/gateware/sim_rom.init",
    ROOT / "sources/build/vexriscv-profiles/VexRiscv_Full_4k.v",
    BASE / "src/p3_native_candidate_ctx.c",
    IMAGE / "image.bin",
    IMAGE / "student_mini_native_image.h",
    IMAGE / "manifest.json",
    log,
    receipt_path,
    nm_path,
    RUN / "bios.objdump.txt",
    RUN / "bios.readelf.txt",
]
assert all(path.is_file() for path in artifacts)

clock_hz = 1_000_000
seconds = metrics["generation_cycles"] / clock_hz
result = {
    "status": "EXACT_PASS_BUT_LAYOUT_PERFORMANCE_REJECTED",
    "question": "根号5等于几？",
    "token_ids": [row["token"] for row in rows],
    "answer": parent["answer"],
    "semantic_equality": {
        "standalone_native_ctx": "token_hidden_logits_exact",
        "same_elf_mode3": "token_hidden_logits_exact",
    },
    **metrics,
    "symbols": symbols,
    "standalone_comparison": {
        "generation_cycles": 12_386_416,
        "p3_cycles": 880_633,
        "ibus_bytes": 3_994_592,
        "all_measured_deltas": 0,
    },
    "mode3_comparison": {
        "generation_cycles": 11_754_128,
        "p3_cycles": 980_264,
        "ibus_bytes": 3_096_768,
        "generation_cycles_regression": metrics["generation_cycles"] - 11_754_128,
        "ibus_bytes_regression": metrics["ibus_bytes"] - 3_096_768,
    },
    "configured_clock_hz": clock_hz,
    "simulated_tokens_per_second_including_eos": len(rows) / seconds,
    "simulated_tokens_per_second_excluding_eos": (len(rows) - 1) / seconds,
    "process_launch_to_complete_wall_seconds": receipt["elapsed_seconds"],
    "decision": (
        "REJECT source-order-only layout change: final hot symbol layout and all measured "
        "performance counters equal the standalone parent. Use an explicit linker-order "
        "mechanism before another layout experiment."
    ),
    "qualification_scope": (
        "One fresh native-layout root5 VexRiscv RTL execution. Exact semantic integration "
        "pass, but not a 330-case protocol or physical timing/PPA qualification."
    ),
    "bindings": {str(path.relative_to(ROOT)): sha(path) for path in artifacts},
}
(RUN / "token-stream.json").write_text(json.dumps(rows, indent=2) + "\n")
(RUN / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
