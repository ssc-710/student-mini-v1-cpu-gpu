"""After full tag-candidate CPU replay, synthesize and preflight its exact layout."""
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
from scripts.continue_student_mini_cpu_rom_placement import derive as previous_placement


def derive(source,root,checker):
    text=previous_placement(source,root)
    changes={
        'from scripts.student_mini_cpu_floorplan import geometry, placement_tcl, configuration':
        'from scripts.student_mini_cpu_tag_floorplan import geometry, placement_tcl, configuration',
        "ROOT/'integration/student-mini/check_cpu_macro_power.tcl'":"Path("+repr(str(checker))+")",
        'CPU_MACRO_POWER_CONNECTED macros=30 pins=60':'CPU_MACRO_POWER_CONNECTED macros=29 pins=58',
        'CHECKING_ALL_60_MACRO_SUPPLY_PINS':'CHECKING_ALL_58_MACRO_SUPPLY_PINS',
        'Same netlist/ROM, 30 real macros':'Same netlist/ROM, 29 real SRAM macros plus 512x22 real tag registers',
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/student_mini_cpu_tag_floorplan.py',ROOT/'scripts/continue_student_mini_cpu_tag_physical.py',",
    }
    for old,new in changes.items():
        expected=2 if old=="ROOT/'integration/student-mini/check_cpu_macro_power.tcl'" else 1
        if text.count(old)!=expected:raise ValueError('CPU tag placement seam changed: '+old)
        text=text.replace(old,new)
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--replay-continuation',type=Path,required=True)
    args=parser.parse_args();replay=args.replay_continuation.resolve()
    original=ROOT/'scripts/run_student_mini_cpu_placement.py'
    power=ROOT/'integration/student-mini/check_cpu_macro_power.tcl'
    files=[Path(__file__),original,power,replay/'inputs.json',ROOT/'scripts/student_mini_cpu_tag_floorplan.py',
           ROOT/'scripts/continue_student_mini_cpu_rom_placement.py',ROOT/'scripts/run_student_mini_cpu_synthesis.py']
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-tag-physical-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    checker=work/'check-tag-cpu-power.tcl'
    text=power.read_text()
    for old,new in (('$count != 30 || $pins != 60','$count != 29 || $pins != 58'),('macros=30 pins=60','macros=29 pins=58')):
        if text.count(old)!=1:raise ValueError('power verification seam changed')
        text=text.replace(old,new)
    checker.write_text(text)
    producer=work/'placement-producer.py';producer.write_text(derive(original.read_text(),ROOT,checker))
    bindings.update({str(p):sha(p) for p in (checker,producer)})
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def execute(command,phase):
        heartbeat(phase.upper());log=work/(phase+'.log')
        with log.open('x') as output:code=subprocess.call(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        rows=[json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
        if rows:result[phase]=rows[-1]
        if code:raise ValueError('CPU tag '+phase+' failed; child HOLD retained')
        verify(bindings)
        return rows[-1]
    try:
        heartbeat('WAITING_FOR_FULL_TAG_CPU_REPLAY');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_FULL_TAG_CPU_REPLAY')),flush=True)
        while not (replay/'completion.json').exists():
            if time.monotonic()-begin>43200:raise TimeoutError('bounded full replay wait expired')
            time.sleep(10)
        receipt=replay/'completion.json';prior=json.loads(receipt.read_text())
        if prior['status']!='CPU_TAG_REGISTER_FULL_REPLAY_STAGE_PASS':raise ValueError('full cache-tag replay did not pass')
        child=Path(prior['replay']['work']);bindings.update(prior['bindings']);bindings[str(receipt)]=sha(receipt);verify(bindings)
        synthesis=execute([sys.executable,str(ROOT/'scripts/run_student_mini_cpu_synthesis.py'),'--replay',str(child)],'synthesis')
        if synthesis['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS':raise ValueError('CPU tag synthesis not qualified')
        placed=execute([sys.executable,str(producer),'--synthesis',synthesis['work']],'placement')
        if placed['status']!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':raise ValueError('CPU tag placement not qualified')
        result.update(status='CPU_TAG_PHYSICAL_PREFLIGHT_STAGE_PASS',reason='Replayed 29-SRAM/real-tag-register CPU passes synthesis and 100 MHz placement; route/activity/power remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_TAG_PHYSICAL_PREFLIGHT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
