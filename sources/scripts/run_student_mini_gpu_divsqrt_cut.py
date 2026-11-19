"""Isolated, source-bound F32 SRT retiming differential; no vendor modification."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_divsqrt_cut import project
from scripts.retry_student_mini_route import execute_locked_route


def compiler_command(tool,config,rtl,cut,wrapper,driver,work,*,lint_only=False):
    action=['--lint-only'] if lint_only else ['--cc','--exe','--build','-j','2','--Mdir',str(work/'obj'),'-CFLAGS','-O2']
    return [str(tool),*action,'--assert','--top-module','student_mini_gpu_divsqrt_cut','-Wno-fatal','-DVX_CFG_XLEN=32',
        '-I'+str(config.parent),'-I'+str(rtl),'-I'+str(rtl/'libs'),'-I'+str(rtl/'fpu'),
        '-y',str(rtl/'libs'),'-y',str(rtl/'fpu'),str(rtl/'VX_gpu_pkg.sv'),str(rtl/'fpu/VX_fpu_pkg.sv'),
        str(rtl/'fpu/VX_fdivsqrt_unit.sv'),str(cut),str(wrapper),*([] if lint_only else [str(driver)])]


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    args=parser.parse_args();gpu=args.project.resolve()
    vendor=Path('/mnt/d/open-soc-ai-labs-vortex');rtl=vendor/'hw/rtl'
    original=rtl/'fpu/VX_fdivsqrt_unit.sv'
    if sha(original)!='15c12fd00e9fabd8abde8361aead816b3ed358625d4d2ef4cf065f449889713f':
        raise ValueError('pinned SRT source differs')
    config=gpu/'vortex-build/hw/VX_config.vh'
    tool=Path('/home/soclab/tools/verilator-5.040/bin/verilator')
    wrapper=ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut.sv'
    driver=ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut_main.cpp'
    sources=[Path(__file__),ROOT/'scripts/student_mini_gpu_divsqrt_cut.py',ROOT/'scripts/student_mini.py',
        ROOT/'scripts/retry_student_mini_route.py',config,tool,tool.with_name('verilator_bin'),wrapper,driver]
    sources += [p for p in rtl.rglob('*') if p.is_file() and p.suffix in ('.sv','.vh')]
    bindings={str(p):sha(p) for p in sources}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-divsqrt-step-cut'/identity;work.mkdir(parents=True,exist_ok=False)
    cut=work/'VX_fdivsqrt_step_cut.sv';cut.write_text(project(original.read_text()))
    bindings[str(cut)]=sha(cut)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_complete=False,
        full_gpu_equivalence=False,old_counters_reusable=False,latency_before=17,latency_after=30,
        scope='F32 divide/sqrt result bits and flags versus pinned RTL, with stalls/bubbles/reset; not IEEE proof or whole GPU acceptance')
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def fresh():
        if any(sha(Path(p))!=value for p,value in bindings.items()):raise ValueError('SRT input changed')
    command=compiler_command(tool,config,rtl,cut,wrapper,driver,work)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings,command=command),indent=2)+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            result['queue_seconds']=time.monotonic()-started
            code=execute_locked_route(command,work/'compile.log',600,lambda _:heartbeat('COMPILING_ISOLATED_SRT'))
            if code:raise RuntimeError('SRT compile failed')
            binary=work/'obj/Vstudent_mini_gpu_divsqrt_cut';bindings[str(binary)]=sha(binary)
            code=execute_locked_route([str(binary)],work/'transactions.jsonl',300,lambda _:heartbeat('EXECUTING_DIFFERENTIAL'))
            if code:raise RuntimeError('SRT differential failed')
            records=[];completed=[]
            for line in (work/'transactions.jsonl').read_text().splitlines():
                if line.startswith('{'):records.append(json.loads(line))
                elif line.startswith('DIVSQRT_STEP_CUT_COMPLETE'):completed.append(line)
            if len(completed)!=1 or len(records)<=30000:raise ValueError('incomplete SRT coverage')
            counts={seed:sum(r['seed']==seed for r in records) for seed in range(1,11)}
            if min(counts.values())<=3000:raise ValueError('missing seed differential coverage')
            if any(r['match'] is not True or r['xor_delta']!=0 or r['actual_bits']!=r['expected_bits']
                   or r['actual_flags']!=r['expected_flags'] for r in records):raise ValueError('SRT bit mismatch')
            if {(r['sqrt'],r['frm']) for r in records}!={(s,m) for s in (0,1) for m in range(5)}:
                raise ValueError('operation or rounding-mode coverage incomplete')
            fresh();result.update(status='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS',records=len(records),seeds=counts,
                reason='Private timing candidate numerically matches original F32 RTL; synthesis/timing and full GPU replay are mandatory before adoption')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
