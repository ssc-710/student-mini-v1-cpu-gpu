"""Prove and map a common DFI output boundary after the actual CTS HOLD."""
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
from scripts.student_mini_cpu_dfi_cut import project,formal_bench,mutants,WIDTH
from scripts.student_mini_cpu_replay_sources import TOP


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','replay','route'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();mapping=args.mapping.resolve();replay=args.replay.resolve();route=args.route.resolve()
    parent=json.loads((mapping/'completion.json').read_text());whole=json.loads(replay.read_text())
    physical=json.loads((route/'completion.json').read_text())
    if (parent['status']!='CPU_ROM_REQUEST_MAPPING_STAGE_PASS' or parent['macro_count']!=29
        or whole['status']!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'
        or whole['parent_mapping']!=str(mapping) or whole['transcript_join']['baseline_records']!=1000
        or physical['status']!='HOLD' or physical['clock_period_ns']!=10):
        raise ValueError('qualified complete same-boundary replay and physical HOLD required')
    for item in (parent,whole,physical):verify(item['bindings'])
    report=Path(physical['reports_directory'])/'4_cts_final.rpt'
    metrics=Path(physical['metrics_directory'])/'4_1_cts.json'
    for path in (report,metrics):
        if physical['artifacts'].get(str(path))!=sha(path):raise ValueError('CTS artifact changed')
    timing=report.read_text()
    if ('Endpoint: build_soc_coursesimsoc_dfi_p0_wrdata[87]' not in timing
        or 'slack (VIOLATED)' not in timing
        or json.loads(metrics.read_text())['cts__timing__setup__ws']>=0
        or physical['bindings'].get(str(mapping/'mapped.v'))!=sha(mapping/'mapped.v')):
        raise ValueError('same-source DFI output timing violation required')
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    rtl=ROOT/'integration/student-mini/cpu_dfi_output_cut.sv'
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths=[Path(__file__),ROOT/'scripts/student_mini_cpu_dfi_cut.py',ROOT/'scripts/student_mini.py',
        ROOT/'scripts/export_student_mini_cpu_boundary.py',ROOT/'scripts/student_mini_cpu_replay_sources.py',
        ROOT/'scripts/retry_student_mini_route.py',mapping/'completion.json',mapping/'mapped.v',
        mapping/'mapped.json',replay,route/'completion.json',report,metrics,rtl,macro,tools/'yosys',tools.parent/'libexec/yosys']
    bindings={str(p):sha(p) for p in paths}
    for item in (parent,whole,physical):bindings.update(item['bindings'])
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-output-boundary'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        whole_core_equivalence=False,cycle_equivalence=False,read_latency_cycles=2,dfi_output_latency_cycles=1,
        scope='169-bit common DFI output register; bounded local proof, not whole-controller protocol acceptance')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            bench=work/'contract.sv';bench.write_text(formal_bench());bindings[str(bench)]=sha(bench)
            outcomes=[]
            for name,value in dict(original=rtl.read_text(),**mutants(rtl.read_text())).items():
                source=work/(name+'.sv');source.write_text(value)
                script=work/(name+'.ys');script.write_text(
                    f'read_verilog -formal -sv {source} {bench}\nprep -top contract -flatten\n'
                    'async2sync\nchformal -lower\nsat -verify -prove-asserts -seq 24 -set-init-zero -show-public\n')
                code=execute_locked_route([str(tools/'yosys'),'-Q','-T','-s',str(script)],work/(name+'.log'),60,
                    lambda _:heartbeat('LOCAL_FORMAL_'+name))
                log=(work/(name+'.log')).read_text()
                if name=='original':
                    if code or 'SAT proof finished - no model found: SUCCESS!' not in log:raise ValueError('local DFI proof failed')
                elif code==0 or 'proof did fail' not in log:raise ValueError('DFI mutation survived or tool failed: '+name)
                outcomes.append(dict(name=name,exit_code=code,expected='PASS' if name=='original' else 'COUNTEREXAMPLE'))
            mapped=work/'mapped.v';mapped.write_text(project((mapping/'mapped.v').read_text(),rtl.read_text()))
            script=work/'structure.ys';script.write_text(f'read_verilog -sv {mapped}\nread_verilog -lib {macro}\n'
                f'hierarchy -check -top {TOP}\nproc\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/mapped.json\n')
            if execute_locked_route([str(tools/'yosys'),'-Q','-T','-s',str(script)],work/'yosys.log',900,
                lambda _:heartbeat('CHECKING_DFI_BOUNDARY_STRUCTURE')):raise ValueError('DFI projection mapping failed')
            design=json.loads((work/'mapped.json').read_text())['modules'][TOP]
            original=json.loads((mapping/'mapped.json').read_text())['modules'][TOP]
            ports=design['ports'];prior=original['ports']
            if set(ports)!=set(prior) or any(ports[k]['direction']!=v['direction'] or len(ports[k]['bits'])!=len(v['bits']) for k,v in prior.items()):
                raise ValueError('external geometry changed')
            macros=sorted(n for n,c in design['cells'].items() if c['type']=='student_mini_cpu_sram_32x1024')
            if macros!=sorted(parent['macro_instances']) or len(macros)!=29:raise ValueError('SRAM geometry changed')
            boundary=design['cells'].get('dfi_output_boundary',{})
            if len(boundary.get('connections',{}).get('response',[]))!=WIDTH:raise ValueError('complete DFI boundary missing')
            verify(bindings)
            result.update(status='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS',macro_count=29,macro_instances=macros,
                parent_mapping=str(mapping),local_formal_steps=24,mutants_killed=4,outcomes=outcomes,
                reason='All 169 output bits share one register, local bounded proof and four mutants pass; full CPU replay/new timing still required')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
