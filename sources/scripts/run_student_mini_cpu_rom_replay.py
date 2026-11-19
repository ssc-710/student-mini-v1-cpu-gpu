"""Full same-ROM CPU differential after the isolated output-register retiming."""
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
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "if parent['status']!='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS':raise ValueError('SRAM structure stage did not pass')":
        "if parent['status']!='CPU_ROM_CUT_MAPPING_STAGE_PASS' or parent.get('rom_differential_records')!=37888 or parent.get('read_latency_cycles')!=1:raise ValueError('ROM cut differential/structure did not pass')",
        "paths=[Path(__file__),ROOT/'scripts/student_mini.py'":
        "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_rom_replay.py',ROOT/'scripts/run_student_mini_cpu_boundary_replay.py',ROOT/'scripts/student_mini.py'",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('CPU producer seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--cpu-run',type=Path,required=True)
    args=parser.parse_args();mapping=args.mapping.resolve();parent=json.loads((mapping/'completion.json').read_text())
    if parent['status']!='CPU_ROM_CUT_MAPPING_STAGE_PASS':raise ValueError('ROM cut structure not passed')
    bindings=dict(parent['bindings']);verify(bindings)
    original=ROOT/'scripts/run_student_mini_cpu_boundary_replay.py'
    for p in (Path(__file__),original,mapping/'completion.json'):bindings[str(p)]=sha(p)
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,cpu=str(args.cpu_run.resolve())),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-replay-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),stage='CPU_ROM_REPLAY_QUEUED')),flush=True)
    with (work/'replay.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--mapping',str(mapping),'--cpu-run',str(args.cpu_run.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    lines=[json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
    if lines:result['replay']=lines[-1]
    verify(bindings)
    if code==0 and result.get('replay',{}).get('status')=='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':result['status']='CPU_ROM_CUT_FULL_REPLAY_STAGE_PASS'
    result['reason']='Full original CPU/DFI/UART/output/counter replay after ROM-only register retiming; physical gates separate'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'])),flush=True)
    return 0 if result['status']=='CPU_ROM_CUT_FULL_REPLAY_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
