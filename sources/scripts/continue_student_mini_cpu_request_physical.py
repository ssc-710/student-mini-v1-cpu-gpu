"""Synthesize/place only the fully replayed independent-memory ROM request cut."""
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
from scripts.continue_student_mini_cpu_tag_physical import derive as placement_source


def synthesis_source(source,root):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "paths=[Path(__file__),ROOT/'scripts/student_mini.py'":
        "paths=[Path(__file__),ROOT/'scripts/continue_student_mini_cpu_request_physical.py',ROOT/'scripts/run_student_mini_cpu_synthesis.py',ROOT/'scripts/student_mini.py'",
        "if parent['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' or parent.get('cold_start_replay_complete') is not True:":
        "if parent['status']!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS' or parent.get('cold_start_replay_complete') is not True or parent.get('independent_external_memory') is not True or parent.get('cycle_equivalence') is not False or parent.get('transcript_join',{}).get('baseline_records')!=1000 or len(parent.get('transcript_join',{}).get('raw_counter_comparisons',[]))!=1000:",
        "memories=mapped['remaining_logic_memories']":
        "memories=[dict(width=int(c['parameters']['WIDTH'],2),depth=int(c['parameters']['SIZE'],2)) for c in design['modules'][TOP]['cells'].values() if c['type']=='$mem_v2']",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('new-latency synthesis seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--replay-continuation',type=Path,required=True)
    args=parser.parse_args();replay=args.replay_continuation.resolve()
    synthesis=ROOT/'scripts/run_student_mini_cpu_synthesis.py'
    placement=ROOT/'scripts/run_student_mini_cpu_placement.py'
    power=ROOT/'integration/student-mini/check_cpu_macro_power.tcl'
    paths=[Path(__file__),synthesis,placement,power,replay/'inputs.json',
           ROOT/'scripts/continue_student_mini_cpu_tag_physical.py',ROOT/'scripts/continue_student_mini_cpu_rom_placement.py',
           ROOT/'scripts/student_mini_cpu_tag_floorplan.py']
    bindings={str(p):sha(p) for p in paths};key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-request-physical-continuation'/key;work.mkdir(parents=True,exist_ok=False)
    checker=work/'power.tcl';text=power.read_text()
    for old,new in (('$count != 30 || $pins != 60','$count != 29 || $pins != 58'),('macros=30 pins=60','macros=29 pins=58')):
        if text.count(old)!=1:raise ValueError('macro power-check seam changed')
        text=text.replace(old,new)
    checker.write_text(text)
    synth=work/'synthesis-producer.py';synth.write_text(synthesis_source(synthesis.read_text(),ROOT))
    place=work/'placement-producer.py';place.write_text(placement_source(placement.read_text(),ROOT,checker))
    bindings.update({str(p):sha(p) for p in (checker,synth,place)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,read_latency_cycles=2)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def execute(producer,phase,args):
        verify(bindings);heartbeat(phase.upper())
        with (work/(phase+'.log')).open('x') as log:
            code=subprocess.call([sys.executable,str(producer),*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows=[json.loads(x) for x in (work/(phase+'.log')).read_text().splitlines() if x.startswith('{')]
        if rows:result[phase]=rows[-1]
        if code or not rows:raise ValueError(phase+' failed; child HOLD retained')
        packet=Path(rows[-1]['work'])/'completion.json';child=json.loads(packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(packet)]=sha(packet)
        return rows[-1]
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_CHANGED_LATENCY_FULL_REPLAY')),flush=True)
    try:
        packet=replay/'completion.json'
        while not packet.is_file():
            heartbeat('WAITING_FOR_CHANGED_LATENCY_FULL_REPLAY')
            if time.monotonic()-begin>43200:raise TimeoutError('bounded full replay wait expired')
            time.sleep(10)
        parent=json.loads(packet.read_text())
        if parent['status']!='CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS':raise ValueError('changed-latency full CPU replay required')
        verify(parent['bindings']);bindings.update(parent['bindings']);bindings[str(packet)]=sha(packet)
        synthesized=execute(synth,'synthesis',['--replay',parent['replay']['work']])
        if synthesized['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS':raise ValueError('synthesis not qualified')
        placed=execute(place,'placement',['--synthesis',synthesized['work']])
        if placed['status']!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':raise ValueError('placement not qualified')
        result.update(status='CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS',
            reason='Independently replayed two-edge ROM CPU passed synthesis and 100 MHz placement; route, power and protocol remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
