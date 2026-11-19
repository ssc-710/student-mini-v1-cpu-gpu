"""Run full cold-start CPU differential only after the scoped cache-tag proof."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source, root):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "if parent['status']!='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS':raise ValueError('SRAM structure stage did not pass')":
        "if parent['status']!='CPU_TAG_REGISTER_MAPPING_STAGE_PASS' or parent.get('differential_records')!=15360 or parent.get('macro_count')!=29 or parent.get('tag_register_bits')!=11296:raise ValueError('tag differential/structure did not pass')",
        "paths=[Path(__file__),ROOT/'scripts/student_mini.py'":
        "paths=[Path(__file__),ROOT/'scripts/run_student_mini_cpu_tag_replay.py',ROOT/'scripts/run_student_mini_cpu_boundary_replay.py',ROOT/'scripts/student_mini.py'",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('CPU replay producer seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--cpu-run',type=Path,required=True)
    args=parser.parse_args();mapping=args.mapping.resolve();original=ROOT/'scripts/run_student_mini_cpu_boundary_replay.py'
    files=[Path(__file__),original,mapping/'inputs.json',ROOT/'scripts/retry_student_mini_route.py']
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,cpu=str(args.cpu_run.resolve())),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-tag-replay-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        heartbeat('WAITING_FOR_CACHE_TAG_PROOF');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_CACHE_TAG_PROOF')),flush=True)
        while not (mapping/'completion.json').exists():
            if time.monotonic()-begin>43200:raise TimeoutError('bounded tag proof wait expired')
            time.sleep(10)
        receipt=mapping/'completion.json';parent=json.loads(receipt.read_text())
        if parent['status']!='CPU_TAG_REGISTER_MAPPING_STAGE_PASS':raise ValueError('cache-tag proof failed')
        bindings.update(parent['bindings']);bindings[str(receipt)]=sha(receipt);verify(bindings)
        heartbeat('FULL_CPU_REPLAY_QUEUED')
        with (work/'replay.log').open('x') as log:
            code=subprocess.call([sys.executable,str(producer),'--mapping',str(mapping),'--cpu-run',str(args.cpu_run.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        lines=[json.loads(line) for line in (work/'replay.log').read_text().splitlines() if line.startswith('{')]
        if lines:result['replay']=lines[-1]
        verify(bindings)
        if code or result.get('replay',{}).get('status')!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS':raise ValueError('full cache-tag CPU replay failed; child HOLD preserved')
        result.update(status='CPU_TAG_REGISTER_FULL_REPLAY_STAGE_PASS',reason='Actual whole same-ROM CPU/DFI/UART/baseline/Nano and counters agree; synthesis and 100 MHz physical qualification remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_TAG_REGISTER_FULL_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
