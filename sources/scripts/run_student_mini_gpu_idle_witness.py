"""Validate the isolated idle-retention repair against every reachable macro.

No whole-core or physical claim. Same-address collisions remain excluded and
must not be inferred from this read/hold/reset experiment.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route,verify
from scripts.run_student_mini_gpu_memory_witness import bench,parse_log
from scripts.student_mini_gpu_binding_cuts import hold_idle_read_output,retained_transactions


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary',type=Path,required=True)
    args=parser.parse_args();boundary=args.boundary.resolve()
    parent_path=boundary/'completion.json';parent=json.loads(parent_path.read_text())
    if parent.get('boundary_complete') is not True:raise ValueError('mapped source required')
    bindings=dict(parent['bindings']);verify(bindings)
    source=boundary/'bindings.sv'
    if sha(source)!=parent['artifacts']['bindings.sv']:raise ValueError('mapped binding changed')
    staged=ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    models=[]
    for macro in json.loads(staged.read_text())['macros']:
        for name,row in macro['artifacts'].items():
            if not name.endswith('.v'):continue
            path=Path(row['path'])
            if sha(path)!=row['sha256']:raise ValueError('actual macro model changed')
            models.append(path)
    toolroot=Path('/home/soclab/tools/oss-cad-suite')
    paths=[Path(__file__),parent_path,source,staged,*models,ROOT/'shared/rtl/vortex_banked_large_sram_wrappers.sv']
    paths += [ROOT/'scripts'/name for name in ('student_mini_gpu_binding_cuts.py','run_student_mini_gpu_memory_witness.py','retry_student_mini_route.py')]
    paths += [toolroot/folder/name for folder in ('bin','libexec') for name in ('iverilog','vvp')]
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-idle-retention'/identity;work.mkdir(parents=True,exist_ok=False)
    repaired=work/'bindings.sv';repaired.write_text(hold_idle_read_output(source.read_text()));bindings[str(repaired)]=sha(repaired)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings,parent=str(boundary),single_change='retain last valid macro word during idle'),indent=2)+'\n')
    start=time.monotonic();result=dict(status='HOLD',bindings=bindings,records=[],whole_gpu_equivalence=False,physical_evidence_complete=False,same_address_collision_qualified=False)
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            for index,shape in enumerate(parent['logical_shapes']):
                folder=work/str(index);folder.mkdir();testbench=folder/'bench.sv';testbench.write_text(bench(shape));binary=folder/'bench.vvp'
                command=[str(toolroot/'bin/iverilog'),'-g2012','-s','memory_witness','-o',str(binary),str(testbench),str(repaired),str(ROOT/'shared/rtl/vortex_banked_large_sram_wrappers.sv'),*map(str,models)]
                if execute_locked_route(command,folder/'compile.log',60,heartbeat):raise RuntimeError('memory compile failed')
                for seed in range(1,11):
                    rows=retained_transactions(shape,seed);inputs=folder/f'seed-{seed}.txt';log=folder/f'seed-{seed}.log'
                    inputs.write_text(''.join(f"{r['reset']} {r['read']} {r['write']} {r['mask']:x} {r['write_address']:x} {r['read_address']:x} {r['input_hex']} 1 {r['golden_hex']}\n" for r in rows))
                    if execute_locked_route([str(toolroot/'bin/vvp'),str(binary),'+input='+str(inputs)],log,60,heartbeat):raise RuntimeError(f'idle retention failed at shape={index} seed={seed}')
                    samples=parse_log(log.read_text(),rows);output=folder/f'seed-{seed}.json';output.write_text(json.dumps(samples,indent=2)+'\n')
                    result['records'].append(dict(shape=shape,seed=seed,samples=len(samples),idle_samples=sum(r['label']=='idle-retention' for r in rows),output=str(output),sha256=sha(output)))
            verify(bindings)
        result.update(status='GPU_IDLE_RETENTION_MACRO_STAGE_PASS',reason='All reachable macro shapes, seed 1-10, every output/idle/reset checked; whole GPU and physical revalidation mandatory')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='GPU_IDLE_RETENTION_MACRO_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
