"""Replay a new input-only model through the unchanged mapped CPU/ROM binary.

Only external SDRAM initialization changes. Every old baseline output/counter
must still match, and new Nano states must match the selected model reference.
This is cold-start numerical evidence, not reset/physical/release acceptance.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha
from scripts.student_mini_cpu_loader_banks import bank_images,checked_original,checked_header,changed_loader
from scripts.retry_student_mini_route import execute_locked_route,verify
from scripts.assemble_student_mini_cpu_results import parse
from scripts.assemble_student_mini_native_session import reference,transcript
from scripts.assemble_student_mini_selected_session import check_deployment
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def collect_console(path):
    rows=[];terminal=0
    with path.open() as handle:
        for line in handle:
            if line.startswith('CPU_BOUNDARY_REPLAY_COMPLETE cycles='):terminal+=1
            if line.startswith(('STUDENT_CPU ','STUDENT_CPU_','STUDENT_NATIVE_')):rows.append(line)
    if terminal!=1:raise ValueError('missing/duplicate full mapped CPU completion')
    return ''.join(rows)


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('replay','image-dir','old-image-dir','candidate','preflight'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();prior=args.replay.resolve();image=args.image_dir.resolve();old_image=args.old_image_dir.resolve()
    candidate_path=args.candidate.resolve();preflight=args.preflight.resolve()
    parent=json.loads((prior/'completion.json').read_text())
    if parent.get('status')!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':raise ValueError('actual mapped CPU parent required')
    bindings=dict(parent['bindings']);verify(bindings)
    for name,digest in parent['artifacts'].items():
        path=prior/name
        if sha(path)!=digest:raise ValueError('parent replay artifact changed')
        bindings[str(path)]=digest
    cpu=Path(parent['parent_cpu']);old_manifest=json.loads((old_image/'manifest.json').read_text())
    if bindings.get(str(old_image/'manifest.json'))!=sha(old_image/'manifest.json'):
        raise ValueError('old image does not belong to the executed ROM')
    if sha(old_image/'image.bin')!=old_manifest['image_sha256']:raise ValueError('old model changed')
    checked_header((old_image/'student_mini_native_image.h').read_text(),(image/'student_mini_native_image.h').read_text())
    manifest=json.loads((image/'manifest.json').read_text());candidate=json.loads(candidate_path.read_text())
    audit_path=(ROOT/manifest['quality_audit']['path']).resolve()
    if not audit_path.is_relative_to(ROOT) or sha(audit_path)!=manifest['quality_audit']['sha256']:raise ValueError('quality audit differs')
    audit=json.loads(audit_path.read_text());deployment=check_deployment(candidate,audit,manifest)
    for name,digest in manifest['bindings'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=digest:raise ValueError('selected image source changed')
        bindings[str(path)]=digest
    checkpoint=candidate_path.parent/deployment['quantized']
    if sha(checkpoint)!=deployment['quantized_sha256'] or sha(image/'image.bin')!=manifest['image_sha256']:
        raise ValueError('selected payload differs')
    loader=(cpu/'loader.bin').read_bytes();old_inputs=json.loads((cpu/'inputs.json').read_text())
    checked_original(loader,[(prior/f'sim_mem_{i}.init').read_text() for i in range(1,5)])
    replacement=changed_loader(loader,(old_image/'image.bin').read_bytes(),(image/'image.bin').read_bytes(),old_inputs['native_image_offset'])
    binary=prior/'obj/Vcpu_boundary_replay'
    if bindings.get(str(binary))!=sha(binary):raise ValueError('executed binary not bound')
    paths=[Path(__file__),prior/'completion.json',cpu/'loader.bin',image/'manifest.json',image/'image.bin',image/'student_mini_native_image.h',candidate_path,checkpoint,audit_path]
    paths += [ROOT/'scripts'/name for name in ('student_mini_cpu_loader_banks.py','assemble_student_mini_cpu_results.py',
        'assemble_student_mini_native_session.py','assemble_student_mini_selected_session.py','retry_student_mini_route.py')]
    bindings.update({str(p):sha(p) for p in paths})
    plan=dict(bindings=bindings,preflight=str(preflight),same_rom=True,only_external_model_input_changed=True)
    identity=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-cpu-replay'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(plan,indent=2)+'\n')
    for path in prior.glob('*.init'):shutil.copyfile(path,work/path.name)
    for i,words in enumerate(bank_images(replacement),1):
        (work/f'sim_mem_{i}.init').write_text(''.join(f'{word:032x}\n' for word in words))
    (work/'loader.bin').write_bytes(replacement)
    for path in [work/'loader.bin',*work.glob('*.init')]:bindings[str(path)]=sha(path)
    start=time.monotonic();result=dict(status='HOLD',target_run_complete=False,formal_baseline=False,
        accepted_nano_session=False,physical_evidence_complete=False,warm_reset_qualified=False,
        deployment=deployment,bindings=bindings,same_rom=True,binary_sha256=sha(binary))
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        heartbeat('WAITING_FOR_SELECTED_C_PREFLIGHT');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SELECTED_C_PREFLIGHT')),flush=True)
        while not preflight.is_file():
            if time.monotonic()-start>43200:raise TimeoutError('preflight wait expired')
            time.sleep(10)
        checked=json.loads(preflight.read_text())
        if (checked.get('status')!='SELECTED_NATIVE_C_PREFLIGHT_STAGE_PASS'
            or checked['bindings'].get(str(image/'manifest.json'))!=sha(image/'manifest.json')):
            raise ValueError('selected preflight not passed or wrong image')
        bindings.update(checked['bindings']);bindings[str(preflight)]=sha(preflight)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            command=['bash','-c','ulimit -c 0; cd -- "$1" || exit; exec "$2"','selected-cpu',str(work),str(binary)]
            if execute_locked_route(command,work/'raw-console.log',3600,lambda _:heartbeat('EXECUTING_SELECTED_MODEL_ON_MAPPED_CPU')):
                raise RuntimeError('actual mapped CPU execution failed')
            console=collect_console(work/'raw-console.log')
            original=collect_console(prior/'console.log')
            if parse(console,1000)!=parse(original,1000):raise ValueError('baseline outputs/counters changed')
            joined=transcript(console,'cpu',reference(MiniNanoRuntime.from_npz(checkpoint),manifest['prompt_tokens']),len(manifest['prompt_tokens']))
            (work/'console.log').write_text(console)
            verify(bindings)
        result.update(status='SELECTED_MAPPED_CPU_NUMERICAL_STAGE_PASS',target_run_complete=True,
            baseline_records=1000,native_join=joined,frequency_hz=100000000,
            reason='New input-only model actually executed; unchanged mapped RTL/ROM/binary; all baseline and selected Nano states independently checked')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['target_run_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
