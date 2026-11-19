"""One-buffer physical experiment for the measured CPU SRAM read half-cycle.

No clock exception, macro/ROM change, latency change, or RTL modification.
Existing real RTL execution remains a separate bound qualification; route and
actual gate-level activity/power are still mandatory after a placement PASS.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route
from scripts.audit_student_mini_cpu_timing import worst_setup


def buffer_function(liberty):
    blocks=re.findall(r'(?ms)^    cell \("sky130_fd_sc_hd__buf_4"\) \{.*?(?=^    cell |\Z)',liberty)
    if len(blocks)!=1 or re.findall(r'\bfunction\s*:\s*"([^"]+)"',blocks[0]) not in (['A'],['(A)']):
        raise ValueError('locked buffer is not a single identity function')
    for pin,direction in [('A','input'),('X','output')]:
        pins=re.findall(r'(?ms)^        pin \("'+pin+r'"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)',blocks[0])
        if len(pins)!=1 or not re.search(r'\bdirection\s*:\s*"?'+direction+r'"?\s*;',pins[0]):
            raise ValueError('buffer pin direction differs')


def checked_path(parent,report):
    if (parent.get('status')!='HOLD' or parent.get('clock_period_ns')!=10
        or parent.get('threads')!=2 or parent.get('macro_power_connected') is not True):
        raise ValueError('actual powered 100 MHz placement HOLD required')
    path=worst_setup(report,parent.get('placement_wns_ns'))
    if (path['startpoint']!='data_mem_grain10.0.0.storage'
        or path['endpoint']!='VexRiscv.dBusWishbone_DAT_MISO_regNext[21]$_SDFF_PP1_'
        or '_095039_/Y (sky130_fd_sc_hd__a222oi_1)' not in report
        or '_095042_/A2 (sky130_fd_sc_hd__o21ai_0)' not in report):
        raise ValueError('observed SRAM half-cycle critical path differs')
    return path


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();packet=args.placement.resolve()/'completion.json';parent=json.loads(packet.read_text())
    report=Path(parent['reports_directory'])/'3_detailed_place.rpt'
    if parent['artifacts'].get(str(report))!=sha(report): raise ValueError('final CPU timing report changed')
    path=checked_path(parent,report.read_text());bindings=dict(parent['bindings']);verify(bindings)
    flow=Path('/home/soclab/src/orfs-clean-aabf2a/flow')
    liberty=flow/'platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib'
    buffer_function(liberty.read_text())
    hook=ROOT/'integration/student-mini/cpu_read_return_buffer.tcl'
    files=[Path(__file__),ROOT/'scripts/audit_student_mini_cpu_timing.py',ROOT/'scripts/retry_student_mini_route.py',
           packet,report,liberty,hook]
    old=Path(parent['result_directory']);old_config=Path(parent['config'])
    if old.parent!=flow/'results/sky130hd/cpu_student_mini_physical_top_asic': raise ValueError('unexpected CPU checkpoint root')
    names=['1_synth.odb','1_synth.sdc','2_floorplan.odb','2_floorplan.sdc','3_2_place_iop.odb','3_3_place_gp.odb','3_5_place_dp.odb']
    for p in [old_config,*[old/name for name in names]]:
        if parent['artifacts'].get(str(p))!=sha(p): raise ValueError('bound CPU checkpoint changed')
        files.append(p)
    bindings.update({str(p):sha(p) for p in files})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-read-buffer-placement'/key;work.mkdir(parents=True,exist_ok=False)
    variant='student-mini-cpu-read-buffer-'+key[:16];top='cpu_student_mini_physical_top_asic'
    results=flow/'results/sky130hd'/top/variant;logs=flow/'logs/sky130hd'/top/variant;reports=flow/'reports/sky130hd'/top/variant
    config=work/'config.mk';shutil.copyfile(old_config,config);bindings[str(config)]=sha(config)
    result=dict(status='HOLD',preflight_complete=False,physical_evidence_complete=False,formal_baseline=False,
        bindings=bindings,clock_period_ns=10,threads=2,macro_power_connected=False,geometry=parent['geometry'],
        config=str(config),parent_synthesis=parent['parent_synthesis'],result_directory=str(results),
        metrics_directory=str(logs),reports_directory=str(reports),prior_hold=str(packet),observed_path=path,
        single_variable='one identity buffer on measured SRAM read-return net; unchanged RTL, 5 ns half-cycle budget and all constraints')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            result['queue_seconds']=time.monotonic()-begin
            for folder in (results,logs,reports): folder.mkdir(parents=True,exist_ok=False)
            result['checkpoint_copies']={}
            for name in names:
                destination=results/('3_4_place_resized.odb' if name=='3_5_place_dp.odb' else name)
                shutil.copyfile(old/name,destination)
                if sha(destination)!=sha(old/name): raise ValueError('checkpoint copy differs')
                result['checkpoint_copies'][destination.name]=dict(source=str(old/name),sha256=sha(destination))
            base=['make','-j1','-C',str(flow),f'DESIGN_CONFIG={config}',f'FLOW_VARIANT={variant}',
                f'COURSE_ROOT={ROOT}','OPENROAD_EXE=/home/soclab/.local/bin/openroad',
                'YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys','NUM_CORES=2',f'PRE_DETAIL_PLACE_TCL={hook}']
            for target in ('do-3_5_place_dp','do-3_place'):
                if execute_locked_route(base+[target],work/(target+'.log'),600,lambda _:heartbeat(target)):
                    raise ValueError('CPU buffer placement failed: '+target)
            marker='CPU_SINGLE_BUFFER_INSERTED driver=_095039_/Y sink=_095042_/A2 cell=sky130_fd_sc_hd__buf_4'
            if (work/'do-3_5_place_dp.log').read_text().splitlines().count(marker)!=1:
                raise ValueError('exact one-buffer topology witness missing')
            result['one_buffer_topology_checked']=True
            # The frozen 29-macro checker is part of the actual parent producer.
            candidates=[Path(p) for p in bindings if Path(p).name=='power.tcl' and 'cpu-request-physical-continuation' in p]
            if len(candidates)!=1: raise ValueError('unique actual CPU macro-power checker required')
            command=['env',f'STUDENT_MINI_PDN_ODB={results}/3_5_place_dp.odb','/home/soclab/.local/bin/openroad','-exit',str(candidates[0])]
            if execute_locked_route(command,work/'macro-power.log',60,lambda _:heartbeat('CHECKING_UNCHANGED_MACROS')):
                raise ValueError('CPU macro power check failed')
            if (work/'macro-power.log').read_text().splitlines().count('CPU_MACRO_POWER_CONNECTED macros=29 pins=58')!=1:
                raise ValueError('actual 29 macro supply marker missing')
            result['macro_power_connected']=True
            wns=json.loads((logs/'3_5_place_dp.json').read_text())['detailedplace__timing__setup__ws'];result['placement_wns_ns']=wns
            if type(wns) not in (float,int) or not math.isfinite(wns) or wns<0: raise ValueError('100 MHz CPU timing still fails; route prohibited')
            verify(bindings);result.update(status='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS',preflight_complete=True,
                reason='One checked identity buffer; detailed placement now passes 100 MHz. Fresh route, macro access and gate-level activity/power remain')
    except Exception as error: result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={str(p):sha(p) for folder in (work,results,logs,reports) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__=='__main__': raise SystemExit(main())
