"""Initial macro placement and bounded 100 MHz preflight; never routes a failure."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_cpu_floorplan import geometry, placement_tcl, configuration
from scripts.retry_student_mini_route import verify, execute_locked_route

TARGETS = ('do-2_1_floorplan', 'do-2_2_floorplan_macro', 'do-2_3_floorplan_tapcell',
           'do-2_4_floorplan_pdn', 'do-2_floorplan', 'do-2_floorplan.sdc',
           'do-3_1_place_gp_skip_io', 'do-3_2_place_iop', 'do-3_3_place_gp',
           'do-3_4_place_resized', 'do-3_5_place_dp', 'do-3_place')


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    args = parser.parse_args(); parent_dir = args.synthesis.resolve()
    receipt = parent_dir/'completion.json'; parent = json.loads(receipt.read_text())
    if parent['status'] != 'CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS' or parent['clock_period_ns'] != 10:
        raise ValueError('qualified same-ROM CPU synthesis required')
    bindings = dict(parent['bindings']); verify(bindings)
    old_results = Path(parent['result_directory'])
    checkpoints = [old_results/name for name in ('1_synth.odb', '1_synth.sdc')]
    for p in checkpoints:
        if parent['artifacts'].get(str(p)) != sha(p): raise ValueError('synthesis checkpoint changed')
    paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_floorplan.py',
             ROOT/'scripts/retry_student_mini_route.py', receipt, *checkpoints]
    bindings.update({str(p): sha(p) for p in paths})
    g = geometry((parent_dir/'vortex_sp_32x1024_w4.lef').read_text(), parent['cell_and_macro_area_um2'])
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings,geometry=g),sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-placement'/identity; work.mkdir(parents=True,exist_ok=False)
    placement = work/'macro-placement.tcl'; placement.write_text(placement_tcl(g))
    config = work/'config.mk'; config.write_text(configuration((parent_dir/'config.mk').read_text(),g,placement))
    bindings.update({str(p):sha(p) for p in (config,placement)})
    variant = 'student-mini-cpu-place-'+identity[:16]
    results = old_results.parent/variant
    logs = Path(parent['metrics_directory']).parent/variant
    reports = Path(parent['reports_directory']).parent/variant
    orfs = Path('/home/soclab/src/orfs-clean-aabf2a')
    result = dict(status='HOLD',preflight_complete=False,physical_evidence_complete=False,
                  formal_baseline=False,bindings=bindings,clock_period_ns=10,threads=2,
                  geometry=g,config=str(config),parent_synthesis=str(parent_dir),
                  result_directory=str(results),metrics_directory=str(logs),reports_directory=str(reports))
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-begin))+'\n')
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock,fcntl.LOCK_EX); verify(bindings)
            result['queue_seconds'] = time.monotonic()-begin
            for folder in (results,logs,reports): folder.mkdir(parents=True,exist_ok=False)
            for path in checkpoints:
                target=results/path.name; shutil.copyfile(path,target)
                if sha(target)!=bindings[str(path)]: raise ValueError('checkpoint copy differs')
            base=['make','-j1','-C',str(orfs/'flow'),f'DESIGN_CONFIG={config}',f'FLOW_VARIANT={variant}',
                  f'COURSE_ROOT={ROOT}','OPENROAD_EXE=/home/soclab/.local/bin/openroad',
                  'YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys','NUM_CORES=2']
            for target in TARGETS:
                if execute_locked_route(base+[target],work/(target+'.log'),600,lambda _:heartbeat(target)):
                    raise RuntimeError('CPU '+target+' failed')
            metrics=json.loads((logs/'3_5_place_dp.json').read_text())
            wns=metrics['detailedplace__timing__setup__ws']; result['placement_wns_ns']=wns
            if type(wns) not in (float,int) or not math.isfinite(wns) or wns<0:
                raise ValueError('100 MHz CPU placement timing fails; route prohibited')
            verify(bindings)
            result.update(status='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS',preflight_complete=True,
                          reason='Same netlist/ROM, 30 real macros, initial placement passes 100 MHz; route, pin access, protocol and activity/power remain')
    except Exception as error: result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={str(p):sha(p) for folder in (work,results,logs,reports) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__=='__main__': raise SystemExit(main())
