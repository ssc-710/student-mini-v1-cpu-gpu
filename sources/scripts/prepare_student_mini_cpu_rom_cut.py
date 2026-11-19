"""Prove all ROM addresses, then structurally prepare a latency-preserving cut."""
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
from scripts.student_mini_cpu_rom_cut import retime_rom,rom_parts,isolated_rom,check_rom_transcript
from scripts.student_mini_cpu_replay_sources import TOP
from scripts.retry_student_mini_route import execute_locked_route,verify


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mapping',type=Path,required=True)
    args=parser.parse_args();parent=args.mapping.resolve();prior=json.loads((parent/'completion.json').read_text())
    if prior['status']!='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS' or prior['macro_count']!=30:raise ValueError('original actual SRAM mapping required')
    bindings=dict(prior['bindings'])
    for name,digest in prior['artifacts'].items():
        path=parent/name
        if sha(path)!=digest:raise ValueError('parent artifact changed')
        bindings[str(path)]=digest
    tools=Path('/home/soclab/tools/oss-cad-suite/bin');bench=ROOT/'tests/rtl/student_mini_cpu_rom_cut.sv'
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths=[Path(__file__),ROOT/'scripts/student_mini_cpu_rom_cut.py',bench,parent/'completion.json',macro,tools/'iverilog',tools/'vvp',tools/'yosys',tools.parent/'libexec/yosys',ROOT/'scripts/retry_student_mini_route.py']
    bindings.update({str(p):sha(p) for p in paths});verify(bindings)
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-cut'/identity;work.mkdir(parents=True,exist_ok=False)
    original=(parent/'mapped.v').read_text();_,_,words=rom_parts(original)
    mapped=work/'mapped.v';mapped.write_text(retime_rom(original))
    isolated=work/'roms.sv';isolated.write_text(isolated_rom(original,'original')+retime_rom(isolated_rom(original,'cut')))
    bindings[str(mapped)]=sha(mapped);bindings[str(isolated)]=sha(isolated)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,whole_core_equivalence=False,
        physical_flow_ready=False,bindings=bindings,parent=str(parent),macro_count=30,read_latency_cycles=1,
        rom_words=12558,rom_words_sha256=hashlib.sha256(b''.join(v.to_bytes(4,'little') for v in words)).hexdigest())
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');begin=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    try:
        binary=work/'rom.vvp'
        compiled=subprocess.run([str(tools/'iverilog'),'-g2012','-s','bench','-o',str(binary),str(isolated),str(bench)],capture_output=True,text=True,timeout=60)
        (work/'rom-compile.log').write_text(compiled.stdout+compiled.stderr)
        if compiled.returncode:raise RuntimeError('ROM seam compile failed')
        with (work/'rom-differential.log').open('x') as log:
            code=subprocess.call([str(tools/'vvp'),str(binary)],stdout=log,stderr=subprocess.STDOUT,timeout=60)
        text=(work/'rom-differential.log').read_text()
        if code:raise ValueError('ROM full-address/stability simulation failed')
        result['rom_differential']=check_rom_transcript(text)
        result['rom_differential_records']=37888;result['rom_seeds']=list(range(1,11))
        script=work/'structure.ys';script.write_text(f'read_verilog -sv {mapped}\nread_verilog -lib {macro}\nhierarchy -check -top {TOP}\nproc\nmemory_collect\nopt_clean\ncheck -assert\nwrite_json {work}/mapped.json\n')
        bindings[str(script)]=sha(script)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work),stage='ROM_DIFFERENTIAL_PASS_WAITING_FOR_MAPPING')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            if execute_locked_route([str(tools/'yosys'),'-Q','-T','-s',str(script)],work/'yosys.log',900,lambda _:heartbeat('CHECKING_ROM_CUT_STRUCTURE')):raise RuntimeError('ROM cut structure failed')
            design=json.loads((work/'mapped.json').read_text());old=json.loads((parent/'mapped.json').read_text())
            if design['modules'][TOP]['ports'].keys()!=old['modules'][TOP]['ports'].keys():raise ValueError('physical ports changed')
            for name,row in old['modules'][TOP]['ports'].items():
                actual=design['modules'][TOP]['ports'][name]
                if row['direction']!=actual['direction'] or len(row['bits'])!=len(actual['bits']):raise ValueError('port geometry changed')
            cells=design['modules'][TOP]['cells']
            macros=[name for name,cell in cells.items() if cell['type']=='student_mini_cpu_sram_32x1024']
            if sorted(macros)!=sorted(prior['macro_instances']):raise ValueError('actual SRAM mapping changed')
            result['macro_instances']=macros
            result['remaining_logic_memories']=[dict(name=name,width=int(cell['parameters']['WIDTH'],2),depth=int(cell['parameters']['SIZE'],2),write_ports=int(cell['parameters']['WR_PORTS'],2)) for name,cell in cells.items() if cell['type']=='$mem_v2']
            verify(bindings)
        result.update(status='CPU_ROM_CUT_MAPPING_STAGE_PASS',reason='Actual ROM all-address 4-state differential and 30-macro hierarchy passed; full CPU replay and new 100 MHz physical evidence still required')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-begin
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_CUT_MAPPING_STAGE_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
