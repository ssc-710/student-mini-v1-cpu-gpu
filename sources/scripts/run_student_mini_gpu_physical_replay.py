"""Replay three real kernels through mapped GPU core plus physical adapters.

Uses an isolated simulator source overlay, preserves active vendor/counter builds,
and services OpenRAM delay events at 100 MHz. This is a representative functional
stage, not all-case coverage, post-route signoff, or formal baseline acceptance.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route
from scripts.assemble_student_mini_gpu_results import parse
from scripts.student_mini_gpu_physical_replay_sources import rename_modules,connect_shim,timing_processor,quiet_macro,overlay_configure
from scripts.student_mini_gpu_constant_calls import lower_scheduler_constants


def overlay_directory(source,target,private_names):
    target.mkdir()
    for path in source.iterdir():
        if path.name=='.git' or path.name in private_names:continue
        (target/path.name).symlink_to(path,target_is_directory=path.is_dir())


def checked_output(text,ordinal,functional):
    lines=text.splitlines()
    actual=[line for line in lines if line.startswith('STUDENT_GPU ')]
    if len(actual)!=1 or not actual[0].startswith(f'STUDENT_GPU ordinal={ordinal} '):
        raise ValueError('wrong physical-boundary output ordinal')
    if lines.count(f'STUDENT_GPU_COMPLETE start={ordinal} count=1')!=1:raise ValueError('missing kernel completion')
    canonical=actual[0].replace(f'ordinal={ordinal} ','ordinal=0 ',1)+'\nSTUDENT_GPU_COMPLETE start=0 count=1\n'
    observed=parse(canonical,1)[0]
    for field in ('actual_status','actual_bits','selected','primitive'):
        if observed[field]!=functional['observation'][field]:raise ValueError('full output differs: '+field)
    if functional['observation']['numeric_match'] is not True:raise ValueError('functional reference does not match golden')
    perf=re.findall(r'^PERF: instrs=(\d+), cycles=(\d+), IPC=[\d.]+$',text,re.M)
    if len(perf)!=1 or min(map(int,perf[0]))<=0:raise ValueError('missing physical-boundary hardware counts')
    return dict(actual=observed,instructions=int(perf[0][0]),cycles=int(perf[0][1]))


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('boundary','functional-parent','functional-report'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    boundary=args.boundary.resolve();parent=args.functional_parent.resolve()
    completed=json.loads((boundary/'completion.json').read_text())
    manifest=json.loads((parent/'manifest.json').read_text())
    report=json.loads(args.functional_report.read_text())
    if completed.get('boundary_complete') is not True or report.get('platform')!='gpu':raise ValueError('qualified inputs required')
    project=boundary/'project-banked.v'
    if completed['artifacts'].get(project.name)!=sha(project):raise ValueError('mapped RTL changed')
    staged_path=ROOT/'grading/evidence/vortex-physical/staged-openram-banked-manifest.json'
    staged=json.loads(staged_path.read_text())
    models=[Path(row['path']) for macro in staged['macros'] for name,row in macro['artifacts'].items() if name.endswith('.v')]
    source=Path('/mnt/d/open-soc-ai-labs-vortex');tools=Path('/mnt/d/open-soc-ai-labs-vortex-tools')
    selected=[next(row for row in report['records'] if row['case']['operator']==op and row['seed']==1) for op in ('p1','p2','p3')]
    bindings=dict(completed['bindings']);bindings.update(manifest['bindings'])
    paths=[Path(__file__),ROOT/'scripts/student_mini_gpu_physical_replay_sources.py',ROOT/'scripts/student_mini_gpu_constant_calls.py',ROOT/'scripts/retry_student_mini_route.py',
        ROOT/'scripts/assemble_student_mini_gpu_results.py',boundary/'completion.json',project,staged_path,*models,
        parent/'manifest.json',args.functional_report.resolve(),ROOT/'tests/rtl/student_mini_gpu_physical_bridge.sv',
        ROOT/'shared/rtl/vortex_physical_top.sv',ROOT/'shared/rtl/vortex_command_adapter.sv',
        ROOT/'shared/rtl/vortex_memory_adapter.sv',ROOT/'shared/rtl/vortex_banked_large_sram_wrappers.sv',
        tools/'verilator/bin/verilator',tools/'verilator/bin/verilator_bin']
    paths.extend(source/name for name in subprocess.check_output(['git','-C',str(source),'ls-files','configure','hw','sim','sw','ci'],text=True).splitlines() if (source/name).is_file())
    paths.extend(parent/name for name in ('Makefile','student_mini.cu','device_compat.cc','common.h'))
    bindings.update({str(p):sha(p) for p in paths})
    plan=dict(bindings=bindings,ordinals=[r['observation']['ordinal'] for r in selected],clock_period_ns=10,
        scope='Three representative full-output comparisons through actual SRAM models and physical adapters',
        data_source='Frozen input image and real compiled kernels; no golden outputs in the DUT')
    identity=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-physical-replay'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(plan,indent=2)+'\n')
    overlay=work/'source';overlay_directory(source,overlay,{'sim','configure'})
    shutil.copy2(source/'configure',overlay/'configure')
    (overlay/'configure').write_text(overlay_configure((source/'configure').read_text()))
    overlay_directory(source/'sim',overlay/'sim',{'rtlsim'})
    private=overlay/'sim/rtlsim';overlay_directory(source/'sim/rtlsim',private,{'Makefile','processor.cpp','rtlsim_shim.sv'})
    transformed,mapping=rename_modules(lower_scheduler_constants(project.read_text()))
    (private/'physical-project.v').write_text(transformed)
    top,_=rename_modules((ROOT/'shared/rtl/vortex_physical_top.sv').read_text(),mapping)
    (private/'physical-top.sv').write_text(top)
    (private/'processor.cpp').write_text(timing_processor((source/'sim/rtlsim/processor.cpp').read_text()))
    (private/'rtlsim_shim.sv').write_text(connect_shim((source/'sim/rtlsim/rtlsim_shim.sv').read_text()))
    extra=[private/'physical-project.v',private/'physical-top.sv',ROOT/'tests/rtl/student_mini_gpu_physical_bridge.sv']
    extra.extend(ROOT/'shared/rtl'/name for name in ('vortex_command_adapter.sv','vortex_memory_adapter.sv','vortex_banked_large_sram_wrappers.sv'))
    for model in models:
        output=private/model.name;output.write_text(quiet_macro(model.read_text()));extra.append(output)
    makefile=(source/'sim/rtlsim/Makefile').read_text()
    makefile+='\n# Independent mapped physical-boundary replay.\nVL_FLAGS += --timing --timescale-override 1ns/1ps '+' '.join(map(str,extra))+'\nCXXFLAGS := $(filter-out -std=c++17,$(CXXFLAGS)) -std=c++20\n'
    (private/'Makefile').write_text(makefile)
    for name in ('student_mini.cu','device_compat.cc','common.h'):shutil.copy2(parent/name,work/name)
    (work/'Makefile').write_text((parent/'Makefile').read_text().replace(str(parent),str(work)).replace('CONFIGS := ','CONFIGS := -DVX_CFG_FPU_TYPE=STD '))
    derived={str(p.relative_to(work)):sha(p) for p in private.iterdir() if p.is_file() and not p.is_symlink()}
    derived['source/configure']=sha(overlay/'configure')
    (work/'source-derivation.json').write_text(json.dumps(dict(module_alpha_renaming=mapping,files=derived,
        constant_call_change='Two scheduler localparam calls lowered to identical 1-bit constants; checked frozen function bodies; runtime calls unchanged',
        configure_change='find -L follows private overlay source-directory symlinks; upstream vendor unchanged',
        macro_change='VERBOSE 1 to 0 only; DELAY and T_HOLD preserved',timing='1 ps simulation unit; 5000 ps half-cycle; all scheduled delay events serviced'),indent=2)+'\n')
    os.environ.update(CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',CHIP_BE='opencl',
        HIP_CLANG_PATH=str(tools/'llvm-vortex/bin'),MAKEFLAGS='-j2',THREADS='2',VORTEX_PROFILING='0')
    os.environ['PATH']=str(tools/'verilator/bin')+':'+os.environ['PATH']
    started=time.monotonic();result=dict(status='HOLD',target_run_complete=False,formal_baseline=False,
        all_case_coverage=False,post_route_simulation=False,performance_eligible=False,records=[],bindings=bindings)
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('physical replay source changed')
        if any(sha(work/p)!=value for p,value in derived.items()):raise ValueError('derived simulator source changed')
    def execute(command,name,timeout):
        heartbeat(name.upper())
        if execute_locked_route(command,work/(name+'.log'),timeout,lambda _:heartbeat(name.upper())):
            raise RuntimeError(name+' failed; inspect isolated log')
    try:
        fresh()
        print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            build=work/'vortex-build';build.mkdir()
            execute(['bash','-c','cd -- "$1" && shift && exec "$@"','physical-replay',str(build),str(overlay/'configure'),
                '--xlen=32','--tooldir='+str(tools),'--osversion=ubuntu/focal','--prefix='+str(work/'install')],'configure',120)
            config=(build/'config.mk').read_text()
            if str(overlay) not in config:raise ValueError('private source overlay not selected by configure')
            configs='-DVX_CFG_FPU_TYPE=STD -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4'
            execute(['make','-j2','-C',str(build/'sw/kernel'),'CONFIGS='+configs,'THREADS=2'],'kernel',600)
            execute(['make','-j2','-C',str(work),'all','PERF=1','THREADS=2'],'compile',900)
            for functional in selected:
                ordinal=functional['observation']['ordinal'];name='case-'+str(ordinal)
                execute(['make','-j2','-C',str(work),'run-rtlsim','PERF=1','THREADS=2',
                    'OPTS='+manifest['input_directory']+'/inputs.bin '+str(ordinal)+' 1'],name,2400)
                observation=checked_output((work/(name+'.log')).read_text(),ordinal,functional)
                result['records'].append(dict(ordinal=ordinal,case_id=functional['case']['id'],seed=functional['seed'],
                    operator=functional['case']['operator'],**observation))
            fresh();result.update(status='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS',target_run_complete=True,
                reason='Three actual kernels match full outputs through SRAM and physical adapters; full coverage and signoff remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    artifacts=[p for p in work.iterdir() if p.is_file()]
    artifacts+=list((work/'vortex-build/sw/runtime').glob('*.so'))+list((work/'vortex-build/sw/runtime').glob('*.stamp'))
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in artifacts}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['target_run_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
