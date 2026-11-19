"""Re-evaluate a frozen candidate, choosing deployment stage by validation only.

The twelve observed test questions are regression evidence, not a fresh blind
test. No training, model replacement, platform session, or release is performed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ['CUDA_VISIBLE_DEVICES']=''
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha


def select_stage(validation):
    """Frozen tie break: PTQ before QAT; test outcomes are not an input."""
    if set(validation)!={'fp32','ptq_exact','qat_exact'}:
        raise ValueError('all numerical stages required')
    for values in validation.values():
        if len(values)!=8 or any(type(r['passed']) is not bool for r in values):
            raise ValueError('complete frozen validation set required')
    return max(('ptq_exact','qat_exact'),key=lambda stage:sum(r['passed'] for r in validation[stage]))


def split_check(dataset,question):
    if set(dataset)!={'train','validation','test'}:raise ValueError('frozen split names differ')
    sets={name:{row['question'] for row in rows} for name,rows in dataset.items()}
    if any(len(sets[name])!=len(rows) for name,rows in dataset.items()):
        raise ValueError('duplicate questions within split')
    if any(sets[a]&sets[b] for a,b in [('train','validation'),('train','test'),('validation','test')]):
        raise ValueError('question contamination between splits')
    if question in sets['train'] or question not in sets['test']:
        raise ValueError('weather acceptance question must be held out')


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    args=parser.parse_args();candidate_path=args.candidate.resolve()
    candidate=json.loads(candidate_path.read_text());folder=candidate_path.parent
    inputs=json.loads((folder/'inputs.json').read_text())
    if candidate['kind']!='teacher-native-exact-reference-candidate':raise ValueError('wrong candidate type')
    lineage=candidate['lineage']
    if lineage['qat']['parent_fp32_sha256']!=lineage['fp32']['sha256']:
        raise ValueError('QAT is not descended from the same FP32 checkpoint')
    bindings=dict(candidate['bindings'])
    for stage in ('fp32','qat'):
        for field in ('checkpoint','quantized'):
            path=folder/lineage[stage][field]
            expected=lineage[stage]['sha256' if field=='checkpoint' else 'quantized_sha256']
            if sha(path)!=expected:raise ValueError('checkpoint/export bytes changed')
            bindings[str(path)]=expected
    for path in (Path(__file__),candidate_path,folder/'inputs.json',ROOT/'grading/student-mini/spec.json'):
        bindings[str(path)]=sha(path)
    plan=dict(bindings=bindings,selection='validation-only pass count; PTQ before QAT for ties',
        test_disclosure='Previously observed test questions; regression only, not fresh blind evidence',
        model_replacement=False,training=False)
    identity=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/native-quality'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    started=time.monotonic();result=dict(status='HOLD',accepted_sessions=0,release_complete=False,bindings=bindings)
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('quality input changed')
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        fresh();spec=json.loads((ROOT/'grading/student-mini/spec.json').read_text())
        split_check(inputs['dataset'],spec['nano']['held_out_question'])
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            import torch
            from scripts.train_student_mini_native_nano import evaluate
            from soc_ai_labs.student_mini_nano_model import MiniNativeNano
            from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime
            if torch.version.cuda is not None:raise ValueError('CPU-only teacher environment required')
            torch.set_num_threads(2);torch.set_num_interop_threads(1)
            model=MiniNativeNano().cpu();model.qat_enabled=False
            model.load_state_dict(torch.load(folder/lineage['fp32']['checkpoint'],map_location='cpu',weights_only=True))
            models={'fp32':model,'ptq_exact':MiniNanoRuntime.from_npz(folder/lineage['fp32']['quantized']),
                'qat_exact':MiniNanoRuntime.from_npz(folder/lineage['qat']['quantized'])}
            heartbeat('VALIDATION')
            validation={name:evaluate(value,inputs['dataset']['validation'],inputs['tokenizer']) for name,value in models.items()}
            selected=select_stage(validation)
            selection=dict(stage=selected,validation_counts={name:sum(r['passed'] for r in rows) for name,rows in validation.items()},
                rule=plan['selection'])
            (work/'validation-selection.json').write_text(json.dumps(selection,indent=2)+'\n')
            heartbeat('REGRESSION')
            regression={name:evaluate(value,inputs['dataset']['test'],inputs['tokenizer']) for name,value in models.items()}
            if regression!=candidate['quality']:raise ValueError('frozen candidate regression cannot be reproduced')
            passed=all(r['passed'] for r in validation[selected]+regression[selected])
            fresh();result.update(status='REFERENCE_QUALITY_STAGE_PASS' if passed else 'HOLD_VALIDATION_OR_REGRESSION',
                selection=selection,validation=validation,regression=regression,
                test_disclosure=plan['test_disclosure'],question_contamination=0,
                reason='Exact reference only; platform execution and independent quality review remain',
                torch_version=torch.__version__,training_device='cpu')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='REFERENCE_QUALITY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
