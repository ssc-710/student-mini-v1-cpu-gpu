"""Measure a single non-inverting CTS-buffer bypass; never adopt a checkpoint."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route


def check_buffer(liberty):
    blocks=re.findall(r'(?ms)^    cell \("sky130_fd_sc_hd__clkbuf_16"\) \{.*?(?=^    cell |\Z)',liberty)
    if len(blocks)!=1:raise ValueError('unique non-inverting buffer Liberty cell required')
    pins=re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)',blocks[0])
    values={name:body for name,body in pins}
    functions=re.findall(r'(?m)^\s+function\s*:\s*"([^"]+)"',values.get('X',''))
    if (len(pins)!=2 or set(values)!={'A','X'} or len(functions)!=1
            or functions[0].strip() not in ('A','(A)')
            or re.findall(r'(?m)^\s+direction\s*:\s*"([^"]+)"',values['A'])!=['input']
            or re.findall(r'(?m)^\s+direction\s*:\s*"([^"]+)"',values['X'])!=['output']):
        raise ValueError('bypassed cell is not an exact non-inverting buffer')


def parse(log,expected):
    pattern=r'(?m)^CPU_CTS_BUFFER_PROBE stage=(original|single_buffer_bypassed)\nworst slack max (-?\d+\.\d+)\nworst slack min (-?\d+\.\d+)\s*$'
    rows=re.findall(pattern,log)
    if [r[0] for r in rows]!=['original','single_buffer_bypassed'] or '[ERROR' in log or 'Error:' in log:
        raise ValueError('complete original/changed setup and hold reports required')
    if log.splitlines().count('CPU_CTS_BUFFER_PROBE_COMPLETE macros=29 removed=1 diagnostic_only=1 no_checkpoint_written=1')!=1:
        raise ValueError('precise buffer bypass witness missing')
    result={stage:dict(setup_ns=float(setup),hold_ns=float(hold)) for stage,setup,hold in rows}
    if any(not math.isfinite(v) for r in result.values() for v in r.values()) or abs(result['original']['setup_ns']-expected)>.00001:
        raise ValueError('original CTS timing not reproduced')
    return result


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prior-route',type=Path,required=True)
    args=parser.parse_args();packet=args.prior_route.resolve()/'completion.json';parent=json.loads(packet.read_text())
    if parent['status']!='HOLD' or parent['platform']!='cpu' or parent['clock_period_ns']!=10 or abs(parent['cts_wns_ns']+.130249)>1e-6:
        raise ValueError('observed original 100 MHz CTS HOLD required')
    result_dir=Path(parent['result_directory']);odb=result_dir/'4_1_cts.odb';sdc=result_dir/'4_cts.sdc'
    report=Path(parent['reports_directory'])/'4_cts_final.rpt';config=Path(parent['config'])
    for path in (odb,sdc,report):
        if parent['artifacts'].get(str(path))!=sha(path):raise ValueError('original checkpoint changed')
    if 'delaybuf_3_core_clock/X' not in report.read_text() or 'Endpoint: serial_source_data[7]' not in report.read_text():
        raise ValueError('observed clock/output path differs')
    platform=Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd')
    liberty=platform/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib';rc=platform/'setRC.tcl'
    macro=Path(re.findall(r'^export ADDITIONAL_LIBS = (.+)$',config.read_text(),re.M)[0]);check_buffer(liberty.read_text())
    hook=ROOT/'integration/student-mini/cpu_cts_single_buffer_probe.tcl';tool=Path('/home/soclab/.local/bin/openroad')
    bindings=dict(parent['bindings']);bindings.update({str(p):sha(p) for p in (Path(__file__),packet,odb,sdc,report,config,liberty,macro,rc,hook,tool)})
    verify(bindings);key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-cts-buffer-probe'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,diagnostic_only=True)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');start=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            command=['env',f'MINI_SC_LIB={liberty}',f'MINI_MACRO_LIB={macro}',f'MINI_ODB={odb}',f'MINI_SDC={sdc}',f'MINI_RC={rc}',str(tool),'-exit',str(hook)]
            if execute_locked_route(command,work/'probe.log',240,lambda _:heartbeat('SINGLE_CLOCK_BUFFER_DIAGNOSTIC')):
                raise ValueError('actual clock-buffer diagnostic failed')
            measured=parse((work/'probe.log').read_text(),parent['cts_wns_ns'])
            verify(bindings);result.update(status='CPU_CTS_BUFFER_DIAGNOSTIC_COMPLETE',measurements=measured,
                next_adoption_eligible=all(v>=0 for v in measured['single_buffer_bypassed'].values()),
                reason='In-memory single buffer bypass; no placement, routing or power adopted')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'],measurements=result.get('measurements'))),flush=True)
    return 0 if result['status']=='CPU_CTS_BUFFER_DIAGNOSTIC_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
