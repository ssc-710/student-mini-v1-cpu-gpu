"""Prove the cache-tag replacement against real SRAM before any CPU/physical run."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_cpu_tag_registers import replace_tag, original_wrapper, MODULE
from scripts.student_mini_cpu_replay_sources import TOP
from scripts.audit_student_mini_cpu_timing import worst_setup
from scripts.retry_student_mini_route import verify, execute_locked_route


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();parent=args.mapping.resolve();placement=args.placement.resolve()
    prior=json.loads((parent/'completion.json').read_text());failed=json.loads((placement/'completion.json').read_text())
    if prior['status']!='CPU_ROM_CUT_MAPPING_STAGE_PASS' or failed['status']!='HOLD' or not failed['macro_power_connected']:
        raise ValueError('verified ROM-cut candidate with observed powered timing HOLD required')
    bindings=dict(prior['bindings']);bindings.update(failed['bindings'])
    for name,digest in prior['artifacts'].items():bindings[str(parent/name)]=digest
    rpt=Path(failed['reports_directory'])/'3_detailed_place.rpt'
    if failed['artifacts'].get(str(rpt))!=sha(rpt):raise ValueError('unbound negative timing report')
    path=worst_setup(rpt.read_text(),failed['placement_wns_ns'])
    if path['startpoint']!='tag_mem.0.0.storage' or path['endpoint']!='data_mem_grain1.0.0.storage':
        raise ValueError('not the diagnosed tag-to-data path')
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    bench=ROOT/'tests/rtl/student_mini_cpu_tag_registers.sv'
    files=[Path(__file__),ROOT/'scripts/student_mini_cpu_tag_registers.py',ROOT/'scripts/audit_student_mini_cpu_timing.py',
        ROOT/'scripts/retry_student_mini_route.py',parent/'completion.json',placement/'completion.json',rpt,macro,bench,
        tools/'iverilog',tools/'vvp',tools/'yosys',tools.parent/'libexec/yosys']
    bindings.update({str(p):sha(p) for p in files});verify(bindings)
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-tag-registers'/identity;work.mkdir(parents=True,exist_ok=False)
    original=(parent/'mapped.v').read_text();mapped=work/'mapped.v';mapped.write_text(replace_tag(original))
    isolated=work/'tag-models.sv';isolated.write_text(original_wrapper(original)+MODULE)
    bindings.update({str(p):sha(p) for p in (mapped,isolated)})
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,whole_core_equivalence=False,
        bindings=bindings,macro_count=29,tag_words=512,tag_bits=22,tag_storage='actual synthesizable standard-cell registers',
        parent_mapping=str(parent),parent_placement=str(placement),observed_negative_path=path,
        collision_scope='Same-address write-first bypass remains byte-identical in original top; isolated macro comparison excludes unspecified raw collisions',
        internal_phase_change='Tag result now available after rising edge; next-rising-edge architectural comparison remains mandatory')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='TAG_PROOF_QUEUED')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            binary=work/'tag.vvp'
            compiled=subprocess.run([str(tools/'iverilog'),'-g2012','-s','bench','-o',str(binary),str(isolated),str(bench),str(macro)],capture_output=True,text=True,timeout=60)
            (work/'compile.log').write_text(compiled.stdout+compiled.stderr)
            if compiled.returncode:raise ValueError('tag proof compile failed')
            with (work/'tag-differential.log').open('x') as log:
                code=subprocess.call([str(tools/'vvp'),str(binary)],stdout=log,stderr=subprocess.STDOUT,timeout=60)
            lines=(work/'tag-differential.log').read_text().splitlines()
            rows=[line for line in lines if line.startswith('TAG_ROW ')]
            if code or len(rows)!=15360 or lines.count('CPU_TAG_REGISTERS_PASS seeds=10 rows=15360 words=512 bits=22')!=1:
                raise ValueError('tag full-word differential or seed coverage failed')
            for index,line in enumerate(rows):
                match=re.fullmatch(r'TAG_ROW seed=(\d+) index=(\d+) rd=[01] wa=\d+ ra=\d+ mask=[0-9a-f] data=[0-9a-f]{8} golden=([0-9a-fx]{6}) old=([0-9a-fx]{6}) actual=([0-9a-fx]{6})',line)
                if not match or int(match[1])!=index//1536+1 or int(match[2])!=index or len(set(match.groups()[2:]))!=1:
                    raise ValueError('tag transcript mismatch or duplicate/missing row')
            result['differential_records']=len(rows);result['seeds']=list(range(1,11))
            script=work/'structure.ys';script.write_text(f'read_verilog -sv {mapped}\nread_verilog -lib {macro}\nhierarchy -check -top {TOP}\nproc\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/mapped.json\n')
            bindings[str(script)]=sha(script)
            if execute_locked_route([str(tools/'yosys'),'-Q','-T','-s',str(script)],work/'structure.log',900,lambda _:heartbeat('VERIFYING_29_SRAM_PLUS_REAL_TAG_REGISTERS')):
                raise ValueError('tag candidate structure failed')
            design=json.loads((work/'mapped.json').read_text());cells=design['modules'][TOP]['cells']
            macros=[name for name,cell in cells.items() if cell['type']=='student_mini_cpu_sram_32x1024']
            if sorted(macros)!=sorted(n for n in prior['macro_instances'] if n!='tag_mem.0.0'):
                raise ValueError('unrelated SRAM mapping changed')
            storage=design['modules']['student_mini_cpu_cache_tag_registers']['cells']
            bits=sum(int(c['parameters']['WIDTH'],2) for c in storage.values() if c['type']=='$dff')
            if bits!=512*22+32:raise ValueError('tag storage is not exactly 11264 register bits plus 32-bit read output')
            result['tag_register_bits']=bits;result['macro_instances']=macros
            result['remaining_logic_memories']=[dict(name=name,width=int(c['parameters']['WIDTH'],2),depth=int(c['parameters']['SIZE'],2),write_ports=int(c['parameters']['WR_PORTS'],2)) for name,c in cells.items() if c['type']=='$mem_v2']
            verify(bindings)
            result.update(status='CPU_TAG_REGISTER_MAPPING_STAGE_PASS',reason='Real SRAM/tag-register full-word differential and exact storage structure passed; whole CPU replay and new 100 MHz physical gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_TAG_REGISTER_MAPPING_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
