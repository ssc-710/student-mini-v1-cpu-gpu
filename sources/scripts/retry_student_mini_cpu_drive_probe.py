"""Retry the immutable timing probe using this pinned OpenROAD's replace_cell API."""
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


def hook_source(source):
    old='resize_cell [get_cells _074408_] sky130_fd_sc_hd__a21boi_$strength'
    if source.count(old)!=1:raise ValueError('exact unsupported command required')
    return source.replace(old,'replace_cell _074408_ sky130_fd_sc_hd__a21boi_$strength')


def producer_source(source,root,hook):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "hook=ROOT/'integration/student-mini/cpu_multiplier_drive_probe.tcl'":'hook=Path('+repr(str(hook))+')',
        '(Path(__file__),packet,report,odb,sdc,liberty,macro,rc,hook,tool,':
        "(Path(__file__),ROOT/'scripts/retry_student_mini_cpu_drive_probe.py',ROOT/'scripts/probe_student_mini_cpu_multiplier_drive.py',ROOT/'integration/student-mini/cpu_multiplier_drive_probe.tcl',packet,report,odb,sdc,liberty,macro,rc,hook,tool,",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('private drive probe seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--failed-probe',type=Path,required=True)
    parser.add_argument('--placement',type=Path,required=True);args=parser.parse_args()
    packet=args.failed_probe.resolve()/'completion.json';failed=json.loads(packet.read_text());verify(failed['bindings'])
    log=args.failed_probe.resolve()/'probe.log'
    if failed['status']!='HOLD' or failed['artifacts'].get('probe.log')!=sha(log) or 'invalid command name "resize_cell"' not in log.read_text():
        raise ValueError('actual unsupported-command HOLD required')
    original=ROOT/'scripts/probe_student_mini_cpu_multiplier_drive.py';hook=ROOT/'integration/student-mini/cpu_multiplier_drive_probe.tcl'
    bindings={str(p):sha(p) for p in (Path(__file__),original,hook,packet,log,args.placement.resolve()/'completion.json')}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-drive-probe-api-retry'/key;work.mkdir(parents=True,exist_ok=False)
    private_hook=work/'probe.tcl';private_hook.write_text(hook_source(hook.read_text()))
    producer=work/'producer.py';producer.write_text(producer_source(original.read_text(),ROOT,private_hook))
    bindings.update({str(p):sha(p) for p in (producer,private_hook)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,diagnostic_only=True)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='CORRECT_API_PROBE_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),'--placement',str(args.placement.resolve())],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE':result['status']='CPU_DRIVE_API_DIAGNOSTIC_COMPLETE'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
