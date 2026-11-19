"""Run every original case on the changed-latency CPU and its own SDRAM model."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source,root):
    edits={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'from scripts.student_mini_cpu_replay_sources import reference_source,quiet_macro,wrapper,compare_transcripts,TOP':
        'from scripts.student_mini_cpu_replay_sources import quiet_macro,TOP\nfrom scripts.student_mini_cpu_latency_replay import memory_source,wrapper,compare_transcripts',
        "paths=[Path(__file__),ROOT/'scripts/student_mini.py'":
        "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_latency_replay.py',ROOT/'scripts/run_student_mini_cpu_boundary_replay.py',ROOT/'scripts/student_mini_cpu_latency_replay.py',ROOT/'scripts/student_mini_cpu_independent_memory.py',ROOT/'scripts/student_mini.py'",
        "if parent['status']!='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS':raise ValueError('SRAM structure stage did not pass')":
        "if parent['status']!='CPU_ROM_REQUEST_MAPPING_STAGE_PASS' or parent.get('macro_count')!=29 or parent.get('read_latency_cycles')!=2:raise ValueError('qualified two-edge ROM and independent memory required')",
        "reference.write_text(reference_source(rtl.read_text()))":"reference.write_text(memory_source(rtl.read_text()))",
        "'CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS'":"'CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'",
        "transcript_join=joined,frequency_hz=100000000,":
        "transcript_join=joined,frequency_hz=100000000,cycle_equivalence=False,independent_external_memory=True,performance_eligible=False,",
        "Mapped storage and original executed CPU match meaningful DFI/UART traffic and all baseline/Nano transcript rows; warm reset, error injection, physical timing/power and quality gates remain":
        "New latency actual CPU uses its own SDRAM, matches all complete baseline/Nano values, and records fresh counters; no cycle/DFI equivalence claimed; warm reset, errors, timing, power and quality remain",
        'COMPILING_MAPPED_CPU_DIFFERENTIAL_REPLAY':'COMPILING_INDEPENDENT_NEW_LATENCY_CPU',
        'EXECUTING_MAPPED_CPU_AND_REFERENCE':'EXECUTING_INDEPENDENT_NEW_LATENCY_CPU',
    }
    for old,new in edits.items():
        expected=2 if old=="'CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS'" else 1
        if source.count(old)!=expected:raise ValueError('new-latency replay seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--cpu-run',type=Path,required=True)
    args=parser.parse_args();original=ROOT/'scripts/run_student_mini_cpu_boundary_replay.py'
    paths=[Path(__file__),original,ROOT/'scripts/student_mini_cpu_latency_replay.py',args.mapping.resolve()/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,cpu=str(args.cpu_run.resolve())),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-latency-replay-continuation'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,cycle_equivalence=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_QUALIFIED_REQUEST_MAPPING')),flush=True)
    with (work/'replay.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--mapping',str(args.mapping.resolve()),'--cpu-run',str(args.cpu_run.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'replay.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['replay']=rows[-1]
    verify(bindings)
    if not code and result.get('replay',{}).get('status')=='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS':
        packet=Path(result['replay']['work'])/'completion.json';child=json.loads(packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(packet)]=sha(packet)
        if child.get('independent_external_memory') is not True or child.get('cycle_equivalence') is not False:
            raise ValueError('independent latency-aware execution markers missing')
        result['status']='CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('replay'))),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_FULL_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
