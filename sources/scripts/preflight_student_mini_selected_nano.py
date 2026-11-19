"""Check the explicitly selected deployment in portable C, never as hardware PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha
from scripts.assemble_student_mini_selected_session import check_deployment
from scripts.export_student_mini_selected_image import resolve_bound
from scripts.export_student_mini_native_image import pack
from scripts.preflight_student_mini_native_nano import compile_library,load_library,compare
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def checked_payload(manifest,blob,runtime,tokenizer):
    expected,layout=pack(runtime,tokenizer,manifest['question'])
    if blob!=expected or hashlib.sha256(blob).hexdigest()!=manifest['image_sha256']:
        raise ValueError('deployment bytes differ from selected weights')
    if any(manifest.get(k)!=v for k,v in layout.items()):
        raise ValueError('deployment layout or prompt differs')


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--image-dir',type=Path,required=True)
    args=parser.parse_args();candidate_path=args.candidate.resolve();image=args.image_dir.resolve()
    candidate=json.loads(candidate_path.read_text());manifest_path=image/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    audit_path=(ROOT/manifest['quality_audit']['path']).resolve()
    if not audit_path.is_relative_to(ROOT) or sha(audit_path)!=manifest['quality_audit']['sha256']:
        raise ValueError('quality audit path/SHA differs')
    audit=json.loads(audit_path.read_text());deployment=check_deployment(candidate,audit,manifest)
    bindings={}
    for name,digest in audit['bindings'].items():
        path=resolve_bound(name).resolve()
        if sha(path)!=digest:raise ValueError('quality input changed: '+name)
        bindings[str(path)]=digest
    for name,digest in manifest['bindings'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=digest:raise ValueError('image input changed')
        bindings[str(path)]=digest
    if bindings.get(str(candidate_path))!=sha(candidate_path):raise ValueError('candidate not bound')
    checkpoint=candidate_path.parent/deployment['quantized'];inputs_path=candidate_path.parent/'inputs.json'
    if sha(checkpoint)!=deployment['quantized_sha256']:raise ValueError('selected checkpoint changed')
    inputs=json.loads(inputs_path.read_text());runtime=MiniNanoRuntime.from_npz(checkpoint)
    checked_payload(manifest,(image/'image.bin').read_bytes(),runtime,inputs['tokenizer'])
    compiler=Path(shutil.which('gcc') or '')
    if not compiler.is_file():raise RuntimeError('GCC unavailable')
    paths=[Path(__file__),compiler.resolve(),manifest_path,audit_path,checkpoint,inputs_path,image/'image.bin']
    paths += [ROOT/name for name in ('scripts/preflight_student_mini_native_nano.py',
        'scripts/assemble_student_mini_selected_session.py','scripts/export_student_mini_selected_image.py',
        'scripts/export_student_mini_native_image.py','shared/python/soc_ai_labs/student_mini_nano_runtime.py',
        'software/student_mini_native_nano.c','software/include/student_mini_native_nano.h',
        'software/operator_scalar.c','software/include/operator_scalar.h','software/include/numeric_luts.h')]
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-native-c-preflight'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',hardware_execution=False,formal_baseline=False,accepted_nano_session=False,
        deployment=deployment,bindings=bindings,numerical_pass=False)
    def fresh():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('preflight input changed')
    try:
        print(json.dumps(dict(work=str(work),status='WAITING_FOR_SERIAL_QUEUE')),flush=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            command=compile_library(work/'runtime.so');fn=load_library(work/'runtime.so');records=[]
            for split in ('validation','test'):
                for row in inputs['dataset'][split]:
                    prompt=[1,2]+[inputs['tokenizer']['characters'].get(c,5) for c in row['question']]+[3]
                    record=compare(fn,MiniNanoRuntime.from_npz(checkpoint),prompt)
                    records.append(dict(**record,split=split,question=row['question']))
            fresh()
            result.update(numerical_pass=all(r['status']=='PASS' for r in records),records=records,
                compile_command=command,library_sha256=sha(work/'runtime.so'))
            if not result['numerical_pass']:raise ValueError('selected C/Python state mismatch')
            result.update(status='SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS',reason='Portable host C only; no platform or quality acceptance inferred')
    except Exception as error:result.update(status='HOLD',reason=f'{type(error).__name__}: {error}')
    (work/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],hardware_execution=False)),flush=True)
    return 0 if result['status']=='SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
