"""Generate a private retimed GPU boundary only after its RTL differential.

No route or promotion occurs here. The original 17-cycle core, counters and
vendor checkout remain unchanged; the new 30-cycle candidate needs new replay.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_cut_overlay import CONFIGS,checked_config,create_overlay
from scripts.retry_student_mini_route import execute_locked_route


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-work',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=43200)
    args=parser.parse_args();unit=args.unit_work.resolve()
    if not 0<=args.wait_seconds<=43200:raise ValueError('bounded parent wait required')
    vendor=Path('/mnt/d/open-soc-ai-labs-vortex');tools=Path('/mnt/d/open-soc-ai-labs-vortex-tools')
    tracked=subprocess.check_output(['git','-C',str(vendor),'ls-files','hw','sw','ci','configure','config.mk.in','VX_config.toml'],text=True).splitlines()
    files=[vendor/name for name in tracked if (vendor/name).is_file()]
    files += [Path(__file__),ROOT/'scripts/student_mini_gpu_cut_overlay.py',ROOT/'scripts/student_mini_gpu_physical_replay_sources.py',
        ROOT/'scripts/retry_student_mini_route.py',ROOT/'scripts/student_mini.py',unit/'inputs.json',
        tools/'sv2v/bin/sv2v',tools/'verilator/bin/verilator',tools/'verilator/bin/verilator_bin']
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,configs=CONFIGS),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-cut-boundary'/identity;work.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    result=dict(status='HOLD',extraction_complete=False,physical_evidence_complete=False,formal_baseline=False,
        full_gpu_equivalence=False,bindings=bindings,configs=CONFIGS,perf_enable=True,entity_gpu_required=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('retimed GPU export input changed')
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def execute(command,name,timeout,cwd):
        wrapped=['bash','-c','ulimit -c 0; cd -- "$1" || exit; shift; exec "$@"','gpu-cut',str(cwd),*command]
        if execute_locked_route(wrapped,work/(name+'.log'),timeout,lambda _:heartbeat(name)):
            raise RuntimeError(name+' failed')
    try:
        heartbeat('WAITING_FOR_SRT_DIFFERENTIAL');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SRT_DIFFERENTIAL')),flush=True)
        while not (unit/'completion.json').exists():
            if time.monotonic()-started>args.wait_seconds:raise TimeoutError('SRT differential did not finish')
            time.sleep(10)
        report=json.loads((unit/'completion.json').read_text())
        if (report['status']!='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS' or report['latency_before']!=17
                or report['latency_after']!=30 or report['records']<=30000
                or set(report['seeds'])!={str(i) for i in range(1,11)}):
            raise ValueError('SRT differential not complete')
        bindings.update(report['bindings']);bindings[str(unit/'completion.json')]=sha(unit/'completion.json')
        for name,digest in report['artifacts'].items():
            path=unit/name
            if sha(path)!=digest:raise ValueError('SRT witness changed')
            bindings[str(path)]=digest
        overlay=work/'source';derived=create_overlay(vendor,overlay,(unit/'VX_fdivsqrt_step_cut.sv').read_text())
        for name in derived:bindings[str(overlay/name)]=sha(overlay/name)
        (work/'source-derivation.json').write_text(json.dumps(dict(files=derived,
            change='F32 SRT register boundary only: 17 -> 30 enabled cycles; all core/cache/thread geometry unchanged',
            vendor_modified=False,old_counters_reusable=False),indent=2)+'\n')
        os.environ.update(CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',MAKEFLAGS='-j2')
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            build=work/'vortex-build';build.mkdir()
            execute([str(overlay/'configure'),'--xlen=32','--tooldir='+str(tools),'--osversion=ubuntu/focal',
                '--prefix='+str(work/'install')],'configure',120,build)
            if str(overlay) not in (build/'config.mk').read_text():raise ValueError('private source was not selected')
            resolved=[]
            for label,flags in [('sim','-DSIMULATION -DSV_DPI'),('asic','-DSYNTHESIS -DASIC')]:
                resolver=[sys.executable,str(overlay/'ci/gen_config.py'),'--config',str(overlay/'VX_config.toml'),
                    '--format','cpp','--resolved','--cflags='+CONFIGS+' '+flags]
                text=subprocess.check_output(resolver,text=True,timeout=30)
                resolved.append(checked_config(text));(work/(label+'-resolved.h')).write_text(text)
            keys=[key for key in resolved[0] if key.startswith(('VX_CFG_F','VX_CFG_NUM_','VX_CFG_ICACHE_','VX_CFG_DCACHE_'))]
            if any(resolved[0][key]!=resolved[1].get(key) for key in keys):raise ValueError('simulation/ASIC configuration differs')
            execute(['make','-j2','-C',str(build/'hw/syn/yosys'),'gen-sources','PERF=1','CONFIGS='+CONFIGS,
                'PREFIX='+str(work/'mini'),'SV2V='+str(tools/'sv2v/bin/sv2v'),
                'VERILATOR='+str(tools/'verilator/bin/verilator')],'generate',900,work)
            project=work/'mini_Vortex/project.v'
            if not project.is_file() or not project.stat().st_size:raise ValueError('missing full GPU ASIC source')
            fresh();result.update(extraction_complete=True,project_sha256=sha(project),
                reason='Retimed STD/PERF source generated after isolated numerical differential; whole GPU/memory/protocol/timing verification still mandatory')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat('EXTRACTION_STAGE_COMPLETE' if result['extraction_complete'] else 'HOLD')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file() and not p.is_symlink()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),complete=result['extraction_complete'],reason=result['reason'])),flush=True)
    return 0 if result['extraction_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
