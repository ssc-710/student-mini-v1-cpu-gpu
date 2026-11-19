"""Audit the fresh scale-context VexRiscv RTL 1000-vector transcript."""
import hashlib
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
BUILD = BASE / "build/cpu-scalar-ctx"
RUN = BASE / "runs/cpu-scalar-ctx-rtl-frozen-1000"

sys.path.insert(0, str(ROOT / "sources"))
from scripts.assemble_student_mini_cpu_results import parse
from scripts.export_student_mini_input import encode
from scripts.student_mini_release_records import compare


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


log = RUN / "execute.log"
receipt = RUN / "execute.receipt.json"
binding_path = BUILD / "build-binding.json"
candidate = BASE / "src/p3_scalar_candidate_ctx.c"
vectors_path = ROOT / "data/golden/vectors.jsonl"
binding = json.loads(binding_path.read_text())
vectors = [json.loads(line) for line in vectors_path.read_text().splitlines()]

assert binding["variant"] == "scalar-ctx"
assert binding["scalar_candidate_sha256"] == sha(candidate)
assert len(vectors) == 1000
blob = b"".join(encode(vector, ordinal) for ordinal, vector in enumerate(vectors))
assert binding["image_sha256"] == hashlib.sha256(blob).hexdigest()
loader = (BUILD / "loader.bin").read_bytes()
assert loader[: len(blob)] == blob and loader[len(blob) :] == bytes(len(loader) - len(blob))

execution = json.loads(receipt.read_text())
assert execution["completion_marker_observed"] is True
assert execution["log_sha256"] == sha(log)
actual = parse(log.read_text(), 1000)
assert len(actual) == len(vectors) == 1000

records = []
for ordinal, (golden, observation) in enumerate(zip(vectors, actual)):
    records.append(
        dict(
            ordinal=ordinal,
            case_id=golden["case"]["id"],
            operator=golden["case"]["operator"],
            seed=golden["seed"],
            observation=observation,
            comparison=compare(golden["golden"], observation, golden["case"]["operator"]),
        )
    )

summary = {}
expected_records = {"p1": 330, "p2": 340, "p3": 330}
expected_cases = {"p1": 33, "p2": 34, "p3": 33}
for operator in ("p1", "p2", "p3"):
    rows = [record for record in records if record["operator"] == operator]
    case_ids = sorted({record["case_id"] for record in rows})
    assert len(rows) == expected_records[operator]
    assert len(case_ids) == expected_cases[operator]
    for case_id in case_ids:
        seeds = sorted(record["seed"] for record in rows if record["case_id"] == case_id)
        assert seeds == list(range(1, 11))
    matched = sum(record["comparison"]["status"] == "PASS" for record in rows)
    summary[operator] = dict(records=len(rows), cases=len(case_ids), matched=matched)

matched = sum(record["comparison"]["status"] == "PASS" for record in records)
assert matched == 1000
artifacts = [
    log,
    receipt,
    binding_path,
    candidate,
    BUILD / "bios/student_mini_scalar.c",
    BUILD / "loader.bin",
    BUILD / "soc/software/bios/bios.bin",
    BUILD / "soc/gateware/obj_dir/Vsim",
    BUILD / "soc/gateware/sim_rom.init",
    ROOT / "sources/build/vexriscv-profiles/VexRiscv_Full_4k.v",
    vectors_path,
]
result = dict(
    status="VEXRISCV_RTL_FROZEN_1000_EXACT_PASS",
    matched=matched,
    by_operator=summary,
    qualification_scope=(
        "Benchmark-layout scalar scale-context candidate on VexRiscv RTL. "
        "This does not qualify the native-layout root5 candidate or MINI31/32/33 protocol stimuli."
    ),
    binding_note=(
        "For this scalar benchmark build, loader/vectors/candidate/BIOS/Vsim/RTL/log are operative. "
        "build-binding image_directory/header fields are build-script defaults and are not the 1000-vector input."
    ),
    protocol_qualification=(
        "MINI31/32/33 specialized stimuli NOT_RUN for this candidate; "
        "MINI30 status is only what the actual benchmark DMA adapter reports."
    ),
    bindings={str(path.relative_to(ROOT)): sha(path) for path in artifacts},
)
(RUN / "records.json").write_text(json.dumps(records, indent=2) + "\n")
(RUN / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
