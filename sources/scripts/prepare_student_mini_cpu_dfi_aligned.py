"""Preserve failed DFI evidence; align the three actual native read-valid paths."""
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
from scripts.retry_student_mini_route import verify,execute_locked_route
from scripts.student_mini_cpu_dfi_read_alignment import project,formal_bench
from scripts.student_mini_cpu_replay_sources import TOP


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','failed-replay','intervention'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();mapping=args.mapping.resolve();failed=args.failed_replay.resolve();receipt=args.intervention.resolve()
    parent=json.loads((mapping/'completion.json').read_text());replay=json.loads((failed/'completion.json').read_text());observed=json.loads(receipt.read_text())
    if (parent['status']!='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' or replay['status']!='HOLD'
        or replay['parent_mapping']!=str(mapping) or observed['replay']!=str(failed)
        or observed['status']!='ACTUAL_NANO_FAILURE_STOP_REQUESTED'):
        raise ValueError('same-candidate explicit failed whole replay required')
    for value in (parent,replay,observed):verify(value['bindings'])
    actual=failed/'console.log'
    if replay['artifacts'].get('console.log')!=sha(actual):raise ValueError('failed raw log changed')
    found=False
    with actual.open(errors='replace') as stream:
        for line in stream:
            if line.rstrip('\n')==observed['witness']:found=True;break
    if not found:raise ValueError('explicit failure witness missing')
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    rtl=ROOT/'integration/student-mini/cpu_dfi_output_cut.sv'
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths=[Path(__file__),ROOT/'scripts/student_mini_cpu_dfi_read_alignment.py',ROOT/'scripts/student_mini.py',
        ROOT/'scripts/retry_student_mini_route.py',mapping/'completion.json',mapping/'mapped.v',mapping/'mapped.json',
        failed/'completion.json',actual,receipt,tool,tool.parent.parent/'libexec/yosys',rtl,macro]
    bindings={str(p):sha(p) for p in paths}
    for value in (parent,replay,observed):bindings.update(value['bindings'])
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-aligned-boundary'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        whole_core_equivalence=False,cycle_equivalence=False,read_latency_cycles=2,dfi_output_latency_cycles=1,
        native_read_valid_added_cycles=1,local_formal_steps=24,mutants_killed=parent['mutants_killed'],
        mutation_scope='Inherited four common-output-register mutants; new read-valid alignment separately proved for 24 steps')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            bench=work/'contract.sv';bench.write_text(formal_bench())
            proof=work/'proof.ys';proof.write_text(f'read_verilog -formal -sv {rtl} {bench}\nprep -top contract -flatten\n'
                'async2sync\nchformal -lower\nsat -verify -prove-asserts -seq 24 -set-init-zero -show-public\n')
            code=execute_locked_route([str(tool),'-Q','-T','-s',str(proof)],work/'proof.log',60,lambda _:heartbeat('READ_VALID_LOCAL_PROOF'))
            if code or 'SAT proof finished - no model found: SUCCESS!' not in (work/'proof.log').read_text():raise ValueError('read-valid local proof failed')
            mapped=work/'mapped.v';mapped.write_text(project((mapping/'mapped.v').read_text()))
            script=work/'structure.ys';script.write_text(f'read_verilog -sv {mapped}\nread_verilog -lib {macro}\n'
                f'hierarchy -check -top {TOP}\nproc\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/mapped.json\n')
            if execute_locked_route([str(tool),'-Q','-T','-s',str(script)],work/'yosys.log',900,
                lambda _:heartbeat('CHECKING_READ_VALID_ALIGNMENT')):raise ValueError('aligned mapping failed')
            design=json.loads((work/'mapped.json').read_text())['modules'][TOP]
            prior=json.loads((mapping/'mapped.json').read_text())['modules'][TOP]
            if set(design['ports'])!=set(prior['ports']) or any(design['ports'][k]['direction']!=v['direction'] or len(design['ports'][k]['bits'])!=len(v['bits']) for k,v in prior['ports'].items()):raise ValueError('interface changed')
            macros=sorted(n for n,c in design['cells'].items() if c['type']=='student_mini_cpu_sram_32x1024')
            if macros!=sorted(parent['macro_instances']) or len(macros)!=29:raise ValueError('SRAM geometry changed')
            if len(design['cells'].get('dfi_read_valid_alignment',{}).get('connections',{}).get('response',[]))!=3:raise ValueError('three valid lanes missing')
            verify(bindings)
            result.update(status='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS',macro_count=29,macro_instances=macros,parent_mapping=str(mapping),
                reason='Common DFI output plus all three fixed read-valid chains aligned; local properties only, full replay and physical closure still required')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
