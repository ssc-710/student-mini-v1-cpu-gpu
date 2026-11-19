"""Fresh full-GPU export: retain proven multiplier, use proven exact DIV initializer."""
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
from scripts.export_student_mini_gpu_multiplier_boundary import derive as multiplier_export
from scripts.student_mini_gpu_multiplier_overlay import validate_proof


def derive(source, root, proof):
    source = multiplier_export(source, root, proof)
    for old, new in {
        "report['status']!='FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS'": "report['status']!='FPU_INITIAL_DIFFERENCE_STAGE_PASS'",
        "'build/student-mini/gpu-multiplier-boundary'": "'build/student-mini/gpu-initial-difference-boundary'",
        'files += [Path(__file__),': "files += [Path(__file__),ROOT/'scripts/export_student_mini_gpu_initial_difference.py',ROOT/'scripts/student_mini_gpu_initial_difference.py',",
        'integer signed33 product split with unchanged 3 enabled clocks':
            'integer signed33 product split with unchanged 3 enabled clocks; exact initial extended subtraction shared with comparison',
    }.items():
        if source.count(old) != 1: raise ValueError('initial-difference export seam changed')
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-work', type=Path, required=True)
    parser.add_argument('--multiplier-proof', type=Path, required=True)
    args = parser.parse_args(); proof = args.multiplier_proof.resolve(); unit = args.unit_work.resolve()
    report = json.loads((unit/'completion.json').read_text()); verify(report['bindings'])
    if report['status'] != 'FPU_INITIAL_DIFFERENCE_STAGE_PASS': raise ValueError('actual initializer differential required')
    mul = json.loads(proof.read_text()); validate_proof(mul, sha(ROOT/'integration/student-mini/gpu_signed33_mul3.sv')); verify(mul['bindings'])
    original = ROOT/'scripts/export_student_mini_gpu_cut_boundary.py'
    paths = [Path(__file__), original, ROOT/'scripts/export_student_mini_gpu_multiplier_boundary.py',
             ROOT/'scripts/student_mini_gpu_multiplier_overlay.py', proof, unit/'completion.json']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-initial-export-continuation'/key; work.mkdir(parents=True, exist_ok=False)
    private = work/'producer.py'; private.write_text(derive(original.read_text(), ROOT, proof)); bindings[str(private)] = sha(private)
    result = dict(status='HOLD', bindings=bindings, physical_evidence_complete=False, formal_baseline=False,
                  arithmetic_latency=57, integer_multiplier_latency=3, initial_difference_proof=str(unit/'completion.json'),
                  old_counters_reusable=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='INITIAL_DIFFERENCE_WHOLE_EXPORT_QUEUED')), flush=True)
    with (work/'export.log').open('x') as output:
        code = subprocess.call([sys.executable, str(private), '--unit-work', str(unit)], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows = [json.loads(x) for x in (work/'export.log').read_text().splitlines() if x.startswith('{')]
    if rows: result['export'] = rows[-1]
    verify(bindings)
    if not code and result.get('export', {}).get('complete') is True:
        # Same typed multiplier+57-cycle source boundary, with a new hash and proof.
        result['status'] = 'GPU_MULTIPLIER_SOURCE_EXPORT_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('export'))), flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
