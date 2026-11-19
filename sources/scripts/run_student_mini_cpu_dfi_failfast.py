"""Same complete DFI replay, stopping on the first actual payload mismatch."""
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
from scripts.run_student_mini_cpu_dfi_replay import derive as dfi_source


def replay_source(source,root):
    value=dfi_source(source,root)
    changes={
        "driver=ROOT/'tests/rtl/student_mini_cpu_replay_main.cpp'":"driver=ROOT/'tests/rtl/student_mini_cpu_failfast_main.cpp'",
        'cwd_command([str(binary)])':"cwd_command([str(binary),str(cpu/'console.log')])",
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_dfi_failfast.py',",
    }
    for old,new in changes.items():
        if value.count(old)!=1:raise ValueError('failfast replay seam changed')
        value=value.replace(old,new)
    return value


def derive_launcher(source,root):
    begin=source.index('def derive(');end=source.index('def main():',begin)
    source=source[:begin]+'from scripts.run_student_mini_cpu_dfi_failfast import replay_source as derive\n\n\n'+source[end:]
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_dfi_failfast.py',ROOT/'scripts/run_student_mini_cpu_dfi_replay.py',",
        "'build/student-mini/cpu-dfi-replay-continuation'":"'build/student-mini/cpu-dfi-failfast-continuation'",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('failfast launcher seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--cpu-run',type=Path,required=True)
    args=parser.parse_args();original=ROOT/'scripts/run_student_mini_cpu_dfi_replay.py'
    paths=[Path(__file__),original,args.mapping.resolve()/'completion.json']
    bindings={str(p):sha(p) for p in paths};key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-failfast-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private=work/'producer.py';private.write_text(derive_launcher(original.read_text(),ROOT));bindings[str(private)]=sha(private)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='FAILFAST_COMPLETE_REPLAY_QUEUED')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--mapping',str(args.mapping.resolve()),'--cpu-run',str(args.cpu_run.resolve())],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='CPU_DFI_OUTPUT_FULL_REPLAY_STAGE_PASS':result['status']='CPU_DFI_FAILFAST_REPLAY_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
