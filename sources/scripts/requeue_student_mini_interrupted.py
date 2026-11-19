"""Preserve incomplete attempts and rerun unchanged gates in a fresh boot-bound job."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.resume_student_mini_interrupted import replace_once

KINDS = {
    'cpu-rom-probe':('probe_student_mini_cpu_channel_rom_drive.py','cpu-channel-rom-drive','CPU_CHANNEL_ROM_DRIVE_DIAGNOSTIC_COMPLETE','files'),
    'gpu-footprint':('continue_student_mini_gpu_footprint.py','gpu-footprint-continuation','GPU_FOOTPRINT_PLACEMENT_STAGE_PASS','files'),
    'cpu-warm-reset':('run_student_mini_cpu_warm_reset.py','cpu-warm-reset','CPU_QUIESCENT_WARM_RESET_STAGE_PASS','paths'),
}


def derive(source, root, marker, required):
    source = replace_once(source,'ROOT = Path(__file__).resolve().parents[1]','ROOT = Path('+repr(str(root))+')')
    before = marker+' = [Path(__file__),'
    return replace_once(source,before,before+''.join(' Path('+repr(str(p))+'),' for p in required))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=KINDS,required=True)
    parser.add_argument('--interrupted',type=Path,required=True)
    parser.add_argument('--attempt',required=True)
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args(); filename,folder,expected,marker=KINDS[args.kind]
    prior=args.interrupted.resolve(); packet=prior/'inputs.json'
    if prior.parent!=ROOT/'build/student-mini'/folder or (prior/'completion.json').exists():
        raise ValueError('explicit unfinished original attempt required')
    parent=json.loads(packet.read_text()); original=ROOT/'scripts'/filename
    if parent['bindings'].get(str(original))!=sha(original): raise ValueError('original producer changed')
    verify(parent['bindings'])
    arguments=args.arguments[1:] if args.arguments[:1]==['--'] else args.arguments
    if not arguments: raise ValueError('original invocation arguments required')
    bindings={str(p):sha(p) for p in (Path(__file__),original,packet,ROOT/'scripts/resume_student_mini_interrupted.py')}
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    key=hashlib.sha256(json.dumps(dict(bindings=bindings,boot=boot,attempt=args.attempt,arguments=arguments),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/requeued-interruptions'/key; work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py'; producer.write_text(derive(original.read_text(),ROOT,marker,(Path(__file__),original,packet)))
    bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',kind=args.kind,bindings=bindings,boot_id=boot,arguments=arguments,
                original_attempt=str(prior),old_completion_missing=True,interrupted_resource_peak_available=False,
                created_at=datetime.now(timezone.utc).isoformat(),interruption_cause='not established',
                formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work),stage='REQUEUED_AFTER_INTERRUPTION',kind=args.kind)),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),*arguments],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    verify(bindings)
    rows=[json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['child']=rows[-1]
    if code==0 and result.get('child',{}).get('status')==expected: result['status']='RECOVERED_SCOPED_STAGE_PASS'
    result['exit_code']=code
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return 0 if result['status']=='RECOVERED_SCOPED_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
