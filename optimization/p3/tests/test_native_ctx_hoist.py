"""Exact host differential and RV32 static screen for ctx branch hoisting."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
RUN = BASE / "runs/p3-ctx-hoist-host-screen"
assert not RUN.exists()
RUN.mkdir(parents=True)
INCLUDE = ROOT / "sources/software/include"
SOURCES = [
    ROOT / "sources/software/student_mini_native_nano.c",
    ROOT / "sources/software/operator_scalar.c",
    BASE / "src/p3_native_candidate_ctx.c",
    BASE / "src/p3_native_candidate_ctx_hoist.c",
]
ENV = dict(os.environ, TMPDIR=str(BASE / "build/cache/tmp"))

subprocess.run([
    "gcc", "-shared", "-fPIC", "-O2", "-ffp-contract=off", "-fno-fast-math",
    "-I" + str(INCLUDE), *map(str, SOURCES), "-o", str(RUN / "screen.so")
], check=True, env=ENV)
lib = C.CDLL(str(RUN / "screen.so"))

class Model(C.Structure):
    _fields_ = [("weight", C.POINTER(C.c_int8) * 19), ("scale", C.c_float * 19)]

args = [C.c_void_p, C.c_uint, C.POINTER(C.c_int8), C.c_float,
        C.POINTER(Model), C.POINTER(C.c_uint16)]
names = ["p3_native_candidate_ctx", "p3_native_candidate_ctx_hoist"]
for name in names:
    getattr(lib, name).argtypes = args

rng = random.Random(0x5033484f)
weights = [(C.c_int8 * 512)() for _ in range(19)]
model = Model()
for i, weight in enumerate(weights):
    model.weight[i] = weight

calls = 0
for case in range(256):
    for i, weight in enumerate(weights):
        for j in range(512):
            weight[j] = rng.randint(-128, 127)
        model.scale[i] = 2 ** rng.randint(-16, 12)
    activation = (C.c_int8 * 16)(*[rng.randint(-128, 127) for _ in range(16)])
    input_scale = C.c_float(2 ** rng.randint(-16, 12))
    for expert in range(3):
        outputs = []
        codes = []
        for name in names:
            output = (C.c_uint16 * 16)()
            codes.append(getattr(lib, name)(None, expert, activation, input_scale,
                                            C.byref(model), output))
            outputs.append(list(output))
        assert codes[0] == codes[1]
        assert codes[0] != 0 or outputs[0] == outputs[1]
        calls += 1

flags = ["-O2", "-ffp-contract=off", "-fno-fast-math", "-march=rv32im_zicsr",
         "-mabi=ilp32", "-I" + str(INCLUDE)]
objects = {}
for stem in ("p3_native_candidate_ctx", "p3_native_candidate_ctx_hoist"):
    obj = RUN / (stem + ".o")
    subprocess.run(["riscv64-unknown-elf-gcc", *flags, "-c",
                    str(BASE / "src" / (stem + ".c")), "-o", str(obj)],
                   check=True, env=ENV)
    dis = subprocess.run(["riscv64-unknown-elf-objdump", "-dr", str(obj)],
                         check=True, text=True, capture_output=True).stdout
    (RUN / (stem + ".dis")).write_text(dis)
    insns = [line for line in dis.splitlines() if re.match(r"^\s*[0-9a-f]+:", line)]
    objects[stem] = {
        "instructions": len(insns),
        "branches": sum(bool(re.search(r"\b(?:b\w+|j|jal)\b", line)) for line in insns),
        "stack_loads": sum(bool(re.search(r"\b(?:lb|lbu|lh|lhu|lw)\s+\w+,\s*\d+\(sp\)", line)) for line in insns),
        "stack_stores": sum(bool(re.search(r"\b(?:sb|sh|sw)\s+\w+,\s*\d+\(sp\)", line)) for line in insns),
        "object_bytes": obj.stat().st_size,
        "sha256": hashlib.sha256(obj.read_bytes()).hexdigest(),
    }

result = {
    "status": "CTX_HOIST_HOST_EXACT_RV32_STATIC_SCREEN_PASS",
    "expert_calls": calls,
    "seed": "0x5033484f",
    "objects": objects,
    "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in SOURCES[-2:]},
    "qualification_boundary": (
        "Synthetic native-ABI exact screen and RV32 static comparison only. "
        "Not frozen 33x10 qualification, target-cycle evidence, LLM integration or physical qualification."
    ),
}
(RUN / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
