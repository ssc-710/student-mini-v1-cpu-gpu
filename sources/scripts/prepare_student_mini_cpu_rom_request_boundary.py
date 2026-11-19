"""Map the proved ROM request cut only after independent-memory qualification."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route
from scripts.student_mini_cpu_replay_sources import TOP


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('proof','independent-replay','placement'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();proof=args.proof.resolve();independent=args.independent_replay.resolve()
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths=[Path(__file__),proof/'completion.json',independent/'inputs.json',args.placement.resolve()/'completion.json',
           tools/'yosys',tools.parent/'libexec/yosys',macro,ROOT/'scripts/retry_student_mini_route.py']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-request-boundary'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
                whole_core_equivalence=False,cycle_equivalence=False,read_latency_cycles=2)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_INDEPENDENT_MEMORY_QUALIFICATION')),flush=True)
    try:
        packet=independent/'completion.json'
        while not packet.is_file():
            heartbeat('WAITING_FOR_INDEPENDENT_MEMORY_QUALIFICATION')
            if time.monotonic()-begin>43200:raise TimeoutError('bounded independent memory wait expired')
            time.sleep(10)
        memory=json.loads(packet.read_text());local=json.loads((proof/'completion.json').read_text())
        if memory['status']!='CPU_INDEPENDENT_MEMORY_LOCKSTEP_STAGE_PASS':raise ValueError('independent memory did not qualify')
        if local['status']!='CPU_ROM_REQUEST_LOCAL_PROOF_STAGE_PASS' or local.get('mutations_killed')!=['wrong-address','early-ack','ignore-cancel','ignore-reset']:
            raise ValueError('complete word and reset-sensitive mutation proof required')
        parent=Path(local['parent']);prior=json.loads((parent/'completion.json').read_text())
        if memory['bindings'].get(str(parent/'completion.json'))!=sha(parent/'completion.json'):
            raise ValueError('memory qualification used a different CPU source')
        placement=json.loads((args.placement/'completion.json').read_text())
        if placement.get('status')!='HOLD' or placement['bindings'].get(str(parent/'completion.json'))!=sha(parent/'completion.json'):
            raise ValueError('measured same-parent physical HOLD required')
        for item in (memory,local,prior,placement):verify(item['bindings']);bindings.update(item['bindings'])
        bindings[str(packet)]=sha(packet);bindings[str(parent/'completion.json')]=sha(parent/'completion.json')
        for name,digest in local['artifacts'].items():
            if sha(proof/name)!=digest:raise ValueError('local proof artifact changed')
            bindings[str(proof/name)]=digest
        mapped=work/'mapped.v';shutil.copyfile(proof/'candidate.v',mapped)
        script=work/'structure.ys'
        script.write_text(f'read_verilog -sv {mapped}\nread_verilog -lib {macro}\nhierarchy -check -top {TOP}\nproc\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/mapped.json\n')
        bindings.update({str(p):sha(p) for p in (mapped,script)})
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            if execute_locked_route([str(tools/'yosys'),'-Q','-T','-s',str(script)],work/'yosys.log',900,lambda _:heartbeat('CHECKING_REQUEST_BOUNDARY_STRUCTURE')):
                raise ValueError('request cut hierarchy/mapping failed')
        design=json.loads((work/'mapped.json').read_text());old=json.loads((parent/'mapped.json').read_text())
        ports=design['modules'][TOP]['ports'];previous=old['modules'][TOP]['ports']
        if set(ports)!=set(previous) or any(ports[k]['direction']!=v['direction'] or len(ports[k]['bits'])!=len(v['bits']) for k,v in previous.items()):
            raise ValueError('physical interface changed')
        cells=design['modules'][TOP]['cells']
        macros=sorted(n for n,c in cells.items() if c['type']=='student_mini_cpu_sram_32x1024')
        if macros!=sorted(prior['macro_instances']) or len(macros)!=29:raise ValueError('SRAM geometry changed')
        if sum(c['type']=='student_mini_cpu_rom_request_cut' for c in cells.values())!=1:
            raise ValueError('unique real request register boundary missing')
        verify(bindings)
        result.update(status='CPU_ROM_REQUEST_MAPPING_STAGE_PASS',macro_count=29,macro_instances=macros,
            parent_mapping=str(parent),parent_independent_replay=str(independent),
            reason='Local words/mutations, same-parent independent memory and structural boundary passed; changed-latency whole CPU and new physical timing remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_MAPPING_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
