"""Measure one CPU multiplier gate's drive options, without adopting a physical result."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route
from scripts.audit_student_mini_cpu_timing import worst_setup


def equivalent_drive_cells(liberty):
    functions=[]
    for strength in (0,1,2,4):
        cell='sky130_fd_sc_hd__a21boi_'+str(strength)
        blocks=re.findall(r'(?ms)^    cell \("'+cell+r'"\) \{.*?(?=^    cell |\Z)',liberty)
        if len(blocks)!=1:raise ValueError('unique drive cell required')
        pins=re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)',blocks[0])
        signature=[]
        for name,body in pins:
            direction=re.findall(r'\bdirection\s*:\s*"?(input|output)"?\s*;',body)
            function=re.findall(r'\bfunction\s*:\s*"([^"]+)"',body)
            if len(direction)!=1:raise ValueError('pin direction missing')
            signature.append((name,direction[0],function))
        if sorted(p[0] for p in signature)!=['A1','A2','B1_N','Y']:raise ValueError('drive cell pins differ')
        functions.append(sorted(signature))
    if any(x!=functions[0] for x in functions[1:]):raise ValueError('drive cells are not functionally identical')
    return functions[0]


def parse_probe(log,expected):
    rows=re.findall(r'CPU_MULT_DRIVE_PROBE strength=(\d)\s+worst slack\s+(-?\d+(?:\.\d+)?)',log)
    if [int(x[0]) for x in rows]!=[0,1,2,4]:raise ValueError('incomplete drive probes')
    values={strength:float(slack) for strength,slack in rows}
    if abs(values['0']-expected)>.001:raise ValueError('baseline timing did not reproduce')
    if 'CPU_MULT_DRIVE_PROBE_COMPLETE diagnostic_only=1 no_checkpoint_written=1' not in log:raise ValueError('topology probe incomplete')
    return values


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();packet=args.placement.resolve()/'completion.json';parent=json.loads(packet.read_text())
    if parent['status']!='HOLD' or parent['clock_period_ns']!=10 or parent['macro_power_connected'] is not True:
        raise ValueError('actual powered placement HOLD required')
    report=Path(parent['reports_directory'])/'3_detailed_place.rpt'
    odb=Path(parent['result_directory'])/'3_5_place_dp.odb';sdc=Path(parent['result_directory'])/'3_place.sdc'
    for p in (report,odb,sdc):
        if parent['artifacts'].get(str(p))!=sha(p):raise ValueError('parent checkpoint/report changed')
    path=worst_setup(report.read_text(),parent['placement_wns_ns'])
    if 'execute_to_memory_MUL_HH[26]' not in path['endpoint'] or '_074408_/Y (sky130_fd_sc_hd__a21boi_0)' not in report.read_text():
        raise ValueError('observed multiplier path differs')
    platform=Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd')
    liberty=platform/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib';rc=platform/'setRC.tcl'
    config=Path(parent['config']).read_text()
    macro=Path(re.findall(r'^export ADDITIONAL_LIBS = (.+)$',config,re.M)[0])
    hook=ROOT/'integration/student-mini/cpu_multiplier_drive_probe.tcl';tool=Path('/home/soclab/.local/bin/openroad')
    signature=equivalent_drive_cells(liberty.read_text())
    bindings=dict(parent['bindings']);verify(bindings)
    bindings.update({str(p):sha(p) for p in (Path(__file__),packet,report,odb,sdc,liberty,macro,rc,hook,tool,ROOT/'scripts/audit_student_mini_cpu_timing.py')})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-multiplier-drive-probe'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,observed_path=path,functions=signature,
                formal_baseline=False,physical_evidence_complete=False,diagnostic_only=True)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            command=['env',f'MINI_SC_LIB={liberty}',f'MINI_MACRO_LIB={macro}',f'MINI_ODB={odb}',f'MINI_SDC={sdc}',f'MINI_RC={rc}',str(tool),'-exit',str(hook)]
            if execute_locked_route(command,work/'probe.log',180,lambda _:None):raise ValueError('OpenROAD drive probe failed')
            result['worst_slack_ns_by_strength']=parse_probe((work/'probe.log').read_text(),parent['placement_wns_ns'])
            verify(bindings);result.update(status='CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE',reason='In-memory drive-only measurements; legalization, full route and power NOT qualified')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'],measurements=result.get('worst_slack_ns_by_strength'))),flush=True)
    return 0 if result['status']=='CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
