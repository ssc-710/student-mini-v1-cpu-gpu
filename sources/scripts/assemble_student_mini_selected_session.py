"""Join a target transcript to its validation-selected deployment checkpoint.

Keeps legacy QAT-only receipts unchanged. This numerical join never asserts
physical, independent quality, protocol or complete-release acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha
from scripts.export_student_mini_selected_image import select_export,resolve_bound
from scripts.export_student_mini_native_image import pack
from scripts.assemble_student_mini_native_session import reference,transcript
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def check_deployment(candidate,audit,manifest):
    expected=select_export(candidate,audit)
    if manifest.get('deployment')!=expected:
        raise ValueError('image stage/checkpoint does not match validated selection')
    if manifest.get('contains_expected_tokens') is not False:
        raise ValueError('input-only deployment image required')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--image-dir',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--platform',choices=('cpu','gpu'),required=True)
    args=parser.parse_args();run=args.run.resolve();image=args.image_dir.resolve();candidate_path=args.candidate.resolve()
    manifest_path=image/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
    quality_path=(ROOT/manifest['quality_audit']['path']).resolve()
    if not quality_path.is_relative_to(ROOT) or sha(quality_path)!=manifest['quality_audit']['sha256']:
        raise ValueError('quality audit SHA/path differs')
    audit=json.loads(quality_path.read_text(encoding='utf-8'))
    deployment=check_deployment(candidate,audit,manifest)
    for name,digest in audit['bindings'].items():
        if sha(resolve_bound(name))!=digest:raise ValueError('quality lineage input changed')
    if manifest['bindings'].get(candidate_path.relative_to(ROOT).as_posix())!=sha(candidate_path):
        raise ValueError('image belongs to another candidate')
    for name,digest in manifest['bindings'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=digest:raise ValueError('image source changed')
    checkpoint=candidate_path.parent/deployment['quantized']
    if sha(checkpoint)!=deployment['quantized_sha256']:raise ValueError('quantized weights changed')
    inputs_path=candidate_path.parent/'inputs.json';inputs=json.loads(inputs_path.read_text(encoding='utf-8'))
    runtime=MiniNanoRuntime.from_npz(checkpoint)
    expected_image,expected_manifest=pack(runtime,inputs['tokenizer'],manifest['question'])
    if ((image/'image.bin').read_bytes()!=expected_image or sha(image/'image.bin')!=manifest['image_sha256']
            or any(manifest.get(k)!=v for k,v in expected_manifest.items())):
        raise ValueError('runtime image bytes/layout disagree with selected model')
    completion_path=run/'completion.json';completion=json.loads(completion_path.read_text())
    if completion.get('target_run_complete') is not True:raise ValueError('target run incomplete')
    if completion['bindings'].get(str(manifest_path))!=sha(manifest_path):
        raise ValueError('target did not execute this exact deployment image')
    files=[completion_path,manifest_path,quality_path,candidate_path,inputs_path,checkpoint,image/'image.bin',
        Path(__file__),ROOT/'scripts/export_student_mini_selected_image.py',
        ROOT/'scripts/export_student_mini_native_image.py',ROOT/'scripts/assemble_student_mini_native_session.py']
    for name,digest in completion['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('target source changed')
    for name,digest in completion['artifacts'].items():
        path=Path(name) if Path(name).is_absolute() else run/name
        if sha(path)!=digest:raise ValueError('target artifact changed')
        files.append(path)
    log=run/('console.log' if args.platform=='cpu' else 'execute.log');files.append(log)
    joined=transcript(log.read_text(),args.platform,reference(runtime,manifest['prompt_tokens']),len(manifest['prompt_tokens']))
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'grading/evidence/student-mini-v1/selected-native-sessions'/identity;out.mkdir(parents=True,exist_ok=False)
    result=dict(status='NUMERICAL_SESSION_STAGE_PASS',accepted_nano_session=False,platform=args.platform,
        backend='vexriscv-rtl' if args.platform=='cpu' else 'simx',performance_eligible=False,
        physical_complete=False,quality_complete=False,reference_quality_stage=True,
        deployment=deployment,question=manifest['question'],bindings=bindings,**joined,
        reason='Full actual tokens/states match the explicitly selected PTQ/QAT model; whole-platform acceptance remains separate')
    path=out/'session.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),stage=deployment['stage'],accepted=False)))


if __name__=='__main__':main()
