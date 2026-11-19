"""Bind selected PTQ input to the qualified new-latency CPU binary and layout."""
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
from scripts.recheck_student_mini_cpu_latency_counters import eligible


def placement_child(parent,platform):
    if platform!='cpu' or parent.get('status')!='CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS' or parent.get('read_latency_cycles')!=2:
        raise ValueError('exact new-latency CPU physical preflight required')
    child=parent.get('placement',{})
    if child.get('status')!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS' or not isinstance(child.get('work'),str):
        raise ValueError('exact new-latency CPU placement child required')
    return Path(child['work'])


def qualified_execution(parent,qualification,prior):
    eligible(parent)
    if (qualification.get('status')!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'
        or qualification.get('independent_external_memory') is not True
        or qualification.get('cycle_equivalence') is not False
        or qualification.get('source_replay')!=str(prior)
        or qualification.get('parent_mapping')!=parent.get('parent_mapping')
        or qualification.get('transcript_join',{}).get('baseline_records')!=1000):
        raise ValueError('complete same-binary independent-memory execution qualification required')
    receipt=prior/'completion.json'
    if qualification.get('bindings',{}).get(str(receipt))!=sha(receipt):
        raise ValueError('rechecked execution receipt differs')
    verify(qualification['bindings'])


def runner_source(source,root,qualification):
    edits={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "    if parent.get('status')!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':raise ValueError('actual mapped CPU parent required')":
        "    from scripts.continue_student_mini_cpu_request_selected import qualified_execution\n    qualification_path=Path("+repr(str(qualification))+")\n    qualification=json.loads(qualification_path.read_text())\n    qualified_execution(parent,qualification,prior)",
        "    bindings=dict(parent['bindings']);verify(bindings)":
        "    bindings=dict(parent['bindings']);bindings.update(qualification['bindings']);bindings[str(qualification_path)]=sha(qualification_path);verify(bindings)",
        "paths=[Path(__file__),prior/'completion.json'":
        "paths=[Path(__file__),ROOT/'scripts/continue_student_mini_cpu_request_selected.py',ROOT/'scripts/run_student_mini_selected_cpu_replay.py',prior/'completion.json'",
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('selected request CPU runner seam changed')
        source=source.replace(old,new)
    return source


def continuation_source(source,root,runner,qualification):
    edits={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        'from scripts.continue_student_mini_platform_route import placement_child':
        'from scripts.continue_student_mini_cpu_request_selected import placement_child',
        "runner = ROOT/'scripts/run_student_mini_selected_cpu_replay.py'":'runner = Path('+repr(str(runner))+')',
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_request_selected.py',ROOT/'scripts/continue_student_mini_selected_cpu.py',Path("+repr(str(qualification))+"),",
        "'build/student-mini/selected-cpu-placement-continuation'":"'build/student-mini/selected-request-cpu-placement-continuation'",
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('selected request CPU continuation seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification',type=Path,required=True)
    args,child_args=parser.parse_known_args();qualification=args.qualification.resolve()
    original=ROOT/'scripts/continue_student_mini_selected_cpu.py';runner=ROOT/'scripts/run_student_mini_selected_cpu_replay.py'
    bindings={str(p):sha(p) for p in (Path(__file__),original,runner,qualification)}
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,arguments=child_args),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-request-cpu-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private_runner=work/'runner.py';private_runner.write_text(runner_source(runner.read_text(),ROOT,qualification))
    producer=work/'producer.py';producer.write_text(continuation_source(original.read_text(),ROOT,private_runner,qualification))
    bindings.update({str(p):sha(p) for p in (private_runner,producer)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,accepted_nano_session=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_NEW_CPU_PLACEMENT')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),*child_args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS':
        packet=Path(result['child']['work'])/'completion.json';value=json.loads(packet.read_text())
        verify(value['bindings']);bindings.update(value['bindings']);bindings[str(packet)]=sha(packet)
        result['status']='SELECTED_REQUEST_CPU_NUMERICAL_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return 0 if result['status']=='SELECTED_REQUEST_CPU_NUMERICAL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
