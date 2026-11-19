"""Audit the fresh native-ctx GC/link-layout VexRiscv RTL root5 screening run."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
BUILD = BASE / "build/cpu-native-ctx-gc"
RUN = BASE / "runs/cpu-native-ctx-gc-root5-fresh"
PARENT = BASE / "runs/cpu-native-ctx-layout-root5-fresh"
MODE3 = BASE / "runs/cpu-ablation-v2/comparison-audited.json"
GATE = BASE / "runs/cpu-native-ctx-gc-layout-gate/result.json"


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
assert receipt["completion_marker_observed"] and receipt["log_sha256"] == sha(log)
assert text.count("STUDENT_NATIVE_CPU status=0 count=11") == 1
assert text.count("STUDENT_NATIVE_CPU_COMPLETE count=11 p1=1 p2=10 p3=40") == 1

states = [line for line in text.splitlines() if line.startswith("STUDENT_NATIVE_TOKEN ")]
parent_states = [
    line for line in (PARENT / "execute.log").read_text(errors="replace").splitlines()
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
    rows.append({
        "step": int(fields["step"]),
        "token": int(fields["token"]),
        "elapsed_cycles": u64(*fields["elapsed_cycles"].split(":")),
        "hidden": fields["hidden"].split(","),
        "logits": fields["logits"].split(","),
    })
assert [row["step"] for row in rows] == list(range(11)) and rows[-1]["token"] == 4
assert all(len(row["hidden"]) == 16 and len(row["logits"]) == 256 for row in rows)

cpu = re.search(
    r"^STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+) "
    r"instructions=(\d+):(\d+) ibus_bytes=(\d+):(\d+) "
    r"dbus_bytes=(\d+):(\d+) dma_bytes=(\d+):(\d+)$", text, re.M)
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
expected = {
    "generation_cycles": 11_389_357,
    "instructions": 7_156_976,
    "ibus_bytes": 2_417_024,
    "dbus_bytes": 1_872_306,
    "dma_bytes": 0,
    "p3_cycles": 880_673,
}
assert metrics == expected

standalone = {"generation_cycles": 12_386_416, "p3_cycles": 880_633, "ibus_bytes": 3_994_592}
same_elf_mode3 = {"generation_cycles": 11_754_128, "p3_cycles": 980_264, "ibus_bytes": 3_096_768}
assert metrics["generation_cycles"] < standalone["generation_cycles"]
assert metrics["generation_cycles"] < same_elf_mode3["generation_cycles"]
assert metrics["ibus_bytes"] < standalone["ibus_bytes"]
assert metrics["ibus_bytes"] < same_elf_mode3["ibus_bytes"]

artifacts = [
    GATE,
    BUILD / "build-binding.json",
    BUILD / "bios/Makefile",
    BUILD / "bios/student_mini_native_nano.c",
    BUILD / "bios/student_mini_native_session.c",
    BUILD / "soc/software/bios/bios.bin",
    BUILD / "soc/software/bios/bios.elf",
    BUILD / "soc/software/bios/bios.elf.map",
    BUILD / "soc/gateware/sim_rom.init",
    BUILD / "soc/gateware/obj_dir/Vsim",
    BASE / "src/p3_native_candidate_ctx.c",
    ROOT / "rerun_sqrt5/image/image.bin",
    ROOT / "rerun_sqrt5/image/manifest.json",
    log,
    receipt_path,
]
assert all(path.is_file() for path in artifacts)
seconds = metrics["generation_cycles"] / 1_000_000
result = {
    "status": "NATIVE_CTX_GC_ROOT5_SCREENING_EXACT_AND_PERFORMANCE_PASS",
    "question": "根号5等于几？",
    "answer": "我无法获知实时天气。",
    "token_ids": [row["token"] for row in rows],
    "semantic_equality": {
        "standalone_native_ctx_layout": "token_hidden_logits_exact",
        "same_elf_mode3": "token_hidden_logits_exact",
    },
    **metrics,
    "versus_standalone": {
        "generation_cycles_saved": standalone["generation_cycles"] - metrics["generation_cycles"],
        "generation_speedup": standalone["generation_cycles"] / metrics["generation_cycles"],
        "p3_cycles_delta": metrics["p3_cycles"] - standalone["p3_cycles"],
        "ibus_bytes_saved": standalone["ibus_bytes"] - metrics["ibus_bytes"],
    },
    "versus_same_elf_mode3": {
        "generation_cycles_saved": same_elf_mode3["generation_cycles"] - metrics["generation_cycles"],
        "generation_speedup": same_elf_mode3["generation_cycles"] / metrics["generation_cycles"],
        "p3_cycles_saved": same_elf_mode3["p3_cycles"] - metrics["p3_cycles"],
        "ibus_bytes_saved": same_elf_mode3["ibus_bytes"] - metrics["ibus_bytes"],
    },
    "configured_clock_hz": 1_000_000,
    "simulated_tokens_per_second_including_eos": len(rows) / seconds,
    "simulated_tokens_per_second_excluding_eos": (len(rows) - 1) / seconds,
    "process_launch_to_complete_wall_seconds": receipt["elapsed_seconds"],
    "decision": "Advance to five interleaved repetitions and broader integration regression; not yet promoted.",
    "attribution_boundary": (
        "P3 runtime integration/link-layout improvement. P3 arithmetic is unchanged and P3 cycles are "
        "40 cycles slower than standalone; no RTL Fmax, WNS, PPA or physical speed claim."
    ),
    "bindings": {str(path.relative_to(ROOT)): sha(path) for path in artifacts},
}
(RUN / "token-stream.json").write_text(json.dumps(rows, indent=2) + "\n")
(RUN / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
