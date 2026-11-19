"""Start ROM-cut placement only after full replay/synthesis, with proven PG hook."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.continue_student_mini_cpu_pdn_placement import derive as pg_derive


def derive(source,root):
    source=pg_derive(source,root)
    anchor="                    raise RuntimeError('CPU '+target+' failed')"
    check='''
                if target=='do-2_4_floorplan_pdn':
                    checker=ROOT/'integration/student-mini/check_cpu_macro_power.tcl'
                    command=['env',f'STUDENT_MINI_PDN_ODB={results}/2_4_floorplan_pdn.odb','/home/soclab/.local/bin/openroad','-exit',str(checker)]
                    if execute_locked_route(command,work/'macro-power.log',60,lambda _:heartbeat('CHECKING_ALL_60_MACRO_SUPPLY_PINS')):
                        raise ValueError('CPU macro power database check failed')
                    if (work/'macro-power.log').read_text().splitlines().count('CPU_MACRO_POWER_CONNECTED macros=30 pins=60')!=1:
                        raise ValueError('missing macro supply check')
                    result['macro_power_connected']=True
'''
    if source.count(anchor)!=1:raise ValueError('placement command seam changed')
    source=source.replace(anchor,anchor+check)
    anchor='paths = [Path(__file__),'
    if source.count(anchor)!=1:raise ValueError('placement binding seam changed')
    return source.replace(anchor,"paths = [Path(__file__), ROOT/'scripts/continue_student_mini_cpu_rom_placement.py', ROOT/'scripts/continue_student_mini_cpu_pdn_placement.py', ROOT/'integration/student-mini/check_cpu_macro_power.tcl',")


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--synthesis',type=Path,required=True)
    args=parser.parse_args();parent=args.synthesis.resolve();original=ROOT/'scripts/run_student_mini_cpu_placement.py'
    files=[Path(__file__),original,ROOT/'scripts/continue_student_mini_cpu_pdn_placement.py',ROOT/'scripts/student_mini_cpu_floorplan.py',ROOT/'integration/student-mini/check_cpu_macro_power.tcl',ROOT/'ppa/openram/connect_openram_power.tcl']
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(dict(parent=str(parent),bindings=bindings),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-placement-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,physical_evidence_complete=False,formal_baseline=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        heartbeat('WAITING_FOR_ROM_CUT_SYNTHESIS');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_ROM_CUT_SYNTHESIS')),flush=True)
        while not (parent/'completion.json').exists():
            if time.monotonic()-begin>43200:raise TimeoutError('bounded synthesis wait expired')
            time.sleep(10)
        receipt=parent/'completion.json';value=json.loads(receipt.read_text())
        if value['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS':raise ValueError('CPU ROM-cut synthesis did not pass')
        bindings.update(value['bindings']);bindings[str(receipt)]=sha(receipt);verify(bindings)
        heartbeat('PLACEMENT_QUEUED')
        with (work/'placement.log').open('x') as log:code=subprocess.call([sys.executable,str(producer),'--synthesis',str(parent)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows=[json.loads(line) for line in (work/'placement.log').read_text().splitlines() if line.startswith('{')]
        if rows:result['placement']=rows[-1]
        verify(bindings)
        if code or result.get('placement',{}).get('status')!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':raise ValueError('CPU ROM-cut placement did not pass; child evidence retained')
        result.update(status='CPU_ROM_CUT_PLACEMENT_STAGE_PASS',reason='Same-ROM replay, synthesis and placement passed; complete route/activity/power gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_CUT_PLACEMENT_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
