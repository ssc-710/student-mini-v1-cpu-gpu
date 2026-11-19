"""Recheck immutable actual execution after separating Nano counters from values."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.student_mini_cpu_latency_counters import compare_transcripts
from scripts.student_mini_cpu_latency_replay import wrapper,memory_source,TOP


def eligible(parent):
    if parent.get('status')=='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS':return
    if (parent.get('status')!='HOLD' or parent.get('reason')!=
        'ValueError: new-latency CPU sequence, metadata or complete native state differs'):
        raise ValueError('only completed execution with the known measurement-comparison issue may be rechecked')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--replay',type=Path,required=True)
    args=parser.parse_args();source=args.replay.resolve()
    paths=[Path(__file__),ROOT/'scripts/student_mini_cpu_latency_counters.py',
           ROOT/'scripts/student_mini_cpu_latency_replay.py',ROOT/'scripts/student_mini_cpu_independent_memory.py',
           source/'bridge.sv',source/'reference.v']
    bindings={str(p):sha(p) for p in paths};key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-latency-native-counter-recheck'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
                fresh_rtl_execution_performed=False,source_replay=str(source))
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_COMPLETE_IMMUTABLE_EXECUTION')),flush=True)
    try:
        receipt=source/'completion.json'
        while not receipt.is_file():
            heartbeat('WAITING_FOR_COMPLETE_IMMUTABLE_EXECUTION')
            if time.monotonic()-begin>43200:raise TimeoutError('bounded execution wait expired')
            time.sleep(10)
        parent=json.loads(receipt.read_text());eligible(parent)
        verify(parent['bindings']);bindings.update(parent['bindings']);bindings[str(receipt)]=sha(receipt)
        for name,digest in parent['artifacts'].items():
            path=source/name
            if sha(path)!=digest:raise ValueError('actual execution artifact changed')
            bindings[str(path)]=digest
        mapping=Path(parent['parent_mapping']);cpu=Path(parent['parent_cpu'])
        mapped=json.loads((mapping/'completion.json').read_text())
        if mapped['status']!='CPU_ROM_REQUEST_MAPPING_STAGE_PASS':raise ValueError('wrong actual mapping lineage')
        design=json.loads((mapping/'mapped.json').read_text())
        if (source/'bridge.sv').read_text()!=wrapper(design['modules'][TOP]['ports']):
            raise ValueError('actual memory interface differs from qualified wrapper')
        if (source/'reference.v').read_text()!=memory_source((cpu/'soc/gateware/sim.v').read_text()):
            raise ValueError('actual SDRAM model differs from qualified independent environment')
        text=(source/'console.log').read_text();reference=(cpu/'console.log').read_text()
        if sum(x.startswith('CPU_BOUNDARY_REPLAY_COMPLETE cycles=') for x in text.splitlines())!=1:
            raise ValueError('RTL driver did not complete all baseline and Nano execution')
        joined=compare_transcripts(reference,text);verify(bindings)
        output=work/'revalidated';output.mkdir()
        records=output/'uart-records.log'
        records.write_text('\n'.join(x for x in text.splitlines() if x.startswith(('STUDENT_CPU ','STUDENT_CPU_','STUDENT_NATIVE_','CPU_BOUNDARY_REPLAY_COMPLETE ')))+'\n')
        measurements=output/'measurements.json';measurements.write_text(json.dumps(joined,indent=2)+'\n')
        bindings.update({str(p):sha(p) for p in (records,measurements)})
        child=dict(status='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS',bindings=dict(bindings),
            formal_baseline=False,physical_evidence_complete=False,accepted_nano_session=False,
            cold_start_replay_complete=True,cycle_equivalence=False,independent_external_memory=True,
            performance_eligible=False,warm_reset_qualified=False,arbitrary_input_equivalence=False,
            parent_mapping=str(mapping),parent_cpu=str(cpu),source_replay=str(source),source_receipt_sha256=sha(receipt),
            transcript_join=joined,frequency_hz=100000000,fresh_rtl_execution_performed=False,
            artifacts={p.name:sha(p) for p in (records,measurements)},
            reason='Same immutable full actual execution rechecked; complete values/call counts unchanged, all fresh hardware counters retained separately')
        packet=output/'completion.json';packet.write_text(json.dumps(child,indent=2)+'\n');bindings[str(packet)]=sha(packet)
        result.update(status='CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS',
                      replay=dict(work=str(output),status=child['status']),
                      reason=child['reason'])
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
