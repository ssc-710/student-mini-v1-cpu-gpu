"""Differentially verify the NR sign/update split against pinned original RTL."""
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
from scripts.run_student_mini_gpu_normalization_cut import derive as normalization_proof


def derive(source, root, bench):
    source = normalization_proof(source, root, bench)
    changes = {
        'from scripts.student_mini_gpu_normalization_cut import project':
        'from scripts.student_mini_gpu_sign_cut import project',
        "sources=[Path(__file__),":
        "sources=[Path(__file__),ROOT/'scripts/run_student_mini_gpu_sign_cut.py',ROOT/'scripts/student_mini_gpu_sign_cut.py',",
        "'build/student-mini/gpu-divsqrt-nrm-cut'": "'build/student-mini/gpu-divsqrt-sign-cut'",
        'latency_after=31': 'latency_after=57',
        'FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS': 'FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS',
    }
    for old, new in changes.items():
        expected = 2 if old == 'FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS' else 1
        if source.count(old) != expected: raise ValueError('sign-cut proof seam changed')
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--failed-placement', type=Path, required=True)
    args = parser.parse_args(); failed = args.failed_placement.resolve()
    packet = failed/'completion.json'; parent = json.loads(packet.read_text())
    if parent['status'] != 'HOLD' or parent.get('macro_power_connected') is not True or parent['clock_period_ns'] != 10:
        raise ValueError('powered 100 MHz failed placement required')
    report = Path(parent['reports_directory'])/'3_global_place.rpt'
    if parent['artifacts'].get(str(report)) != sha(report): raise ValueError('timing report changed')
    text = report.read_text()
    if 'fdiv_sqrt_unit.g_srt[24]' not in text or 'fdiv_sqrt_unit.g_srt[25]' not in text or 'slack (VIOLATED)' not in text:
        raise ValueError('observed single-iteration setup path missing')
    original = ROOT/'scripts/run_student_mini_gpu_divsqrt_cut.py'
    bench_original = ROOT/'tests/rtl/student_mini_gpu_divsqrt_cut.sv'
    paths = [Path(__file__), original, bench_original, packet, report,
             ROOT/'scripts/student_mini_gpu_sign_cut.py', ROOT/'scripts/run_student_mini_gpu_normalization_cut.py',
             ROOT/'scripts/student_mini_gpu_normalization_cut.py']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-sign-cut-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    bench = work/'differential.sv'; bench.write_text(wrapper(bench_original.read_text()))
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT, bench))
    bindings.update({str(p): sha(p) for p in (bench, producer)})
    result = dict(status='HOLD', bindings=bindings, latency=57, unchanged_arithmetic=True,
                  formal_baseline=False, physical_evidence_complete=False, old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='SIGN_UPDATE_DIFFERENTIAL_QUEUED')), flush=True)
    with (work/'differential.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--project', str(args.project.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'differential.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('child', {}).get('status') == 'FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS':
        result['status'] = 'GPU_SIGN_UPDATE_DIFFERENTIAL_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return 0 if result['status'] == 'GPU_SIGN_UPDATE_DIFFERENTIAL_STAGE_PASS' else 1


if __name__ == '__main__': main_code = main(); raise SystemExit(main_code)
