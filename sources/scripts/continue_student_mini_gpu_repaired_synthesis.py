"""Synthesize only the exact repaired boundary that passes representative replay."""
import argparse
from datetime import datetime,timezone
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


def derive(source,root):
    old="""        if prior['status']!='RETIMED_GPU_SRAM_BOUNDARY_STAGE_PASS':raise ValueError('retimed mapping did not pass')
        packet=Path(prior['output']);mapped=packet.parent
        if sha(packet)!=prior['output_sha256']:raise ValueError('mapping receipt changed')"""
    new="""        if prior['status']!='GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS' or prior['arithmetic_latency']!=30:raise ValueError('repaired mapping did not pass')
        packet=parent/'completion.json';mapped=parent
        replay_path=args.replay_proof.resolve();replay=json.loads(replay_path.read_text())
        if replay['status']!='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS' or replay['target_run_complete'] is not True or len(replay['records'])!=3:
            raise ValueError('three real repaired-kernel outputs required')
        if sorted(r['operator'] for r in replay['records'])!=['p1','p2','p3']:raise ValueError('representative operators differ')
        verify(replay['bindings']);bindings.update(replay['bindings']);bindings[str(replay_path)]=sha(replay_path)
        for name in ('project-banked.v','vortex_physical_top.sv','vortex_command_adapter.sv'):
            if replay['bindings'].get(str(mapped/name))!=sha(mapped/name):raise ValueError('replay did not execute exact repaired hardware')"""
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "parser.add_argument('--mapping-continuation',type=Path,required=True)":"parser.add_argument('--boundary',type=Path,required=True)\n    parser.add_argument('--replay-proof',type=Path,required=True)",
        'parent=args.mapping_continuation.resolve()':'parent=args.boundary.resolve()',
        'paths=[Path(__file__),':"paths=[Path(__file__),ROOT/'scripts/continue_student_mini_gpu_repaired_synthesis.py',ROOT/'scripts/run_student_mini_gpu_cut_synthesis.py',args.replay_proof.resolve(),",
        old:new,
    }
    for before,after in changes.items():
        if source.count(before)!=1:raise ValueError('synthesis source seam changed: '+before)
        source=source.replace(before,after)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary',type=Path,required=True);parser.add_argument('--replay-continuation',type=Path,required=True)
    args=parser.parse_args();boundary=args.boundary.resolve();replay=args.replay_continuation.resolve()
    original=ROOT/'scripts/run_student_mini_gpu_cut_synthesis.py'
    paths=[Path(__file__),original,ROOT/'scripts/retry_student_mini_route.py',boundary/'completion.json',replay/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-repaired-synthesis-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        heartbeat('WAITING_FOR_REPAIRED_GPU_REPLAY');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_REPAIRED_GPU_REPLAY')),flush=True)
        while not (replay/'completion.json').exists():
            if time.monotonic()-begin>43200:raise TimeoutError('bounded full replay wait expired')
            time.sleep(10)
        receipt=replay/'completion.json';parent=json.loads(receipt.read_text())
        if parent['status']!='REPAIRED_30_CYCLE_GPU_REPRESENTATIVE_STAGE_PASS':raise ValueError('repaired whole-GPU representative replay failed')
        child=Path(parent['replay']['work'])/'completion.json'
        bindings.update(parent['bindings']);bindings[str(receipt)]=sha(receipt);bindings[str(child)]=sha(child);verify(bindings)
        heartbeat('SYNTHESIS_QUEUED')
        with (work/'synthesis.log').open('x') as log:code=subprocess.call([sys.executable,str(producer),'--boundary',str(boundary),'--replay-proof',str(child)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        lines=[json.loads(line) for line in (work/'synthesis.log').read_text().splitlines() if line.startswith('{')]
        if lines:result['synthesis']=lines[-1]
        verify(bindings)
        if code or result.get('synthesis',{}).get('status')!='RETIMED_GPU_SYNTHESIS_STAGE_PASS':raise ValueError('repaired synthesis did not pass; child HOLD retained')
        result.update(status='REPAIRED_GPU_SYNTHESIS_PREFLIGHT_STAGE_PASS',reason='Exact replayed 30-cycle boundary synthesized; new placement and physical gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='REPAIRED_GPU_SYNTHESIS_PREFLIGHT_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
