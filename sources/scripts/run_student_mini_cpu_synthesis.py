"""Bounded synthesis of the replayed same-ROM CPU; no placement/PASS shortcut."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.normalize_student_mini_macro_lef import normalize
from scripts.retry_student_mini_route import execute_locked_route
from scripts.student_mini_cpu_replay_sources import TOP

MACRO='vortex_sp_32x1024_w4'


def cpu_constraints(original):
    if original.count('clk_i')!=2 or 'set clk_period 10.000' not in original:
        raise ValueError('unexpected frozen timing constraint')
    return original.replace('clk_i','sys_clk')


def macro_declaration(module):
    if not module.get('ports'):raise ValueError('empty macro ports')
    rows=[]
    for name,row in module['ports'].items():
        if not re.fullmatch('[a-zA-Z_][a-zA-Z_0-9]*',name) or row['direction'] not in ('input','output'):
            raise ValueError('unexpected macro port')
        width=len(row['bits'])
        if not 1<=width<=32:raise ValueError('macro port width differs')
        rows.append(f'{row["direction"]} wire [{width-1}:0] {name}')
    return '(* blackbox *) module '+MACRO+'('+',\n'.join(rows)+');\nendmodule\n'


def synthesis_size(text):
    areas=re.findall(r"Chip area for module '\\"+re.escape(TOP)+r"':\s*([0-9.eE+-]+)",text)
    cells=re.findall(r'(?m)^\s*(\d+)\s+\S+\s+\d+\s+\S+\s+cells\s*$',text)
    if len(areas)!=1 or len(cells)!=1:raise ValueError('ambiguous synthesis statistics')
    area=float(areas[0]);count=int(cells[0])
    if not math.isfinite(area) or area<=0 or not 0<count<=500000:
        raise ValueError('CPU synthesis exceeds bounded size preflight')
    return dict(cell_count=count,cell_and_macro_area_um2=area)


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=43200)
    args=parser.parse_args()
    if not 0<=args.wait_seconds<=43200:raise ValueError('bounded wait required')
    replay=args.replay.resolve();orfs=Path('/home/soclab/src/orfs-clean-aabf2a')
    openroad=Path('/home/soclab/.local/bin/openroad');yosys=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    manifest=ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    paths=[Path(__file__),ROOT/'scripts/student_mini.py',ROOT/'scripts/student_mini_cpu_replay_sources.py',
        ROOT/'scripts/retry_student_mini_route.py',ROOT/'scripts/normalize_student_mini_macro_lef.py',
        ROOT/'ppa/common/constraint.sdc',manifest,openroad,yosys,yosys.parent.parent/'libexec/yosys',orfs/'flow/Makefile']
    paths += [p for folder in (orfs/'flow/scripts',orfs/'flow/platforms/sky130hd') for p in folder.rglob('*') if p.is_file()]
    bindings={str(p):sha(p) for p in paths}
    staged=json.loads(manifest.read_text())
    if staged['status']!='PASS':raise ValueError('staged macro provenance incomplete')
    selected=[r for r in staged['macros'] if r['macro_name']==MACRO]
    if len(selected)!=1:raise ValueError('ambiguous physical SRAM')
    views={}
    for name,row in selected[0]['artifacts'].items():
        path=Path(row['path'])
        if sha(path)!=row['sha256']:raise ValueError('macro artifact changed')
        bindings[str(path)]=row['sha256'];views[name]=path
    identity=hashlib.sha256(json.dumps(dict(replay=str(replay),bindings=bindings),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-synthesis'/identity;work.mkdir(parents=True,exist_ok=False)
    variant='student-mini-cpu-'+identity[:16]
    result_dir=orfs/'flow/results/sky130hd'/TOP/variant
    log_dir=orfs/'flow/logs/sky130hd'/TOP/variant
    report_dir=orfs/'flow/reports/sky130hd'/TOP/variant
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,
        placement_complete=False,bindings=bindings,clock_period_ns=10,threads=2,
        result_directory=str(result_dir),metrics_directory=str(log_dir),reports_directory=str(report_dir))
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('CPU synthesis source changed')
    try:
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_CPU_MAPPED_COLD_START_REPLAY')),flush=True)
        while not (replay/'completion.json').exists():
            heartbeat('WAITING_FOR_CPU_MAPPED_COLD_START_REPLAY')
            if time.monotonic()-started>args.wait_seconds:raise TimeoutError('CPU replay wait expired')
            time.sleep(10)
        parent=json.loads((replay/'completion.json').read_text())
        if parent['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' or parent.get('cold_start_replay_complete') is not True:
            raise ValueError('mapped CPU execution not qualified')
        mapping=Path(parent['parent_mapping']);mapped=json.loads((mapping/'completion.json').read_text())
        for name in ('mapped.v','mapped.json'):
            if parent['bindings'].get(str(mapping/name))!=sha(mapping/name):raise ValueError('replayed mapped source changed')
        bindings.update(parent['bindings']);bindings[str(replay/'completion.json')]=sha(replay/'completion.json')
        bindings[str(mapping/'completion.json')]=sha(mapping/'completion.json')
        design=json.loads((mapping/'mapped.json').read_text())
        blackbox=work/'macro-blackbox.v';blackbox.write_text(macro_declaration(design['modules'][MACRO]))
        normalized,audit=normalize(views[MACRO+'.lef'].read_text())
        lef=work/(MACRO+'.lef');lef.write_text(normalized)
        sdc=work/'constraint.sdc';sdc.write_text(cpu_constraints((ROOT/'ppa/common/constraint.sdc').read_text()))
        memories=mapped['remaining_logic_memories']
        largest=max(row['width']*row['depth'] for row in memories)
        if not 0<largest<=1048576:raise ValueError('unexpected remaining CPU memory scale')
        config=work/'config.mk'
        config.write_text('\n'.join(['export PLATFORM = sky130hd','export DESIGN_NAME = '+TOP,
            f'export VERILOG_FILES = {mapping}/mapped.v {blackbox}',
            f'export VERILOG_FILES_BLACKBOX = {blackbox}','export SYNTH_BLACKBOXES = '+MACRO,
            f'export ADDITIONAL_LEFS = {lef}',f'export ADDITIONAL_LIBS = {views[MACRO+"_TT_1p8V_25C.lib"]}',
            f'export ADDITIONAL_GDS = {views[MACRO+".gds"]}',f'export SDC_FILE = {sdc}',
            'export CORE_UTILIZATION = 30','export CORE_ASPECT_RATIO = 1','export CORE_MARGIN = 20',
            'export PLACE_DENSITY = 0.45','export SYNTH_MOCK_LARGE_MEMORIES = 0',
            f'export SYNTH_MEMORY_MAX_BITS = {largest}','export NUM_CORES = 2','']))
        for path in (blackbox,lef,sdc,config):bindings[str(path)]=sha(path)
        result.update(macro_unit_normalization=audit,remaining_memory_max_bits=largest,config=str(config))
        base=['make','-C',str(orfs/'flow'),f'DESIGN_CONFIG={config}',f'FLOW_VARIANT={variant}',
            f'COURSE_ROOT={ROOT}',f'OPENROAD_EXE={openroad}',f'YOSYS_EXE={yosys}','NUM_CORES=2']
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            code=execute_locked_route(base+['synth'],work/'synth.log',2400,lambda _:heartbeat('SYNTHESIZING_SAME_ROM_CPU'))
            if code:raise RuntimeError('CPU synthesis failed')
            for name in ('1_2_yosys.v','1_2_yosys.sdc','1_synth.odb'):
                if not (result_dir/name).is_file():raise ValueError('missing real synthesis artifact: '+name)
            result.update(synthesis_size((report_dir/'synth_stat.txt').read_text()))
            fresh()
        result.update(status='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS',
            reason='Actual same-ROM mapped CPU synthesized with fixed 10 ns constraints and no memory mocking; placement sizing, timing, routing, macro access and activity/power remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={str(p):sha(p) for folder in (work,result_dir,log_dir,report_dir) if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
