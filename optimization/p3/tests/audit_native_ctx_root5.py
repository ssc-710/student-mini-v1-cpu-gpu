"""Audit the fresh native scale-context root5 VexRiscv RTL execution."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
BUILD = BASE / "build/cpu-native-ctx"
RUN = BASE / "runs/cpu-native-ctx-root5-fresh"
IMAGE = ROOT / "rerun_sqrt5/image"
MODEL = ROOT / "sources/build/student-mini/native-nano/876398eac822028468e275044f350988a847429d5c3a2f3aed2be1e74ca47572"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic(line):
    return re.sub(r" elapsed_cycles=\d+:\d+", "", line)


binding_path = BUILD / "build-binding.json"
binding = json.loads(binding_path.read_text())
candidate = BASE / "src/p3_native_candidate_ctx.c"
image = IMAGE / "image.bin"
manifest_path = IMAGE / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
log = RUN / "execute.log"
receipt_path = RUN / "execute.receipt.json"
receipt = json.loads(receipt_path.read_text())

assert binding["variant"] == "native-ctx"
assert binding["native_candidate_sha256"] == sha(candidate)
assert binding["image_sha256"] == sha(image) == manifest["image_sha256"]
assert (BUILD / "loader.bin").read_bytes()[: image.stat().st_size] == image.read_bytes()
assert receipt["completion_marker_observed"] is True
assert receipt["log_sha256"] == sha(log)

text = log.read_text(errors="replace")
assert text.count("STUDENT_NATIVE_CPU status=0 count=11") == 1
assert text.count("STUDENT_NATIVE_CPU_COMPLETE count=11 p1=1 p2=10 p3=40") == 1
states = [line for line in text.splitlines() if line.startswith("STUDENT_NATIVE_TOKEN ")]
assert len(states) == 11
rows = []
for line in states:
    fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
    rows.append(
        dict(
            step=int(fields["step"]),
            token=int(fields["token"]),
            elapsed_cycles=(int(fields["elapsed_cycles"].split(":")[0]) << 32)
            + int(fields["elapsed_cycles"].split(":")[1]),
            hidden=fields["hidden"].split(","),
            logits=fields["logits"].split(","),
        )
    )
assert [row["step"] for row in rows] == list(range(11))
assert rows[-1]["token"] == 4
assert all(len(row["hidden"]) == 16 and len(row["logits"]) == 256 for row in rows)

# The final run is new; the existing same-binary ablation is used only as the
# frozen semantic reference, never as a substitute for this execution.
ablation = json.loads((BASE / "runs/cpu-ablation-v2/comparison-audited.json").read_text())
reference = next(row for row in ablation["records"] if row["mode"] == 3)
assert [semantic(line) for line in states] == [semantic(line) for line in reference["states"]]

generation_match = re.search(r"STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+)", text)
p3_match = re.search(r"STUDENT_NATIVE_OPERATOR op=3 cycles=(\d+):(\d+)", text)
assert generation_match and p3_match
generation_cycles = (int(generation_match[1]) << 32) + int(generation_match[2])
p3_cycles = (int(p3_match[1]) << 32) + int(p3_match[2])
clock_hz = 1_000_000
generation_seconds = generation_cycles / clock_hz

tokenizer = json.loads((MODEL / "inputs.json").read_text(encoding="utf-8"))["tokenizer"]
decode = {int(value): key for key, value in tokenizer["characters"].items()}
token_ids = [row["token"] for row in rows]
answer = "".join(decode.get(token, "") for token in token_ids)

artifacts = [
    binding_path,
    candidate,
    BUILD / "bios/student_mini_native_nano.c",
    BUILD / "bios/student_mini_native_session.c",
    BUILD / "bios/Makefile",
    BUILD / "loader.bin",
    BUILD / "soc/software/bios/bios.bin",
    BUILD / "soc/gateware/obj_dir/Vsim",
    BUILD / "soc/gateware/sim_rom.init",
    ROOT / "sources/build/vexriscv-profiles/VexRiscv_Full_4k.v",
    ROOT / "sources/software/operator_scalar.c",
    ROOT / "sources/software/include/operator_scalar.h",
    image,
    IMAGE / "student_mini_native_image.h",
    manifest_path,
    MODEL / "inputs.json",
    log,
    receipt_path,
]
result = dict(
    status="FRESH_NATIVE_CTX_ROOT5_VEXRISCV_RTL_EXACT_PASS",
    question=manifest["question"],
    answer=answer,
    token_ids=token_ids,
    semantic_reference="cpu-ablation-v2 mode3; token/hidden/logits only",
    generation_cycles=generation_cycles,
    p3_cycles=p3_cycles,
    actual_simulation_clock_hz=clock_hz,
    simulated_generation_seconds=generation_seconds,
    simulated_tokens_per_second_including_eos=len(rows) / generation_seconds,
    simulated_tokens_per_second_excluding_eos=(len(rows) - 1) / generation_seconds,
    process_launch_to_complete_wall_seconds=receipt["elapsed_seconds"],
    process_wall_tokens_per_second_including_eos=len(rows) / receipt["elapsed_seconds"],
    process_wall_tokens_per_second_excluding_eos=(len(rows) - 1) / receipt["elapsed_seconds"],
    timing_boundaries=dict(
        simulated="STUDENT_NATIVE_CPU generation cycle counter at configured 1 MHz; includes prompt/session generation work represented by firmware counter",
        process_wall="Fresh Vsim process launch through observed UART COMPLETE; includes boot, loading and diagnostic UART output",
        physical_limit="100 MHz is only an unsigned physical target and is not used for this token/s result",
    ),
    qualification_scope="Fresh native-layout root5 run; does not transfer benchmark MINI31/32/33 protocol or physical signoff qualification",
    bindings={str(path.relative_to(ROOT)): sha(path) for path in artifacts},
)
(RUN / "token-stream.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
(RUN / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
