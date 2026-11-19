import hashlib
import json
from pathlib import Path
import re
import shutil

here = Path(__file__).resolve().parent
root = here.parent
work = root / 'sources/build/student-mini/native-gpu/fc14e0f618eacaeb78fd0df4626bab2fd19315064842dab6b7c12084b13bb61c'
runs = sorted(work.glob('simx-*/completion.json'), key=lambda p: p.stat().st_mtime)
completion = json.loads(runs[-1].read_text())
if not completion['target_run_complete']:
    raise RuntimeError(completion['reason'])
log = runs[-1].parent / 'execute.log'
text = log.read_text()
gpu = re.findall(r'^STUDENT_NATIVE_TOKEN step=(\d+) token=(\d+) hidden=(\S+) logits=(\S+)', text, re.M)
cpu_log = Path('/mnt/d/sqrt3-rerun/cpu-run.log')
cpu_text = cpu_log.read_text(errors='replace')
cpu = re.findall(r'STUDENT_NATIVE_TOKEN step=(\d+) token=(\d+)(?: elapsed_cycles=\S+)? hidden=(\S+) logits=(\S+)', cpu_text)
tokenizer_file = root / 'sources/build/student-mini/native-nano/876398eac822028468e275044f350988a847429d5c3a2f3aed2be1e74ca47572/inputs.json'
tokenizer = json.loads(tokenizer_file.read_text())['tokenizer']
chars = {v: k for k, v in tokenizer['characters'].items()}
ids = [int(row[1]) for row in gpu]
answer = ''.join(chars.get(i, '' if i == 4 else '[UNK]') for i in ids)
out = here / 'gpu-result'
out.mkdir(exist_ok=True)
for source, name in [(log, 'execute.log'), (runs[-1], 'completion.json'), (cpu_log, 'cpu-run.log')]:
    shutil.copy2(source, out / name)
result = dict(question='根号3等于几？', actual_tokenized_question='[UNK][UNK][UNK]等于几？',
              backend='Vortex SimX (not physical GPU)', tokens=ids, answer=answer,
              completion=[line for line in text.splitlines() if line.startswith('STUDENT_NATIVE_GPU')],
              cpu_gpu_tokens_equal=[r[1] for r in gpu] == [r[1] for r in cpu],
              cpu_gpu_hidden_and_logits_equal=gpu == cpu,
              source_run=str(runs[-1].parent),
              sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()})
(out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
