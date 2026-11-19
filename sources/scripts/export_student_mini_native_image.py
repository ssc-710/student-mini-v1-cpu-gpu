"""Input-only native Nano deployment image; golden tokens remain host-side.

This export is preparation, not a CPU/GPU/accelerator session PASS. No training
software is imported or included in the runtime image.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'shared/python')]
from scripts.student_mini import sha
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime, PROFILE, SHAPES


def pack(runtime, tokenizer, question):
    special = tokenizer['special']
    if special != dict(PAD=0, BOS=1, USER=2, ASSISTANT=3, EOS=4, UNK=5):
        raise ValueError('native tokenizer special IDs differ')
    characters = tokenizer['characters']
    ids = list(characters.values())
    if any(type(value) is not int or not 6 <= value < 256 for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('invalid or duplicate character token ID')
    if any(len(char) != 1 for char in characters):
        raise ValueError('native tokenizer is character-based')
    prompt = [1, 2]+[characters.get(char, 5) for char in question]+[3]
    if not question or len(prompt)+12 > 32:
        raise ValueError('question exceeds frozen context including generation budget')
    image = bytearray()
    segments = {}
    def append(name, payload):
        offset = (len(image)+63)//64*64
        image.extend(bytes(offset-len(image)))
        image.extend(payload)
        segments[name] = dict(offset=offset, size=len(payload))
    for name in sorted(SHAPES):
        append('weight.'+name, np.ascontiguousarray(runtime.arrays[name]).tobytes())
    packed = []
    for expert in range(3):
        for name in ('gate', 'up', 'down'):
            matrix = runtime.arrays[name][0, expert] if expert < 2 else runtime.arrays['shared_'+name][0]
            packed.append(np.ascontiguousarray(matrix.T).tobytes())
    append('rtl.p3.layer0.weights', b''.join(packed))
    scale_order = sorted(SHAPES)
    append('scales.fp32', b''.join(struct.pack('<f', runtime.scales[name]) for name in scale_order))
    reverse = {value: char for char, value in characters.items()}
    offsets, blob = [0], bytearray()
    for token in range(256):
        blob.extend(reverse.get(token, '').encode('utf-8'))
        offsets.append(len(blob))
    append('tokenizer.offsets.u32', struct.pack('<257I', *offsets))
    append('tokenizer.bytes', bytes(blob))
    append('user.utf8', question.encode('utf-8'))
    append('prompt.tokens.u32', struct.pack('<'+str(len(prompt))+'I', *prompt))
    append('generated.tokens.u32', struct.pack('<12I', *([0xa5a5a5a5]*12)))
    append('kv_cache.bf16', bytes(32*32*2))
    append('descriptors', bytes(64*4))
    append('operator_scratch', bytes(1024*1024))
    image.extend(bytes((-len(image)) % 64))
    return bytes(image), dict(segments=segments, scale_order=scale_order,
        scale_index={name: i for i, name in enumerate(scale_order)}, prompt_tokens=prompt,
        question=question, model_config=asdict(PROFILE), max_generated_tokens=12,
        tokenizer_special_tokens=special, contains_expected_tokens=False)


def header(manifest):
    lines = ['// Generated input-only native Nano ABI. No expected token array.',
             '#ifndef STUDENT_MINI_NATIVE_IMAGE_H', '#define STUDENT_MINI_NATIVE_IMAGE_H',
             '#define COURSE_STUDENT_MINI_NATIVE_NANO 1', '#define COURSE_NANO_IMAGE_PRESENT 1',
             '#define COURSE_NANO_PREFILL_TOPK 4',
             '#define COURSE_NANO_PAGE_SIZE 4']
    macro = lambda name: re.sub('[^A-Za-z0-9]', '_', name).upper()
    for name, value in manifest['model_config'].items():
        if type(value) is int:
            lines.append(f'#define COURSE_NANO_MODEL_{macro(name)} {value}u')
    for name, segment in manifest['segments'].items():
        for key, value in segment.items():
            lines.append(f'#define COURSE_NANO_SEGMENT_{macro(name)}_{key.upper()} {value}u')
    for name, index in manifest['scale_index'].items():
        lines.append(f'#define COURSE_NANO_SCALE_{macro(name)}_INDEX {index}u')
    for name, token in manifest['tokenizer_special_tokens'].items():
        lines.append(f'#define COURSE_NANO_TOKEN_{name} {token}u')
    lines += [f'#define COURSE_NANO_PROMPT_TOKENS {len(manifest["prompt_tokens"])}u', '#endif', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--question', default='今天天气怎么样？')
    args = parser.parse_args()
    candidate_path = args.candidate.resolve()
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    if candidate.get('kind') != 'teacher-native-exact-reference-candidate':
        raise ValueError('native candidate required')
    if candidate['lineage']['qat']['parent_fp32_sha256'] != candidate['lineage']['fp32']['sha256']:
        raise ValueError('same-source QAT lineage required')
    checkpoint = candidate_path.parent/candidate['lineage']['qat']['quantized']
    if sha(checkpoint) != candidate['lineage']['qat']['quantized_sha256']:
        raise ValueError('checkpoint changed')
    inputs_path = candidate_path.parent/'inputs.json'
    inputs = json.loads(inputs_path.read_text(encoding='utf-8'))
    for name, digest in candidate['bindings'].items():
        path = Path(name)
        if not path.is_file() and name.startswith('/mnt/c/Users/admin/Downloads/open-soc-ai-labs/'):
            path = ROOT/name.split('/open-soc-ai-labs/', 1)[1]
        if sha(path) != digest:
            raise ValueError('candidate source changed: '+name)
    runtime = MiniNanoRuntime.from_npz(checkpoint)
    blob, manifest = pack(runtime, inputs['tokenizer'], args.question)
    bindings = {path.relative_to(ROOT).as_posix(): sha(path) for path in
                (candidate_path, inputs_path, checkpoint, Path(__file__))}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, question=args.question), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    work = ROOT/'build/student-mini/native-image'/identity
    work.mkdir(parents=True, exist_ok=False)
    (work/'image.bin').write_bytes(blob)
    (work/'student_mini_native_image.h').write_text(header(manifest))
    manifest.update(status='DEVELOPMENT_ONLY', target_execution=False, formal_baseline=False,
                    bindings=bindings, image_sha256=sha(work/'image.bin'), size_bytes=len(blob))
    (work/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tokens = runtime.generate(manifest['prompt_tokens'])
    reverse = {value: key for key, value in inputs['tokenizer']['characters'].items()}
    golden = dict(kind='host-reference-only-never-target-input', tokens=tokens,
                  text=''.join(reverse.get(token, '[UNK]') for token in tokens if token != 4),
                  token_sha256=hashlib.sha256(struct.pack('<'+str(len(tokens))+'I', *tokens)).hexdigest(),
                  image_sha256=manifest['image_sha256'], manifest_sha256=sha(work/'manifest.json'))
    (work/'host-golden.json').write_text(json.dumps(golden, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(work=str(work), image_bytes=len(blob), status='DEVELOPMENT_ONLY',
                         expected_token_count=len(tokens), target_execution=False)))


if __name__ == '__main__':
    main()
