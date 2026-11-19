"""Fresh complete execution of the DFI-latency candidate, with actual counters."""
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
from scripts.run_student_mini_cpu_latency_replay import derive as latency_source


def derive(source,root):
    source=latency_source(source,root)
    changes={
        'from scripts.student_mini_cpu_latency_replay import memory_source,wrapper,compare_transcripts':
        'from scripts.student_mini_cpu_latency_replay import memory_source,wrapper\nfrom scripts.student_mini_cpu_latency_counters import compare_transcripts',
        "paths=[Path(__file__),":
        "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_dfi_replay.py',ROOT/'scripts/student_mini_cpu_latency_counters.py',",
        "if parent['status']!='CPU_ROM_REQUEST_MAPPING_STAGE_PASS' or parent.get('macro_count')!=29 or parent.get('read_latency_cycles')!=2:raise ValueError('qualified two-edge ROM and independent memory required')":
        "if parent['status']!='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' or parent.get('macro_count')!=29 or parent.get('read_latency_cycles')!=2 or parent.get('dfi_output_latency_cycles')!=1 or parent.get('local_formal_steps')!=24 or parent.get('mutants_killed')!=4:raise ValueError('proved complete DFI output tuple required')",
        "'CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'":"'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'",
        'cycle_equivalence=False,independent_external_memory=True,performance_eligible=False,':
        'cycle_equivalence=False,independent_external_memory=True,performance_eligible=False,dfi_output_latency_cycles=1,',
    }
    for old,new in changes.items():
        expected=2 if old=="'CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'" else 1
        if source.count(old)!=expected:raise ValueError('DFI replay derivation seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--cpu-run',type=Path,required=True)
    args=parser.parse_args();mapping=args.mapping.resolve();packet=mapping/'completion.json'
    parent=json.loads(packet.read_text())
    if parent['status']!='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS':raise ValueError('DFI mapping must finish first')
    verify(parent['bindings'])
    original=ROOT/'scripts/run_student_mini_cpu_boundary_replay.py'
    paths=[Path(__file__),original,ROOT/'scripts/run_student_mini_cpu_latency_replay.py',
           ROOT/'scripts/student_mini_cpu_latency_counters.py',packet]
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,cpu=str(args.cpu_run.resolve())),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-replay-continuation'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,cycle_equivalence=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='COMPLETE_DFI_CANDIDATE_REPLAY')),flush=True)
    with (work/'replay.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--mapping',str(mapping),'--cpu-run',str(args.cpu_run.resolve())],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'replay.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['replay']=rows[-1]
    verify(bindings)
    if not code and result.get('replay',{}).get('status')=='CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS':
        child_packet=Path(result['replay']['work'])/'completion.json';child=json.loads(child_packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(child_packet)]=sha(child_packet)
        if child['transcript_join']['baseline_records']!=1000 or child.get('independent_external_memory') is not True:
            raise ValueError('incomplete actual DFI candidate execution')
        result['status']='CPU_DFI_OUTPUT_FULL_REPLAY_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('replay'))),flush=True)
    return 0 if result['status']=='CPU_DFI_OUTPUT_FULL_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
