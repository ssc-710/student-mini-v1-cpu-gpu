"""Run the original >30k full-bit/flag differential on an isolated 31-cycle candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gpu_normalization_cut import wrapper
from scripts.retry_student_mini_route import verify


def derive(source,root,bench):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        'from scripts.student_mini_gpu_divsqrt_cut import project':'from scripts.student_mini_gpu_normalization_cut import project',
        "wrapper=ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut.sv'":'wrapper=Path('+repr(str(bench))+')',
        "sources=[Path(__file__),ROOT/'scripts/student_mini_gpu_divsqrt_cut.py',":
        "sources=[Path(__file__),ROOT/'scripts/run_student_mini_gpu_normalization_cut.py',ROOT/'scripts/run_student_mini_gpu_divsqrt_cut.py',ROOT/'scripts/student_mini_gpu_normalization_cut.py',ROOT/'scripts/student_mini_gpu_divsqrt_cut.py',",
        "'build/student-mini/gpu-divsqrt-step-cut'":"'build/student-mini/gpu-divsqrt-nrm-cut'",
        'latency_after=30':'latency_after=31',
        'SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS':'FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS',
    }
    for old,new in changes.items():
        expected=2 if old=='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS' else 1
        if source.count(old)!=expected:raise ValueError('FPU proof producer seam changed: '+old)
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--failed-placement',type=Path,required=True)
    args=parser.parse_args();failed=args.failed_placement.resolve();prior=json.loads((failed/'completion.json').read_text())
    if prior['status']!='HOLD' or not prior.get('macro_power_connected') or prior['clock_period_ns']!=10:
        raise ValueError('powered 100 MHz placement HOLD required')
    report=Path(prior['reports_directory'])/'3_global_place.rpt'
    if prior['artifacts'].get(str(report))!=sha(report) or 'fdiv_sqrt_unit.nrm_reg' not in report.read_text():
        raise ValueError('source-bound normalization path report required')
    original=ROOT/'scripts/run_student_mini_gpu_divsqrt_cut.py';bench_original=ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut.sv'
    files=[Path(__file__),original,bench_original,ROOT/'scripts/student_mini_gpu_normalization_cut.py',failed/'completion.json',report]
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-normalization-continuation'/identity;work.mkdir(parents=True,exist_ok=False)
    bench=work/'differential.sv';bench.write_text(wrapper(bench_original.read_text()))
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT,bench))
    bindings.update({str(p):sha(p) for p in (bench,producer)})
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,bindings=bindings,latency=31,
        unchanged_arithmetic=True,old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='NORMALIZATION_DIFFERENTIAL_QUEUED')),flush=True)
    with (work/'differential.log').open('x') as log:
        code=subprocess.call([sys.executable,str(producer),'--project',str(args.project.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(line) for line in (work/'differential.log').read_text().splitlines() if line.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if code==0 and result.get('child',{}).get('status')=='FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS':result['status']='GPU_NORMALIZATION_DIFFERENTIAL_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
