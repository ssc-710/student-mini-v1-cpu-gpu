"""Change only the user prompt in a released input-only image; no inference."""
import hashlib
import json
from pathlib import Path
import re
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / 'sources'
source = ROOT / 'build/student-mini/selected-native-image/7de13d49c71d6a6a0b2e816757d1eb8e6a2480d4438c6bd40f5fc84cf50a1a64'
model = ROOT / 'build/student-mini/native-nano/876398eac822028468e275044f350988a847429d5c3a2f3aed2be1e74ca47572'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
assert sha(source/'image.bin') == manifest['image_sha256']
assert sha(model/'ptq.npz') == manifest['deployment']['quantized_sha256']
tokenizer = json.loads((model/'inputs.json').read_text(encoding='utf-8'))['tokenizer']
question = '根号3等于几？'
tokens = [1, 2] + [tokenizer['characters'].get(c, 5) for c in question] + [3]
blob = bytearray((source/'image.bin').read_bytes())
segment = manifest['segments']['prompt.tokens.u32']
assert len(tokens)*4 <= segment['size']
blob[segment['offset']:segment['offset']+segment['size']] = bytes(segment['size'])
blob[segment['offset']:segment['offset']+len(tokens)*4] = struct.pack('<'+'I'*len(tokens), *tokens)
manifest.update(question=question, prompt_tokens=tokens, target_execution=False,
                status='PREPARED_NOT_EXECUTED', bindings={},
                unknown_characters=[c for c in question if c not in tokenizer['characters']],
                rerun_source_image_sha256=sha(source/'image.bin'))
out = HERE/'image'
out.mkdir(exist_ok=True)
(out/'image.bin').write_bytes(blob)
manifest['image_sha256'] = sha(out/'image.bin')
header = (source/'student_mini_native_image.h').read_text()
header = re.sub(r'(#define COURSE_NANO_PROMPT_TOKENS )\d+u', r'\g<1>'+str(len(tokens))+'u', header)
(out/'student_mini_native_image.h').write_text(header)
(out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(question=question, prompt_tokens=tokens, unknown_characters=manifest['unknown_characters'], image_sha256=manifest['image_sha256']), ensure_ascii=False))
