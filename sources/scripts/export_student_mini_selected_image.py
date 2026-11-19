"""Export the validation-selected PTQ/QAT stage, never silently default to QAT.

Independent reference-quality evidence is required. The image still is not a
qualified platform session and contains no golden output or lookup answers.
Legacy exports and their active consumers remain untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha
from scripts.audit_student_mini_native_quality import select_stage
from scripts.export_student_mini_native_image import pack,header
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def select_export(candidate,audit):
    if (candidate.get('kind')!='teacher-native-exact-reference-candidate'
            or audit.get('status')!='REFERENCE_QUALITY_STAGE_PASS'
            or audit.get('accepted_sessions')!=0 or audit.get('release_complete') is not False
            or audit.get('question_contamination')!=0):
        raise ValueError('independent reference quality stage required')
    selected=select_stage(audit['validation'])
    if audit['selection']['stage']!=selected:
        raise ValueError('selection differs from frozen validation-only policy')
    if audit['regression']!=candidate['quality']:
        raise ValueError('regression is not bound to candidate quality')
    for name,records in audit['regression'].items():
        if name not in ('fp32','ptq_exact','qat_exact') or len(records)!=12:
            raise ValueError('incomplete frozen regression')
    if set(audit['regression'])!={'fp32','ptq_exact','qat_exact'}:
        raise ValueError('missing numerical stage')
    if not all(r['passed'] is True for r in audit['validation'][selected]+audit['regression'][selected]):
        raise ValueError('selected stage has a failed validation/regression')
    lineage=candidate['lineage']
    if lineage['qat']['parent_fp32_sha256']!=lineage['fp32']['sha256']:
        raise ValueError('QAT parent does not match FP32')
    source=lineage['fp32' if selected=='ptq_exact' else 'qat']
    name=source['quantized']
    if Path(name).name!=name or '/' in name or '\\' in name or ':' in name or name in ('.','..'):
        raise ValueError('quantized checkpoint must be a local file name')
    return dict(stage=selected,quantized=name,quantized_sha256=source['quantized_sha256'],
        source_checkpoint_sha256=source['sha256'],parent_fp32_sha256=lineage['fp32']['sha256'])


def resolve_bound(name):
    prefix='/mnt/c/Users/admin/Downloads/open-soc-ai-labs/'
    return ROOT/name[len(prefix):] if name.startswith(prefix) else Path(name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--quality-audit',type=Path,required=True)
    parser.add_argument('--question',default='今天天气怎么样？')
    args=parser.parse_args()
    candidate_path=args.candidate.resolve();audit_path=args.quality_audit.resolve()
    candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    deployment=select_export(candidate,audit)
    input_path=candidate_path.parent/'inputs.json'
    checkpoint=candidate_path.parent/deployment['quantized']
    checked={}
    for name,digest in audit['bindings'].items():
        path=resolve_bound(name).resolve()
        if sha(path)!=digest:raise ValueError('quality audit input changed: '+name)
        checked[str(path)]=digest
    if checked.get(str(candidate_path))!=sha(candidate_path) or checked.get(str(input_path))!=sha(input_path):
        raise ValueError('audit belongs to another candidate or dataset')
    if checked.get(str(checkpoint))!=deployment['quantized_sha256'] or sha(checkpoint)!=deployment['quantized_sha256']:
        raise ValueError('selected checkpoint not independently bound')
    selection_path=audit_path.parent/'validation-selection.json'
    if audit['artifacts'].get(selection_path.name)!=sha(selection_path):
        raise ValueError('validation-before-test selection artifact changed')
    if json.loads(selection_path.read_text())!=audit['selection']:
        raise ValueError('selection artifact disagrees with audit')
    inputs=json.loads(input_path.read_text(encoding='utf-8'))
    runtime=MiniNanoRuntime.from_npz(checkpoint)
    blob,manifest=pack(runtime,inputs['tokenizer'],args.question)
    files=(candidate_path,audit_path,selection_path,input_path,checkpoint,Path(__file__),
        ROOT/'scripts/export_student_mini_native_image.py',ROOT/'scripts/audit_student_mini_native_quality.py',
        ROOT/'shared/python/soc_ai_labs/student_mini_nano_runtime.py')
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,question=args.question),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-native-image'/identity
    work.mkdir(parents=True,exist_ok=False)
    (work/'image.bin').write_bytes(blob)
    (work/'student_mini_native_image.h').write_text(header(manifest),encoding='utf-8')
    manifest.update(status='DEVELOPMENT_ONLY',target_execution=False,formal_baseline=False,
        deployment=deployment,quality_stage_only=True,bindings=bindings,
        quality_audit=dict(path=audit_path.relative_to(ROOT).as_posix(),sha256=sha(audit_path)),
        image_sha256=sha(work/'image.bin'),size_bytes=len(blob))
    (work/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tokens=runtime.generate(manifest['prompt_tokens'])
    reverse={v:k for k,v in inputs['tokenizer']['characters'].items()}
    golden=dict(kind='host-reference-only-never-target-input',tokens=tokens,
        text=''.join(reverse.get(t,'[UNK]') for t in tokens if t!=4),
        token_sha256=hashlib.sha256(struct.pack('<'+str(len(tokens))+'I',*tokens)).hexdigest(),
        image_sha256=manifest['image_sha256'],manifest_sha256=sha(work/'manifest.json'))
    (work/'host-golden.json').write_text(json.dumps(golden,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(work=str(work),stage=deployment['stage'],target_execution=False,image_bytes=len(blob))))


if __name__=='__main__':main()
