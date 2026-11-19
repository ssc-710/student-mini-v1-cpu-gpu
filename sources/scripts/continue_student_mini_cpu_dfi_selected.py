"""Selected PTQ replay only on the fully executed, placed DFI-aligned CPU."""
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


def placement_child(parent,platform):
    if (platform!='cpu' or parent.get('status')!='CPU_DFI_OUTPUT_PHYSICAL_PREFLIGHT_STAGE_PASS'
        or parent.get('read_latency_cycles')!=2 or parent.get('dfi_output_latency_cycles')!=1):
        raise ValueError('exact complete DFI CPU physical preflight required')
    child=parent.get('placement',{})
    if child.get('status')!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS' or not isinstance(child.get('work'),str):
        raise ValueError('matching actual placement child required')
    return Path(child['work'])


def checked_execution(parent):
    if (parent.get('status')!='CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'
        or parent.get('cold_start_replay_complete') is not True or parent.get('independent_external_memory') is not True
        or parent.get('dfi_output_latency_cycles')!=1 or parent.get('cycle_equivalence') is not False
        or parent.get('transcript_join',{}).get('baseline_records')!=1000
        or parent.get('transcript_join',{}).get('native_completion') is not True):
        raise ValueError('complete new-boundary actual execution required')
    driver=ROOT/'tests/rtl/student_mini_cpu_failfast_main.cpp'
    if parent.get('bindings',{}).get(str(driver))!=sha(driver):raise ValueError('expected failfast executable driver not bound')
    packet=Path(parent['parent_mapping'])/'completion.json'
    if parent['bindings'].get(str(packet))!=sha(packet):raise ValueError('mapping binding differs')
    mapping=json.loads(packet.read_text())
    if mapping.get('native_read_valid_added_cycles')!=1:raise ValueError('new read-return alignment not qualified')


def runner_source(source,root):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "    if parent.get('status')!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':raise ValueError('actual mapped CPU parent required')":
        '    from scripts.continue_student_mini_cpu_dfi_selected import checked_execution\n    checked_execution(parent)',
        "paths=[Path(__file__),prior/'completion.json'":
        "paths=[Path(__file__),ROOT/'scripts/continue_student_mini_cpu_dfi_selected.py',ROOT/'scripts/run_student_mini_selected_cpu_replay.py',prior/'completion.json'",
        "command=['bash','-c','ulimit -c 0; cd -- \"$1\" || exit; exec \"$2\"','selected-cpu',str(work),str(binary)]":
        "command=['bash','-c','ulimit -c 0; cd -- \"$1\" || exit; exec \"$2\" \"$3\"','selected-cpu',str(work),str(binary),str(prior/'console.log')]",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('selected DFI runner seam changed')
        source=source.replace(old,new)
    return source


def continuation_source(source,root,runner):
    changes={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        'from scripts.continue_student_mini_platform_route import placement_child':
        'from scripts.continue_student_mini_cpu_dfi_selected import placement_child',
        "runner = ROOT/'scripts/run_student_mini_selected_cpu_replay.py'":'runner = Path('+repr(str(runner))+')',
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_dfi_selected.py',ROOT/'scripts/continue_student_mini_selected_cpu.py',",
        "'build/student-mini/selected-cpu-placement-continuation'":"'build/student-mini/selected-dfi-cpu-placement-continuation'",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('selected DFI continuation seam changed')
        source=source.replace(old,new)
    return source


def main():
    original=ROOT/'scripts/continue_student_mini_selected_cpu.py';runner=ROOT/'scripts/run_student_mini_selected_cpu_replay.py'
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-continuation',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    paths=[Path(__file__),original,runner,args.physical_continuation.resolve()/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,arguments=remaining),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/selected-dfi-cpu-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private_runner=work/'runner.py';private_runner.write_text(runner_source(runner.read_text(),ROOT))
    private=work/'producer.py';private.write_text(continuation_source(original.read_text(),ROOT,private_runner))
    bindings.update({str(p):sha(p) for p in (private_runner,private)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,accepted_nano_session=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_DFI_CPU_PLACEMENT')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--physical-continuation',str(args.physical_continuation.resolve()),*remaining],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='SELECTED_PLACED_CPU_NUMERICAL_STAGE_PASS':
        result['status']='SELECTED_DFI_CPU_NUMERICAL_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
