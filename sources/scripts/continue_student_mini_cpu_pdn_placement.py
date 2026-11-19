"""Replace an unstarted owned CPU placement with explicit OpenRAM PG binding."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def derive(source,root):
    seam="config = work/'config.mk'; config.write_text(configuration((parent_dir/'config.mk').read_text(),g,placement))"
    replacement=seam+"\n    pg=ROOT/'ppa/openram/connect_openram_power.tcl'\n    config.write_text(config.read_text()+f'export PRE_PDN_TCL = {pg}\\n')\n    bindings[str(pg)]=sha(pg)"
    changes={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        seam:replacement,
        "paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_floorplan.py',":
            "paths = [Path(__file__), ROOT/'scripts/run_student_mini_cpu_placement.py', ROOT/'ppa/openram/connect_openram_power.tcl', ROOT/'scripts/student_mini_cpu_floorplan.py',",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('CPU placement derivation seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis',type=Path,required=True)
    parser.add_argument('--queued-work',type=Path,required=True)
    parser.add_argument('--queued-pid',type=int,required=True)
    args=parser.parse_args();parent=args.synthesis.resolve();queued=args.queued_work.resolve()
    original=ROOT/'scripts/run_student_mini_cpu_placement.py'
    if not queued.is_relative_to(ROOT/'build/student-mini/cpu-placement') or (queued/'completion.json').exists():
        raise ValueError('expected unfinished owned CPU placement')
    files=[Path(__file__),original,ROOT/'scripts/student_mini_cpu_floorplan.py',ROOT/'ppa/openram/connect_openram_power.tcl',queued/'inputs.json',parent/'completion.json']
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-pdn-placement-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    process=Path('/proc')/str(args.queued_pid);descriptor=os.pidfd_open(args.queued_pid);stopped=False
    try:
        command=[p.decode() for p in (process/'cmdline').read_bytes().split(b'\0') if p]
        if (len(command)!=4 or Path(command[1]).name!=original.name or command[2]!='--synthesis'
            or (ROOT/command[3]).resolve()!=parent or (process/'cwd').resolve()!=ROOT
            or (process/'exe').resolve()!=Path('/usr/bin/python3').resolve()):raise ValueError('unexpected queued process')
        signal.pidfd_send_signal(descriptor,signal.SIGSTOP);stopped=True
        locks=subprocess.check_output(['lslocks','-J','-o','PID,MODE,PATH'],text=True)
        owned=[r for r in json.loads(locks)['locks'] if r.get('pid')==args.queued_pid and r.get('path','').endswith('/persistent-ppa/matrix.lock')]
        if (len(owned)!=1 or owned[0]['mode']!='WRITE*'
            or json.loads((queued/'heartbeat.json').read_text())['stage']!='WAITING_FOR_SERIAL_QUEUE'):
            raise ValueError('task already started; leave unchanged')
        receipt=dict(status='QUEUED_CPU_PLACEMENT_REPLACED',created_at=datetime.now(timezone.utc).isoformat(),pid=args.queued_pid,
            command=command,bindings=bindings,queued_work=str(queued),completed_evidence_modified=False,
            reason='Explicit OpenRAM vccd1/vssd1 global connections missing from initial configuration; no layout tool had started')
        (work/'stop-request.json').write_text(json.dumps(receipt,indent=2)+'\n')
        signal.pidfd_send_signal(descriptor,signal.SIGTERM)
    finally:
        if stopped:signal.pidfd_send_signal(descriptor,signal.SIGCONT)
        os.close(descriptor)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings,single_change='add existing OpenRAM PG connection hook'),indent=2)+'\n')
    with (work/'placement.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--synthesis',str(parent)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(line) for line in (work/'placement.log').read_text().splitlines() if line.startswith('{')]
    result=dict(status='HOLD',bindings=bindings,physical_evidence_complete=False,formal_baseline=False,
        placement=rows[-1] if rows else None,exit_code=code)
    if code==0 and result['placement']['status']=='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':result['status']='CPU_PDN_PLACEMENT_PREFLIGHT_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],placement=result['placement'])),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
