"""Resume the observed CPU PDN HOLD with only explicit OpenRAM supply binding."""
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
from scripts.retry_student_mini_route import execute_locked_route,verify

TARGETS=('do-2_4_floorplan_pdn','do-2_floorplan','do-2_floorplan.sdc',
         'do-3_1_place_gp_skip_io','do-3_2_place_iop','do-3_3_place_gp',
         'do-3_4_place_resized','do-3_5_place_dp','do-3_place')


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-placement',type=Path,required=True)
    args=parser.parse_args();old=args.failed_placement.resolve()
    parent=json.loads((old/'completion.json').read_text())
    if (parent['status']!='HOLD' or parent['reason']!='RuntimeError: CPU do-2_4_floorplan_pdn failed'
        or parent['clock_period_ns']!=10 or parent['threads']!=2):raise ValueError('not the observed CPU PDN failure')
    failure=(old/'do-2_4_floorplan_pdn.log').read_text()
    if 'PDN-0231' not in failure or 'PDN-0217' not in failure:raise ValueError('different PDN failure')
    bindings=dict(parent['bindings']);verify(bindings)
    previous=Path(parent['result_directory'])
    checkpoints=[previous/name for name in ('2_3_floorplan_tapcell.odb','2_1_floorplan.sdc','1_synth.sdc')]
    for path in checkpoints:
        if parent['artifacts'].get(str(path))!=sha(path):raise ValueError('PDN checkpoint changed')
    hook=ROOT/'ppa/openram/connect_openram_power.tcl';checker=ROOT/'integration/student-mini/check_cpu_macro_power.tcl'
    paths=[Path(__file__),ROOT/'scripts/retry_student_mini_route.py',hook,checker,old/'completion.json',old/'do-2_4_floorplan_pdn.log',*checkpoints]
    bindings.update({str(p):sha(p) for p in paths})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-pdn-recovery'/identity;work.mkdir(parents=True,exist_ok=False)
    config=work/'config.mk';config.write_text((old/'config.mk').read_text()+f'\nexport PRE_PDN_TCL = {hook}\n')
    bindings[str(config)]=sha(config)
    variant='student-mini-cpu-pdn-'+identity[:16]
    results=previous.parent/variant;logs=Path(parent['metrics_directory']).parent/variant;reports=Path(parent['reports_directory']).parent/variant
    result=dict(status='HOLD',preflight_complete=False,physical_evidence_complete=False,formal_baseline=False,
        bindings=bindings,parent=str(old),clock_period_ns=10,threads=2,config=str(config),
        result_directory=str(results),metrics_directory=str(logs),reports_directory=str(reports),
        rtl_changed=False,geometry_changed=False,macro_power_connected=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-begin))+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings);result['queue_seconds']=time.monotonic()-begin
            for folder in (results,logs,reports):folder.mkdir(parents=True,exist_ok=False)
            for path in checkpoints:
                shutil.copyfile(path,results/path.name)
                if sha(results/path.name)!=bindings[str(path)]:raise ValueError('copied checkpoint differs')
            base=['make','-j1','-C','/home/soclab/src/orfs-clean-aabf2a/flow',f'DESIGN_CONFIG={config}',f'FLOW_VARIANT={variant}',
                  f'COURSE_ROOT={ROOT}','OPENROAD_EXE=/home/soclab/.local/bin/openroad','YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys','NUM_CORES=2']
            for index,target in enumerate(TARGETS):
                if execute_locked_route(base+[target],work/(target+'.log'),600,lambda _:heartbeat(target)):
                    raise RuntimeError('CPU power-connected '+target+' failed')
                if index==0:
                    command=['env',f'STUDENT_MINI_PDN_ODB={results}/2_4_floorplan_pdn.odb','/home/soclab/.local/bin/openroad','-exit',str(checker)]
                    if execute_locked_route(command,work/'macro-power.log',60,lambda _:heartbeat('CHECKING_ALL_60_MACRO_SUPPLY_PINS')):
                        raise ValueError('CPU macro power database check failed')
                    if (work/'macro-power.log').read_text().splitlines().count('CPU_MACRO_POWER_CONNECTED macros=30 pins=60')!=1:
                        raise ValueError('missing exact macro power completion')
                    result['macro_power_connected']=True
            metrics=json.loads((logs/'3_5_place_dp.json').read_text());wns=metrics['detailedplace__timing__setup__ws']
            result['placement_wns_ns']=wns
            if type(wns) not in (float,int) or not math.isfinite(wns) or wns<0:raise ValueError('negative 100 MHz CPU placement; route prohibited')
            verify(bindings);result.update(status='CPU_PDN_PLACEMENT_PREFLIGHT_STAGE_PASS',preflight_complete=True,
                reason='All actual macro supplies connected and 100 MHz placement passed; route, activity/power and complete protocol remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={str(p):sha(p) for folder in (work,results,logs,reports) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
