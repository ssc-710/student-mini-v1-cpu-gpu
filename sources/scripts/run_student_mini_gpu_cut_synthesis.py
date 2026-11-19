"""Synthesis-only preflight of the retimed GPU, with corrected macro views.

Preserves the 37 real SRAM macros, micron geometry and 10 ns constraint. Never
starts placement/route or issues baseline acceptance. Full GPU replay remains
an independent prerequisite before physical adoption.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.normalize_student_mini_macro_lef import normalize
from scripts.student_mini_macro_names import resolve_placement
from scripts.retry_student_mini_route import execute_locked_route,verify


def derived_config(source,placement,lefs):
    if len(lefs)!=6 or len(set(map(str,lefs)))!=6:raise ValueError('six unique real macro views required')
    if len(re.findall(r'^export MACRO_PLACEMENT_TCL = .+$',source,re.M))!=1:raise ValueError('ambiguous placement config')
    return source+'\n# Checked geometry-identical DBU and exact OpenDB macro names.\nexport ADDITIONAL_LEFS = '+' '.join(map(str,lefs))+f'\nexport MACRO_PLACEMENT_TCL = {placement}\n'


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-continuation',type=Path,required=True)
    args=parser.parse_args();parent=args.mapping_continuation.resolve()
    orfs=Path('/home/soclab/src/orfs-clean-aabf2a');tool=Path('/home/soclab/.local/bin/openroad');yosys=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    paths=[Path(__file__),tool.resolve(),yosys,yosys.parent.parent/'libexec/yosys',orfs/'flow/Makefile']
    paths += [ROOT/'scripts'/name for name in ('student_mini.py','normalize_student_mini_macro_lef.py','student_mini_macro_names.py','retry_student_mini_route.py')]
    paths += [p for folder in (orfs/'flow/scripts',orfs/'flow/platforms/sky130hd') for p in folder.rglob('*') if p.is_file()]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(dict(parent=str(parent),bindings=bindings),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-cut-synthesis'/identity;work.mkdir(parents=True,exist_ok=False)
    variant='student-mini-gpu-cut-'+identity[:16]
    results=orfs/'flow/results/sky130hd/vortex_physical_top'/variant
    logs=orfs/'flow/logs/sky130hd/vortex_physical_top'/variant
    start=time.monotonic();report=dict(status='HOLD',synthesis_complete=False,physical_evidence_complete=False,formal_baseline=False,full_gpu_equivalence=False,bindings=bindings,result_directory=str(results),metrics_directory=str(logs))
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        while not (parent/'completion.json').is_file():
            heartbeat('WAITING_FOR_RETIMED_MAPPING')
            if time.monotonic()-start>43200:raise TimeoutError('mapping wait expired')
            time.sleep(10)
        prior=json.loads((parent/'completion.json').read_text())
        if prior['status']!='RETIMED_GPU_SRAM_BOUNDARY_STAGE_PASS':raise ValueError('retimed mapping did not pass')
        packet=Path(prior['output']);mapped=packet.parent
        if sha(packet)!=prior['output_sha256']:raise ValueError('mapping receipt changed')
        value=json.loads(packet.read_text());verify(value['bindings']);bindings.update(value['bindings'])
        for name,digest in value['artifacts'].items():
            path=mapped/name
            if sha(path)!=digest:raise ValueError('mapping artifact changed')
            bindings[str(path)]=digest
        for path in (parent/'completion.json',packet):bindings[str(path)]=sha(path)
        corrected,names=resolve_placement((mapped/'macro-placement.tcl').read_text())
        if len(names)!=37:raise ValueError('retimed GPU macro geometry/count changed')
        placement=work/'macro-placement.tcl';placement.write_text(corrected)
        staged=ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
        bindings[str(staged)]=sha(staged);lefs=[];audits=[]
        for macro in json.loads(staged.read_text())['macros']:
            for name,row in macro['artifacts'].items():
                if not name.endswith('.lef'):continue
                source=Path(row['path'])
                if sha(source)!=row['sha256']:raise ValueError('original macro LEF changed')
                bindings[str(source)]=row['sha256'];text,audit=normalize(source.read_text())
                destination=work/source.name;destination.write_text(text);lefs.append(destination)
                audits.append(dict(**audit,source=str(source),derived=str(destination),source_sha256=sha(source),derived_sha256=sha(destination)))
        config=work/'config.mk';config.write_text(derived_config((mapped/'config.mk').read_text(),placement,lefs))
        for path in (config,placement,*lefs):bindings[str(path)]=sha(path)
        report.update(config=str(config),macro_count=len(names),clock_period_ns=10,threads=2,macro_unit_audits=audits)
        (work/'inputs.json').write_text(json.dumps(report,indent=2)+'\n')
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            command=['make','-j1','-C',str(orfs/'flow'),'synth',f'DESIGN_CONFIG={config}',f'COURSE_ROOT={ROOT}',f'FLOW_VARIANT={variant}',f'OPENROAD_EXE={tool}',f'YOSYS_EXE={yosys}','NUM_CORES=2']
            if execute_locked_route(command,work/'synth.log',1800,lambda _:heartbeat('SYNTHESIS_ONLY')):raise RuntimeError('retimed synthesis failed')
            for name in ('1_2_yosys.v','1_synth.odb','1_synth.sdc'):
                path=results/name
                if not path.is_file() or not path.stat().st_size:raise ValueError('missing synthesis artifact: '+name)
            verify(bindings)
            report.update(status='RETIMED_GPU_SYNTHESIS_STAGE_PASS',synthesis_complete=True,reason='New retimed netlist and real macro database built; not placement timing, route or full GPU acceptance')
    except Exception as error:report['reason']=f'{type(error).__name__}: {error}'
    heartbeat(report['status']);report['elapsed_seconds']=time.monotonic()-start
    report['artifacts']={str(p):sha(p) for folder in (work,results,logs) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=report['status'],reason=report['reason'])),flush=True)
    return 0 if report['synthesis_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
