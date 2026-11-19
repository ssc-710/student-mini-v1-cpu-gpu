"""Compare portable C native inference to Python; NOT target-platform evidence."""
import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'shared/python')]
from scripts.student_mini import sha
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime

TENSORS = ['embedding', 'lm_head', 'final_norm', 'attention_norm', 'moe_norm',
    'attention_q_nope', 'attention_q_pe', 'attention_index_q', 'attention_ckv',
    'attention_kpe', 'attention_index_k', 'attention_out', 'router', 'gate', 'up',
    'down', 'shared_gate', 'shared_up', 'shared_down']


class Model(ct.Structure):
    _fields_ = [('weight', ct.POINTER(ct.c_int8)*19), ('scale', ct.c_float*19)]


class Workspace(ct.Structure):
    _fields_ = [(name, (ct.c_float*width)*32) for name, width in
                [('cache', 12), ('index_cache', 8), ('hidden', 16), ('normalized', 16),
                 ('queries', 12), ('index_queries', 8)]] + [
                (name, (ct.c_int8*width)*32) for name, width in
                [('ki', 12), ('iki', 8), ('qi', 12), ('iqi', 8)]] + [('attended', (ct.c_uint16*8)*32)]


class Result(ct.Structure):
    _fields_ = [('count', ct.c_uint), ('p1_calls', ct.c_uint), ('p2_calls', ct.c_uint),
                ('p3_calls', ct.c_uint), ('tokens', ct.c_uint32*12),
                ('final_hidden', (ct.c_uint16*16)*12), ('logits', (ct.c_uint16*256)*12),
                ('workspace', Workspace)]


def compile_library(output):
    compiler = shutil.which('gcc')
    if not compiler:
        raise RuntimeError('GCC required for native C preflight')
    command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-ffp-contract=off', '-fno-fast-math', '-shared', '-fPIC',
        str(ROOT/'software/student_mini_native_nano.c'), str(ROOT/'software/operator_scalar.c'),
        '-o', str(output)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    return command


def load_library(path):
    library = ct.CDLL(str(path))
    fn = library.mini_native_generate
    fn.argtypes = [ct.POINTER(Model), ct.POINTER(ct.c_uint32), ct.c_uint, ct.c_void_p, ct.POINTER(Result)]
    fn.restype = ct.c_int
    return fn


def model_view(runtime):
    model = Model()
    for i, name in enumerate(TENSORS):
        if not runtime.arrays[name].flags.c_contiguous:
            raise ValueError('C-contiguous weight storage required')
        model.weight[i] = runtime.arrays[name].ctypes.data_as(ct.POINTER(ct.c_int8))
        model.scale[i] = runtime.scales[name]
    return model


def bf_bits(value):
    return (np.asarray(value, dtype=np.float32).view(np.uint32) >> 16).astype(np.uint16).tolist()


def compare(fn, runtime, prompt):
    model = model_view(runtime)
    result = Result()
    status = fn(ct.byref(model), (ct.c_uint32*len(prompt))(*prompt), len(prompt), None, ct.byref(result))
    if status:
        raise ValueError('native C inference failed: '+str(status))
    expected, hidden, logits = [], [], []
    scores = runtime.prefill(prompt)
    for step in range(12):
        token = int(np.argmax(scores))
        expected.append(token)
        hidden.append(bf_bits(runtime.current_hidden()))
        logits.append(bf_bits(scores))
        if token == 4:
            break
        if step < 11:
            scores = runtime.decode(token)
    actual = list(result.tokens)[:result.count]
    actual_hidden = [list(row) for row in result.final_hidden][:result.count]
    actual_logits = [list(row) for row in result.logits][:result.count]
    match = actual == expected and actual_hidden == hidden and actual_logits == logits
    return dict(status='PASS' if match else 'FAIL', prompt=prompt, golden_tokens=expected,
        actual_tokens=actual, golden_hidden_bits=hidden, actual_hidden_bits=actual_hidden,
        golden_logits_bits=logits, actual_logits_bits=actual_logits,
        calls=dict(p1=result.p1_calls, p2=result.p2_calls, p3=result.p3_calls))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    candidate_path = args.candidate.resolve()
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    checkpoint = candidate_path.parent/candidate['lineage']['qat']['quantized']
    if sha(checkpoint) != candidate['lineage']['qat']['quantized_sha256']:
        raise ValueError('checkpoint changed')
    inputs_path = candidate_path.parent/'inputs.json'
    inputs = json.loads(inputs_path.read_text(encoding='utf-8'))
    files = [candidate_path, checkpoint, inputs_path, Path(__file__),
        ROOT/'software/student_mini_native_nano.c', ROOT/'software/include/student_mini_native_nano.h',
        ROOT/'software/operator_scalar.c', ROOT/'software/include/operator_scalar.h',
        ROOT/'software/include/numeric_luts.h']
    bindings = {str(p): sha(p) for p in files}
    compiler = Path(shutil.which('gcc') or '')
    if not compiler.is_file():
        raise RuntimeError('GCC unavailable')
    bindings[str(compiler)] = sha(compiler)
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/native-c-preflight'/identity
    work.mkdir(parents=True, exist_ok=False)
    command = compile_library(work/'runtime.so')
    fn = load_library(work/'runtime.so')
    tokenizer = inputs['tokenizer']
    # Dataset shape is frozen by the teacher producer, not inferred from answers.
    records = []
    for row in inputs['dataset']['test']:
        question = row['question']
        prompt = [1, 2]+[tokenizer['characters'].get(c, 5) for c in question]+[3]
        record = compare(fn, MiniNanoRuntime.from_npz(checkpoint), prompt)
        record['question'] = question
        records.append(record)
    result = dict(status='HOLD', kind='native-c-preflight-only', hardware_execution=False,
        numerical_pass=all(r['status']=='PASS' for r in records), records=records,
        bindings=bindings, compile_command=command, library_sha256=sha(work/'runtime.so'))
    (work/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(work=str(work), numerical_pass=result['numerical_pass'],
        count=len(records), hardware_execution=False)))
    return 0 if result['numerical_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
