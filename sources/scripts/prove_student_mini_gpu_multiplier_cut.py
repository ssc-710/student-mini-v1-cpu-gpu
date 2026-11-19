"""Source-bound actual RTL differential and mutation checks, not GPU signoff."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_multiplier_cut import project, mutants, PINNED_SHA256
from scripts.retry_student_mini_route import execute_locked_route, verify


def validate_transactions(text):
    rows=[json.loads(line) for line in text.splitlines() if line.startswith('{')]
    markers=[line for line in text.splitlines() if line.startswith('MULTIPLIER_CUT_COMPLETE ')]
    if len(markers)!=1 or len(rows)!=43211: raise ValueError('incomplete multiplier differential')
    identities=[(row['seed'],row['id']) for row in rows]
    expected={(seed,index) for seed in range(1,11) for index in range(4321)} | {(10,4321)}
    if len(set(identities))!=len(rows) or set(identities)!=expected:
        raise ValueError('duplicate or missing multiplier transaction')
    counts={seed:sum(row['seed']==seed for row in rows) for seed in range(1,11)}
    if min(counts.values())<4321: raise ValueError('missing seed or boundary coverage')
    for row in rows:
        if (row['match'] is not True or row['enabled'] is not True
                or row['golden_bits']!=row['actual_bits'] or row['golden_bits']!=row['original_bits']
                or int(row['xor_delta'],16)!=0): raise ValueError('multiplier output differs')
        # Re-evaluate the independent signed integer golden, not just its flag.
        operands=[]
        for key in ('input_a_bits','input_b_bits'):
            value=row[key]
            if type(value) is not int or not 0<=value<2**33: raise ValueError('invalid input width')
            operands.append(value-2**33 if value>=2**32 else value)
        if int(row['golden_bits'],16)!=(operands[0]*operands[1])%(2**66):
            raise ValueError('independent integer product differs')
    fields=dict(pair.split('=') for pair in markers[0].split()[1:])
    if int(fields['records'])!=len(rows) or int(fields['stall_checks'])<10000:
        raise ValueError('missing backpressure/stall checks')
    return dict(records=len(rows),seeds=counts,stall_checks=int(fields['stall_checks']))


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--observed-placement',type=Path,required=True)
    args=parser.parse_args()
    vendor=Path('/mnt/d/open-soc-ai-labs-vortex/hw/rtl');original=vendor/'libs/VX_multiplier.sv'
    if sha(original)!=PINNED_SHA256: raise ValueError('original multiplier changed')
    packet=args.observed_placement.resolve()/'completion.json';parent=json.loads(packet.read_text())
    report=Path(parent['reports_directory'])/'3_resizer.rpt'
    if (parent['status']!='HOLD' or parent['clock_period_ns']!=10
            or parent['artifacts'].get(str(report))!=sha(report)):
        raise ValueError('immutable failed 100 MHz observation required')
    timing=report.read_text()
    if 'g_multiplier[0].multiplier.pipe_reg' not in timing or 'slack (VIOLATED)' not in timing:
        raise ValueError('actual integer multiplier setup path not observed')
    config=args.project.resolve()/'vortex-build/hw/VX_config.vh'
    tool=Path('/home/soclab/tools/verilator-5.040/bin/verilator')
    candidate=ROOT/'integration/student-mini/gpu_signed33_mul3.sv'
    bench=ROOT/'tests/rtl/student_mini_gpu_multiplier_cut.sv'
    driver=ROOT/'tests/rtl/student_mini_gpu_multiplier_cut_main.cpp'
    paths=[Path(__file__),ROOT/'scripts/student_mini_gpu_multiplier_cut.py',ROOT/'scripts/student_mini.py',
           ROOT/'scripts/retry_student_mini_route.py',packet,report,config,tool,tool.with_name('verilator_bin'),candidate,bench,driver]
    paths += [p for p in vendor.rglob('*') if p.is_file() and p.suffix in ('.sv','.vh')]
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-multiplier-local-proof'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
                full_gpu_equivalence=False,formal_proof_complete=False,latency_before=3,latency_after=3,
                observed_path_is_intermediate=True,adopted_into_gpu=False,
                scope='Signed 33x33 full 66-bit product, three enabled clocks and stall hold; no whole-core/reset/protocol qualification')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            result['queue_seconds']=time.monotonic()-started
            variants=dict(correct=candidate.read_text(),**mutants(candidate.read_text()));outcomes=[]
            for name,text in variants.items():
                folder=work/name;folder.mkdir()
                projected=folder/'candidate.sv';projected.write_text(project(original.read_text(),text,differential=True))
                bindings[str(projected)]=sha(projected)
                command=[str(tool),'--cc','--exe','--build','-j','2','--Mdir',str(folder/'obj'),'-CFLAGS','-O2',
                    '--assert','--top-module','student_mini_gpu_multiplier_cut','-Wno-fatal',
                    '-I'+str(config.parent),'-I'+str(vendor),'-I'+str(vendor/'libs'),'-y',str(vendor/'libs'),
                    str(original),str(projected),str(bench),str(driver)]
                if execute_locked_route(command,folder/'compile.log',300,lambda _:heartbeat('COMPILE_'+name)):
                    raise ValueError('actual multiplier compile failed: '+name)
                binary=folder/'obj/Vstudent_mini_gpu_multiplier_cut';bindings[str(binary)]=sha(binary)
                code=execute_locked_route([str(binary)],folder/'transactions.jsonl',120,lambda _:heartbeat('EXECUTE_'+name))
                transcript=(folder/'transactions.jsonl').read_text()
                if name=='correct':
                    if code: raise ValueError('actual multiplier differential failed')
                    result.update(validate_transactions(transcript));outcomes.append(dict(name=name,exit_code=code,accepted=True))
                else:
                    killed=code==2 and 'MULTIPLIER_MISMATCH cycle=' in transcript
                    outcomes.append(dict(name=name,exit_code=code,killed=killed))
                    if not killed: raise ValueError('mutation survived or tool failed: '+name)
            verify(bindings);result.update(status='GPU_MULTIPLIER_LOCAL_DIFFERENTIAL_STAGE_PASS',outcomes=outcomes,mutants_killed=4,
                reason='Local unchanged-latency candidate matched original RTL and independent signed integer golden; not adopted, not a formal arithmetic proof or physical PASS')
    except Exception as error: result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='GPU_MULTIPLIER_LOCAL_DIFFERENTIAL_STAGE_PASS' else 1


if __name__=='__main__': raise SystemExit(main())
