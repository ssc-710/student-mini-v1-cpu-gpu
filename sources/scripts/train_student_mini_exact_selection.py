"""Same frozen training experiment; select checkpoints by deployed validation.

The only experimental change is checkpoint selection: exact exported INT8/BF16
validation replaces surrogate-FP32/QAT validation. No test result selects a
checkpoint, no split/architecture/precision changes, and no target PASS is issued.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha


def validation_rank(records, loss):
    if len(records)!=8 or any(type(row.get('passed')) is not bool for row in records):
        raise ValueError('complete frozen validation required')
    return (sum(row['passed'] for row in records),-float(loss))


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    args=parser.parse_args();parent=args.parent.resolve()
    original=json.loads(parent.read_text());inputs=json.loads((parent.parent/'inputs.json').read_text())
    if inputs['seed']!=1 or inputs['steps']!=3000 or inputs['qat_steps']!=500:
        raise ValueError('expected frozen 3000/500 seed-1 parent')
    bindings=dict(original['bindings'])
    bindings.update({str(p):sha(p) for p in (Path(__file__),parent,parent.parent/'inputs.json',ROOT/'scripts/audit_student_mini_native_quality.py')})
    inputs=dict(inputs,bindings=bindings,checkpoint_selection='exact exported validation only; loss breaks ties',parent_candidate_sha256=sha(parent))
    identity=hashlib.sha256(json.dumps(inputs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    work=ROOT/'build/student-mini/native-nano'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2)+'\n')
    def fresh():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()): raise ValueError('training source changed')
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    result=dict(status='HOLD',target_execution=False,accepted_nano_sessions=0,bindings=bindings)
    started=time.monotonic()
    try:
        fresh()
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            os.environ['CUDA_VISIBLE_DEVICES']=''
            import torch
            import torch.nn.functional as F
            from scripts.train_student_mini_native_nano import evaluate, encode
            from scripts.audit_student_mini_native_quality import split_check
            from soc_ai_labs.student_mini_nano_model import MiniNativeNano
            from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime
            if torch.version.cuda is not None: raise ValueError('CPU-only environment required')
            torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(1);torch.use_deterministic_algorithms(True)
            rows=inputs['dataset'];tokenizer=inputs['tokenizer']
            split_check(rows,json.loads((ROOT/'grading/student-mini/spec.json').read_text())['nano']['held_out_question'])
            x=[];labels=[]
            for row in rows['train']:
                prompt=[1,2]+encode(row['question'],tokenizer)+[3]
                sequence=prompt+encode(row['answer'],tokenizer)+[4]
                if len(sequence)>32:raise ValueError('context overflow')
                x.append(sequence[:-1]+[0]*(32-len(sequence)))
                labels.append([-100]*(len(prompt)-1)+sequence[len(prompt):]+[-100]*(32-len(sequence)))
            x,labels=torch.tensor(x),torch.tensor(labels)
            model=MiniNativeNano().cpu();history=[];lineage={}
            for stage,steps,rate in [('fp32',3000,.006),('qat',500,.0005)]:
                heartbeat(stage.upper());model.qat_enabled=stage=='qat'
                optimizer=torch.optim.AdamW(model.parameters(),lr=rate,weight_decay=.01)
                best=None;rank=(-1,float('-inf'))
                for step in range(1,steps+1):
                    batch=torch.randperm(len(x))[:16];optimizer.zero_grad(set_to_none=True)
                    loss=F.cross_entropy(model(x[batch]).reshape(-1,256),labels[batch].reshape(-1),ignore_index=-100)
                    loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step()
                    if step%100==0:
                        checkpoint=work/f'{stage}-{step}.pt';torch.save(model.state_dict(),checkpoint)
                        export=work/f'{stage}-{step}.npz';model.export_int8(export,parent_checkpoint_sha256=sha(checkpoint))
                        records=evaluate(MiniNanoRuntime.from_npz(export),rows['validation'],tokenizer)
                        score=validation_rank(records,loss.detach())
                        item=dict(stage=stage,step=step,loss=float(loss.detach()),validation_passed=score[0],validation_total=8,checkpoint_sha256=sha(checkpoint),export_sha256=sha(export),validation=records)
                        history.append(item);print(json.dumps({k:v for k,v in item.items() if k!='validation'}),flush=True)
                        if score>rank:best=(checkpoint,export,step);rank=score
                checkpoint=work/(stage+'.pt');export=work/('ptq.npz' if stage=='fp32' else 'qat.npz')
                shutil.copy2(best[0],checkpoint);shutil.copy2(best[1],export)
                model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
                lineage[stage]=dict(checkpoint=checkpoint.name,sha256=sha(checkpoint),parent_fp32_sha256=None if stage=='fp32' else lineage['fp32']['sha256'],selected_validation_passed=rank[0],selected_step=best[2],quantized=export.name,quantized_sha256=sha(export))
            # Immutable selection precedes any test evaluation.
            (work/'checkpoint-selection.json').write_text(json.dumps(dict(lineage=lineage,training_log=history),ensure_ascii=False,indent=2)+'\n')
            heartbeat('REGRESSION');model.qat_enabled=False
            model.load_state_dict(torch.load(work/'fp32.pt',map_location='cpu',weights_only=True))
            quality=dict(fp32=evaluate(model,rows['test'],tokenizer),ptq_exact=evaluate(MiniNanoRuntime.from_npz(work/'ptq.npz'),rows['test'],tokenizer),qat_exact=evaluate(MiniNanoRuntime.from_npz(work/'qat.npz'),rows['test'],tokenizer))
            fresh();result.update(kind='teacher-native-exact-reference-candidate',parameters=sum(p.numel() for p in model.parameters()),lineage=lineage,quality=quality,training_log=history,boundary='Previously observed test set is regression, not blind evidence; reference-only; platform execution remains mandatory')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat('REFERENCE_CANDIDATE_COMPLETE' if 'quality' in result else 'HOLD')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'candidate.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],candidate_complete='quality' in result)),flush=True)
    return 0 if 'quality' in result else 1


if __name__=='__main__':raise SystemExit(main())
