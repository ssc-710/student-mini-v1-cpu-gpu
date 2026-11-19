"""Bind proven private SRAM/DCR corrections to the 30-cycle GPU candidate.

Only hierarchy/macro consistency is established here. Whole-core replay and
fresh timing/route/activity remain mandatory; no original evidence is changed.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_binding_cuts import hold_idle_read_output
from scripts.student_mini_gpu_command_payload import preserve_read_payload
from scripts.generate_vortex_macro_placements import reachable_instances
from scripts.retry_student_mini_route import execute_locked_route,verify


def checked_proofs(idle,payload,cut):
    if (idle.get('status')!='GPU_IDLE_RETENTION_MACRO_STAGE_PASS' or len(idle.get('records',[]))!=40
        or idle.get('whole_gpu_equivalence') is not False):raise ValueError('full scoped SRAM proof required')
    grouped={}
    for row in idle['records']:grouped.setdefault(json.dumps(row['shape'],sort_keys=True),[]).append(row['seed'])
    if len(grouped)!=4 or any(sorted(v)!=list(range(1,11)) for v in grouped.values()):raise ValueError('macro/seed coverage differs')
    if (payload.get('status')!='GPU_READ_PAYLOAD_PROTOCOL_STAGE_PASS' or payload.get('depth')!=32
        or len(payload.get('records',[]))!=12 or not all(r['accepted'] for r in payload['records'])):
        raise ValueError('strengthened read payload proof required')
    if cut.get('status')!='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS' or cut.get('old_counters_reusable') is not False:
        raise ValueError('retimed arithmetic differential required')


def private_config(source,old,new,command):
    if source.count('include ')!=1 or 'export VERILOG_FILES =' in source:
        raise ValueError('unexpected original mapped configuration')
    return source.replace(old.as_posix(),new.as_posix())+'\n# Exact private correction used by synthesis and full replay.\nexport VERILOG_FILES := $(filter-out $(COURSE_ROOT)/shared/rtl/vortex_command_adapter.sv,$(VERILOG_FILES)) '+command.as_posix()+'\n'


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('boundary','idle-proof','payload-proof','cut-proof'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();parent=args.boundary.resolve()
    proof_paths=[getattr(args,name).resolve() for name in ('idle_proof','payload_proof','cut_proof')]
    idle,payload,cut=[json.loads(p.read_text()) for p in proof_paths];checked_proofs(idle,payload,cut)
    prior=json.loads((parent/'completion.json').read_text())
    if prior.get('boundary_complete') is not True or sum(prior['macro_counts'].values())!=37:
        raise ValueError('actual mapped GPU boundary required')
    bindings={}
    for report in (prior,idle,payload,cut):
        for name,digest in report['bindings'].items():
            if name in bindings and bindings[name]!=digest:raise ValueError('proof/source versions disagree')
            bindings[name]=digest
    if prior['bindings'].get(str(proof_paths[2]))!=sha(proof_paths[2]):
        raise ValueError('mapped candidate is not bound to this retimed arithmetic proof')
    for report,path in zip((idle,payload,cut),proof_paths):
        for name,digest in report.get('artifacts',{}).items():
            artifact=Path(name) if Path(name).is_absolute() else path.parent/name
            if sha(artifact)!=digest:raise ValueError('proof artifact changed')
            bindings[str(artifact)]=digest
    for name,digest in prior['artifacts'].items():
        artifact=parent/name
        if sha(artifact)!=digest:raise ValueError('parent mapped artifact changed')
        bindings[str(artifact)]=digest
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    paths=[Path(__file__),*proof_paths,parent/'completion.json',tool,
           ROOT/'scripts/student_mini_gpu_binding_cuts.py',ROOT/'scripts/student_mini_gpu_command_payload.py',
           ROOT/'scripts/generate_vortex_macro_placements.py',ROOT/'scripts/retry_student_mini_route.py']
    bindings.update({str(p):sha(p) for p in paths});verify(bindings)
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-repaired-boundary'/identity;work.mkdir(parents=True,exist_ok=False)
    project=work/'project-banked.v';project.write_text(hold_idle_read_output((parent/'project-banked.v').read_text()))
    command=work/'vortex_command_adapter.sv';command.write_text(preserve_read_payload((ROOT/'shared/rtl/vortex_command_adapter.sv').read_text()))
    for name in ('macros-blackboxes.v','macro-placement.tcl'):shutil.copyfile(parent/name,work/name)
    config=work/'config.mk';config.write_text(private_config((parent/'config.mk').read_text(),parent,work,command))
    sources=[project,work/'macros-blackboxes.v',command,*[ROOT/'shared/rtl'/name for name in
        ('vortex_banked_large_sram_wrappers.sv','vortex_memory_adapter.sv','vortex_physical_top.sv')]]
    for p in (*sources,config,work/'macro-placement.tcl'):bindings[str(p)]=sha(p)
    result=dict(status='HOLD',boundary_complete=False,physical_evidence_complete=False,formal_baseline=False,
        simulation_asic_equivalence=False,bindings=bindings,parent=str(parent),logical_shapes=prior['logical_shapes'],
        macro_counts=prior['macro_counts'],placements=prior['placements'],private_command_adapter=str(command),
        arithmetic_latency=30,old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            script=work/'mapped.ys';script.write_text('read_verilog -sv '+' '.join(map(str,sources))+
                f'; hierarchy -check -top vortex_physical_top; proc; opt_clean; check -assert; write_json {work}/mapped.json\n')
            if execute_locked_route([str(tool),'-Q','-T','-s',str(script)],work/'mapped.log',900,heartbeat):raise RuntimeError('repaired GPU hierarchy failed')
            design=json.loads((work/'mapped.json').read_text())
            instances=reachable_instances(design,set(prior['macro_counts']),top='vortex_physical_top',prefix='')
            if Counter(name for _,name in instances)!=Counter(prior['macro_counts']):raise ValueError('macro multiplicity changed')
            if sum(c['type']=='Vortex' for c in design['modules']['vortex_physical_top']['cells'].values())!=1:raise ValueError('core boundary lost')
            verify(bindings)
        result.update(status='REPAIRED_GPU_BOUNDARY_STAGE_PASS',boundary_complete=True,
            reason='Retimed project plus private proven RAM/DCR changes passed hierarchy/macro checks; whole replay and all physical gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['boundary_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
