"""Source-bound bit/flag differential for the actual failed DIV initialization path."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.student_mini_gpu_sign_cut import wrapper
from scripts.run_student_mini_gpu_sign_cut import derive as sign_proof


def derive(source, root, bench):
    source = sign_proof(source, root, bench)
    for old, new in {
        'from scripts.student_mini_gpu_sign_cut import project': 'from scripts.student_mini_gpu_initial_difference import project',
        'sources=[Path(__file__),': "sources=[Path(__file__),ROOT/'scripts/run_student_mini_gpu_initial_difference.py',ROOT/'scripts/student_mini_gpu_initial_difference.py',",
        "'build/student-mini/gpu-divsqrt-sign-cut'": "'build/student-mini/gpu-divsqrt-initial-difference'",
        'FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS': 'FPU_INITIAL_DIFFERENCE_STAGE_PASS',
    }.items():
        expected = 2 if old == 'FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS' else 1
        if source.count(old) != expected: raise ValueError('initial-difference producer seam changed')
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args(); packet = args.placement.resolve()/'completion.json'
    parent = json.loads(packet.read_text()); verify(parent['bindings'])
    report = Path(parent['reports_directory'])/'3_resizer.rpt'
    if (parent['status'] != 'HOLD' or parent['clock_period_ns'] != 10
        or parent['artifacts'].get(str(report)) != sha(report)):
        raise ValueError('source-bound 100 MHz failed placement required')
    text = report.read_text()
    if ('fdiv_sqrt_unit.pre_reg.' not in text or 'fdiv_sqrt_unit.ini_reg.' not in text
        or 'slack (VIOLATED)' not in text):
        raise ValueError('observed initialization path not found')
    original = ROOT/'scripts/run_student_mini_gpu_divsqrt_cut.py'
    bench_original = ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut.sv'
    paths = [Path(__file__), packet, report, original, bench_original,
             ROOT/'scripts/student_mini_gpu_initial_difference.py', ROOT/'scripts/run_student_mini_gpu_sign_cut.py',
             ROOT/'scripts/student_mini_gpu_sign_cut.py']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-initial-difference-launch'/key; work.mkdir(parents=True, exist_ok=False)
    bench = work/'differential.sv'; bench.write_text(wrapper(bench_original.read_text()))
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT, bench))
    bindings.update({str(p): sha(p) for p in (bench, producer)})
    result = dict(status='HOLD', bindings=bindings, formal_baseline=False, physical_evidence_complete=False,
                  unchanged_precision=True, latency=57, whole_gpu_pass=False, old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='INITIAL_DIFFERENCE_QUEUED')), flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable, str(producer), '--project', str(args.project.resolve())],
                               cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child', {}).get('status') == 'FPU_INITIAL_DIFFERENCE_STAGE_PASS':
        result['status'] = 'GPU_INITIAL_DIFFERENCE_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
