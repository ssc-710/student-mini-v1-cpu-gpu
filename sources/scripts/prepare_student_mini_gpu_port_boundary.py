"""Add proven port ordering to the private 30-cycle SRAM/DCR repaired boundary.

Hierarchy consistency only. Whole-core replay and new physical implementation
are separate gates; historical source-bound runs remain byte-identical.
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
from scripts.student_mini_gpu_port_packing import restore_core_port_order,verify_export_order
from scripts.generate_vortex_macro_placements import reachable_instances
from scripts.retry_student_mini_route import execute_locked_route,verify


def private_config(source,parent,work,top):
    if 'export VERILOG_FILES := $(filter-out ' not in source:raise ValueError('private SRAM/DCR parent required')
    return source.replace(parent.as_posix(),work.as_posix())+'\n# Match the checked core-side sv2v payload ABI.\nexport VERILOG_FILES := $(filter-out $(COURSE_ROOT)/shared/rtl/vortex_physical_top.sv,$(VERILOG_FILES)) '+top.as_posix()+'\n'


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repaired-boundary',type=Path,required=True)
    parser.add_argument('--port-proof',type=Path,required=True)
    args=parser.parse_args();parent=args.repaired_boundary.resolve();proof=args.port_proof.resolve()
    start=time.monotonic()
    while not (parent/'completion.json').exists():
        if time.monotonic()-start>43200:raise TimeoutError('bounded parent wait expired')
        time.sleep(10)
    prior=json.loads((parent/'completion.json').read_text());port=json.loads(proof.read_text())
    if prior.get('boundary_complete') is not True or prior.get('arithmetic_latency')!=30 or sum(prior['macro_counts'].values())!=37:
        raise ValueError('repaired 30-cycle mapped parent required')
    if port.get('status')!='GPU_PORT_PACKING_SEAM_STAGE_PASS' or port.get('whole_core_equivalence') is not False or len(port['records'])!=20 or not all(r['accepted'] for r in port['records']):
        raise ValueError('full scoped port proof required')
    for label in ('fixed','original'):
        if sorted(r['seed'] for r in port['records'] if r['variant']==label)!=list(range(1,11)):raise ValueError('port seeds incomplete')
    bindings={}
    for report,folder in ((prior,parent),(port,proof.parent)):
        for name,digest in report['bindings'].items():
            if name in bindings and bindings[name]!=digest:raise ValueError('source versions disagree')
            bindings[name]=digest
        for name,digest in report['artifacts'].items():
            path=Path(name) if Path(name).is_absolute() else folder/name
            if sha(path)!=digest:raise ValueError('parent artifact changed')
            bindings[str(path)]=digest
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    paths=[Path(__file__),proof,parent/'completion.json',tool,ROOT/'scripts/student_mini_gpu_port_packing.py',ROOT/'scripts/generate_vortex_macro_placements.py',ROOT/'scripts/retry_student_mini_route.py']
    bindings.update({str(p):sha(p) for p in paths});verify(bindings)
    verify_export_order((parent/'project-banked.v').read_text())
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-port-boundary'/identity;work.mkdir(parents=True,exist_ok=False)
    for name in ('project-banked.v','vortex_command_adapter.sv','macros-blackboxes.v','macro-placement.tcl'):shutil.copyfile(parent/name,work/name)
    top=work/'vortex_physical_top.sv';top.write_text(restore_core_port_order((ROOT/'shared/rtl/vortex_physical_top.sv').read_text()))
    config=work/'config.mk';config.write_text(private_config((parent/'config.mk').read_text(),parent,work,top))
    sources=[work/name for name in ('project-banked.v','vortex_command_adapter.sv','macros-blackboxes.v','vortex_physical_top.sv')]
    sources += [ROOT/'shared/rtl'/name for name in ('vortex_banked_large_sram_wrappers.sv','vortex_memory_adapter.sv')]
    for p in (*sources,config,work/'macro-placement.tcl'):bindings[str(p)]=sha(p)
    result=dict(status='HOLD',boundary_complete=False,physical_evidence_complete=False,formal_baseline=False,
        simulation_asic_equivalence=False,bindings=bindings,parent=str(parent),logical_shapes=prior['logical_shapes'],
        macro_counts=prior['macro_counts'],placements=prior['placements'],arithmetic_latency=30,
        private_command_adapter=str(work/'vortex_command_adapter.sv'),private_physical_top=str(top),old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            script=work/'mapped.ys';script.write_text('read_verilog -sv '+' '.join(map(str,sources))+f'; hierarchy -check -top vortex_physical_top; proc; opt_clean; check -assert; write_json {work}/mapped.json\n')
            if execute_locked_route([str(tool),'-Q','-T','-s',str(script)],work/'mapped.log',900,heartbeat):raise RuntimeError('port-corrected hierarchy failed')
            design=json.loads((work/'mapped.json').read_text())
            instances=reachable_instances(design,set(prior['macro_counts']),top='vortex_physical_top',prefix='')
            if Counter(name for _,name in instances)!=Counter(prior['macro_counts']):raise ValueError('macro multiplicity changed')
            verify(bindings);result.update(status='GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS',boundary_complete=True,
                reason='30-cycle/SRAM/DCR/port corrections bound; hierarchy only, not whole-core or physical acceptance')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['boundary_complete'] else 1

if __name__=='__main__':raise SystemExit(main())
