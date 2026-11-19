"""Replay the entire mapped CPU against its executed same-ROM DFI boundary.

Cold-start differential execution only. Warm reset, protocol faults, synthesis,
post-route activity and whole-release acceptance are deliberately separate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_cpu_replay_sources import reference_source,quiet_macro,wrapper,compare_transcripts,TOP
from scripts.export_student_mini_combined_cpu_boundary import checked_parent,checked_sources
from scripts.retry_student_mini_route import execute_locked_route


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True)
    parser.add_argument('--cpu-run',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=43200)
    args=parser.parse_args()
    if not 0<=args.wait_seconds<=43200: raise ValueError('bounded parent wait required')
    mapping=args.mapping.resolve();cpu=args.cpu_run.resolve()
    tool=Path('/home/soclab/tools/verilator-5.040/bin/verilator')
    macro=ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    driver=ROOT/'tests/rtl/student_mini_cpu_replay_main.cpp'
    paths=[Path(__file__),ROOT/'scripts/student_mini.py',
        ROOT/'scripts/student_mini_cpu_replay_sources.py',
        ROOT/'scripts/assemble_student_mini_cpu_results.py',
        ROOT/'scripts/export_student_mini_combined_cpu_boundary.py',
        ROOT/'scripts/export_student_mini_cpu_boundary.py',
        ROOT/'scripts/retry_student_mini_route.py',tool,tool.with_name('verilator_bin'),
        macro,driver,cpu/'inputs.json']
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(dict(mapping=str(mapping),cpu=str(cpu),bindings=bindings),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-boundary-replay'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,
        accepted_nano_session=False,warm_reset_qualified=False,arbitrary_input_equivalence=False,
        bindings=bindings,parent_mapping=str(mapping),parent_cpu=str(cpu))
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        for name,value in bindings.items():
            if sha(Path(name))!=value:raise ValueError('CPU replay input changed: '+name)
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_EXECUTED_ROM_SRAM_MAPPING')),flush=True)
        while not (mapping/'completion.json').exists():
            heartbeat('WAITING_FOR_EXECUTED_ROM_SRAM_MAPPING')
            if time.monotonic()-started>args.wait_seconds:raise TimeoutError('mapping wait expired')
            time.sleep(10)
        parent=json.loads((mapping/'completion.json').read_text())
        if parent['status']!='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS':raise ValueError('SRAM structure stage did not pass')
        original,executed=checked_parent(cpu)
        for name in ('mapped.json','mapped.v'):
            path=mapping/name
            if parent['artifacts'].get(name)!=sha(path):raise ValueError('mapped artifact changed')
            bindings[str(path)]=sha(path)
        bindings.update(parent['bindings']);bindings.update(executed['bindings'])
        for path in (mapping/'completion.json',cpu/'completion.json',cpu/'console.log'):
            bindings[str(path)]=sha(path)
        # Mapping lineage must include this exact CPU execution, not an older ROM.
        if parent['bindings'].get(str(cpu/'completion.json'))!=sha(cpu/'completion.json'):
            raise ValueError('mapped CPU does not belong to this executed ROM')
        gateware=cpu/'soc/gateware';sources=checked_sources(gateware,original)
        rtl=gateware/'sim.v';reference=work/'reference.v'
        reference.write_text(reference_source(rtl.read_text()))
        design=json.loads((mapping/'mapped.json').read_text())
        bridge=work/'bridge.sv';bridge.write_text(wrapper(design['modules'][TOP]['ports']))
        actual_macro=work/'macro.v';actual_macro.write_text(quiet_macro(macro.read_text()))
        for path in gateware.glob('*.init'):
            if executed['artifacts'].get('soc/gateware/'+path.name)!=sha(path):
                raise ValueError('executed memory initialization changed')
            bindings[str(path)]=sha(path);shutil.copyfile(path,work/path.name)
        compilation=[reference if p==rtl else p for p in sources]
        compilation += [mapping/'mapped.v',actual_macro,bridge]
        for path in [*sources,reference,actual_macro,bridge,*work.glob('*.init')]:
            bindings[str(path)]=sha(path)
        command=[str(tool),'--cc','--exe','--build','--timing','--timescale-override','1ns/1ps',
            '--top-module','cpu_boundary_replay','-Wno-fatal','-j','2','--Mdir',str(work/'obj'),
            '-CFLAGS','-O2',*[str(p) for p in compilation],str(driver)]
        def cwd_command(command):
            return ['bash','-c','ulimit -c 0; cd -- "$1" || exit; shift; exec "$@"','cpu-replay',str(work),*command]
        result['compile_command']=command
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            code=execute_locked_route(cwd_command(command),work/'compile.log',1800,
                lambda _:heartbeat('COMPILING_MAPPED_CPU_DIFFERENTIAL_REPLAY'))
            if code:raise RuntimeError('mapped CPU replay compile failed')
            binary=work/'obj/Vcpu_boundary_replay';bindings[str(binary)]=sha(binary)
            code=execute_locked_route(cwd_command([str(binary)]),work/'console.log',3600,
                lambda _:heartbeat('EXECUTING_MAPPED_CPU_AND_REFERENCE'))
            if code:raise RuntimeError('mapped CPU differential replay failed')
            text=(work/'console.log').read_text()
            joined=compare_transcripts((cpu/'console.log').read_text(),text)
            if sum(line.startswith('CPU_BOUNDARY_REPLAY_COMPLETE cycles=') for line in text.splitlines())!=1:
                raise ValueError('missing physical-boundary replay completion')
            fresh()
        result.update(status='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS',cold_start_replay_complete=True,
            transcript_join=joined,frequency_hz=100000000,
            reason='Mapped storage and original executed CPU match meaningful DFI/UART traffic and all baseline/Nano transcript rows; warm reset, error injection, physical timing/power and quality gates remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
