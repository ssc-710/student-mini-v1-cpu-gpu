"""Retry only a timed-out layout/report stage with a larger observation budget.

No RTL, constraints, macro layout, density or numerical acceptance change.
Original 600-second HOLD remains immutable. This is not a one-hour delivery.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route


def checked_parent(parent):
    if (parent.get('status')!='HOLD' or parent.get('clock_period_ns')!=10 or parent.get('threads')!=2
        or parent.get('macro_count')!=37 or parent.get('macro_power_connected') is not True
        or "'do-3_3_place_gp']' timed out after 600 seconds" not in parent.get('reason','')):
        raise ValueError('exact powered 100 MHz/37-macro global-placement timeout required')
    if parent.get('preflight_complete') is not False:raise ValueError('cannot retry accepted placement')


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();packet=args.placement.resolve()/'completion.json';parent=json.loads(packet.read_text())
    checked_parent(parent);bindings=dict(parent['bindings']);verify(bindings)
    checker=ROOT/'integration/student-mini/check_gpu_macro_power.tcl'
    paths=[Path(__file__),packet,checker,ROOT/'scripts/retry_student_mini_route.py']
    old_results=Path(parent['result_directory']);old_config=Path(parent['config'])
    orfs=Path('/home/soclab/src/orfs-clean-aabf2a');top='vortex_physical_top'
    if old_results.parent!=orfs/'flow/results/sky130hd'/top:raise ValueError('unexpected source checkpoint workspace')
    checkpoints=[old_results/name for name in ('1_synth.odb','1_synth.sdc','2_floorplan.odb','2_floorplan.sdc','3_2_place_iop.odb')]
    for path in [old_config,*checkpoints]:
        if parent['artifacts'].get(str(path))!=sha(path):raise ValueError('completed pre-global checkpoint changed')
    bindings.update({str(p):sha(p) for p in [*paths,old_config,*checkpoints]})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-repaired-placement'/key;work.mkdir(parents=True,exist_ok=False)
    variant='student-mini-gpu-report-retry-'+key[:16]
    results=old_results.parent/variant;logs=orfs/'flow/logs/sky130hd'/top/variant;reports=orfs/'flow/reports/sky130hd'/top/variant
    config=work/'config.mk';shutil.copyfile(old_config,config);bindings[str(config)]=sha(config)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        preflight_complete=False,clock_period_ns=10,threads=2,macro_count=37,macro_power_connected=False,
        result_directory=str(results),metrics_directory=str(logs),reports_directory=str(reports),config=str(config),
        parent_synthesis=parent['parent_synthesis'],prior_hold=str(packet),
        single_variable='global-placement/report timeout 600 to 1200 seconds; exact checkpoint/config unchanged',
        stage_budgets_seconds={'do-3_3_place_gp':1200,'other':600},one_hour_full_delivery_achieved=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-begin))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            result['queue_and_parent_wait_seconds']=time.monotonic()-begin
            for folder in (results,logs,reports):folder.mkdir(parents=True,exist_ok=False)
            for path in checkpoints:
                shutil.copyfile(path,results/path.name)
                if sha(results/path.name)!=sha(path):raise ValueError('checkpoint copy differs')
            command=['env',f'STUDENT_MINI_PDN_ODB={results}/3_2_place_iop.odb','/home/soclab/.local/bin/openroad','-exit',str(checker)]
            if execute_locked_route(command,work/'macro-power.log',60,lambda _:heartbeat('CHECKING_RESTORED_SUPPLY_PINS')):
                raise ValueError('restored macro supply check failed')
            if (work/'macro-power.log').read_text().splitlines().count('GPU_MACRO_POWER_CONNECTED macros=37 pins=74')!=1:
                raise ValueError('restored actual macro supply marker missing')
            result['macro_power_connected']=True
            base=['make','-j1','-C',str(orfs/'flow'),f'DESIGN_CONFIG={config}',f'FLOW_VARIANT={variant}',
                  f'COURSE_ROOT={ROOT}','OPENROAD_EXE=/home/soclab/.local/bin/openroad',
                  'YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys','NUM_CORES=2']
            for target in ('do-3_3_place_gp','do-3_4_place_resized','do-3_5_place_dp','do-3_place'):
                budget=1200 if target=='do-3_3_place_gp' else 600
                if execute_locked_route(base+[target],work/(target+'.log'),budget,lambda _:heartbeat(target)):
                    raise ValueError('resumed GPU placement failed: '+target)
            value=json.loads((logs/'3_5_place_dp.json').read_text())['detailedplace__timing__setup__ws']
            result['placement_wns_ns']=value
            if type(value) not in (float,int) or not math.isfinite(value) or value<0:
                raise ValueError('final detailed placement fails 100 MHz; route prohibited')
            verify(bindings)
            result.update(status='REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS',preflight_complete=True,
                reason='Same hardware/checkpoint completed detailed placement at 100 MHz; route/activity/power remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={str(p):sha(p) for folder in (work,results,logs,reports) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
