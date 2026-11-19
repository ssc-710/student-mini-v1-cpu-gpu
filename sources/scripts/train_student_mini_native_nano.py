"""CPU-only native mini training, with same-source FP32 -> PTQ and QAT lineage.

Validation selects checkpoints. The held-out test set is evaluated only after
selection, including the exact INT8/BF16 reference runtime, not weight-only PTQ.
No report from this producer constitutes execution on a target platform.
"""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'shared/python')]
from scripts.train_student_mini_nano import dataset, encode
from scripts.student_mini import sha
from soc_ai_labs.student_mini_nano_model import MiniNativeNano
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def generate(model, question, tokenizer):
    prompt = [1, 2] + encode(question, tokenizer) + [3]
    if isinstance(model, MiniNanoRuntime):
        result = model.generate(prompt)
    else:
        result = []
        with torch.no_grad():
            for _ in range(12):
                token = int(model(torch.tensor([prompt+result]))[0, -1].argmax())
                result.append(token)
                if token == 4:
                    break
    reverse = {value: key for key, value in tokenizer['characters'].items()}
    return result, ''.join(reverse.get(token, '[UNK]') for token in result if token != 4)


def evaluate(model, rows, tokenizer):
    result = []
    for row in rows:
        tokens, text = generate(model, row['question'], tokenizer)
        result.append(dict(row, tokens=tokens, actual_text=text, passed=text == row['answer']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps', type=int, default=1500)
    parser.add_argument('--qat-steps', type=int, default=500)
    args = parser.parse_args()
    if args.steps < 100 or args.qat_steps < 100:
        raise ValueError('each training stage requires a validation checkpoint')
    if torch.version.cuda is not None:
        raise ValueError('use a qualified CPU-only PyTorch build for this producer')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(1)
    torch.use_deterministic_algorithms(True)
    tokenizer, rows = dataset()
    sources = [Path(__file__), ROOT/'scripts/train_student_mini_nano.py',
        ROOT/'grading/student-mini/spec.json']
    sources += [ROOT/'shared/python/soc_ai_labs'/name for name in (
        'student_mini_nano_model.py', 'student_mini_nano_runtime.py', 'nano_chat_model.py',
        'nano_chat_runtime.py', 'rtl_oracle.py', 'numeric.py', 'tiny_model.py', 'litex_contract.py', 'dsa.py')]
    bindings = {str(path): sha(path) for path in sources}
    inputs = dict(bindings=bindings, seed=1, device='cpu', torch_version=torch.__version__,
                  steps=args.steps, qat_steps=args.qat_steps, dataset=rows, tokenizer=tokenizer)
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    work = ROOT/'build/student-mini/native-nano'/identity
    work.mkdir(parents=True, exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    x, labels = [], []
    for row in rows['train']:
        prompt = [1, 2]+encode(row['question'], tokenizer)+[3]
        sequence = prompt+encode(row['answer'], tokenizer)+[4]
        if len(sequence) > 32:
            raise ValueError('training context overflow')
        x.append(sequence[:-1]+[0]*(32-len(sequence)))
        labels.append([-100]*(len(prompt)-1)+sequence[len(prompt):]+[-100]*(32-len(sequence)))
    x, labels = torch.tensor(x), torch.tensor(labels)
    model = MiniNativeNano().cpu()
    started = time.monotonic()
    history = []
    checkpoints = {}
    for stage, steps, rate in [('fp32', args.steps, .006), ('qat', args.qat_steps, .0005)]:
        model.qat_enabled = stage == 'qat'
        optimizer = torch.optim.AdamW(model.parameters(), lr=rate, weight_decay=.01)
        best, rank = None, (-1, float('-inf'))
        for step in range(1, steps+1):
            batch = torch.randperm(len(x))[:16]
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(x[batch]).reshape(-1, 256), labels[batch].reshape(-1), ignore_index=-100)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
            if step % 100 == 0 or step == steps:
                valid = evaluate(model, rows['validation'], tokenizer)
                passed = sum(row['passed'] for row in valid)
                item = dict(stage=stage, step=step, loss=float(loss.detach()), validation_passed=passed,
                            validation_total=len(valid), elapsed_seconds=time.monotonic()-started)
                history.append(item)
                print(json.dumps(item), flush=True)
                score = (passed, -item['loss'])
                if score > rank:
                    best, rank = copy.deepcopy(model.state_dict()), score
        model.load_state_dict(best)
        checkpoint = work/(stage+'.pt')
        torch.save(model.state_dict(), checkpoint)
        export = work/('ptq.npz' if stage == 'fp32' else 'qat.npz')
        model.export_int8(export, parent_checkpoint_sha256=sha(checkpoint))
        checkpoints[stage] = dict(checkpoint=checkpoint.name, sha256=sha(checkpoint),
            parent_fp32_sha256=None if stage == 'fp32' else checkpoints['fp32']['sha256'],
            selected_validation_passed=rank[0], quantized=export.name, quantized_sha256=sha(export))
    # Held-out evaluation occurs once, after both stages and selections finish.
    model.qat_enabled = False
    model.load_state_dict(torch.load(work/'fp32.pt', map_location='cpu', weights_only=True))
    quality = dict(fp32=evaluate(model, rows['test'], tokenizer),
                  ptq_exact=evaluate(MiniNanoRuntime.from_npz(work/'ptq.npz'), rows['test'], tokenizer),
                  qat_exact=evaluate(MiniNanoRuntime.from_npz(work/'qat.npz'), rows['test'], tokenizer))
    if any(sha(Path(path)) != digest for path, digest in bindings.items()):
        raise ValueError('model sources changed during training')
    result = dict(status='HOLD', target_execution=False, accepted_nano_sessions=0,
        kind='teacher-native-exact-reference-candidate', bindings=bindings,
        parameters=sum(p.numel() for p in model.parameters()), lineage=checkpoints, quality=quality,
        training_log=history, elapsed_seconds=time.monotonic()-started,
        boundary='Quality below is exact CPU reference inference, not VexRiscv, Vortex, or accelerator execution. Platform image/runtime/operator evidence remains mandatory.',
        artifacts={p.name: sha(p) for p in work.iterdir() if p.is_file()})
    (work/'candidate.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(work=str(work), status='HOLD', quality={stage: sum(r['passed'] for r in data) for stage, data in quality.items()}, total=len(rows['test']))), flush=True)


if __name__ == '__main__':
    main()
