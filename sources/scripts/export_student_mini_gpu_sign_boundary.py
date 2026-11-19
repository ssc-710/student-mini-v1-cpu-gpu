"""Export the sign/update candidate only after the actual full-bit differential."""
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
from scripts.export_student_mini_gpu_nrm_boundary import derive as nrm_export


def derive(source, root):
    text = nrm_export(source, root)
    changes = {
        'from scripts.student_mini_gpu_nrm_overlay import CONFIGS,checked_config,create_overlay':
        'from scripts.student_mini_gpu_sign_overlay import CONFIGS,checked_config,create_overlay',
        'files += [Path(__file__),':
        "files += [Path(__file__),ROOT/'scripts/export_student_mini_gpu_sign_boundary.py',ROOT/'scripts/student_mini_gpu_sign_overlay.py',",
        "report['status']!='FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS'": "report['status']!='FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS'",
        "report['latency_after']!=31": "report['latency_after']!=57",
        "'build/student-mini/gpu-nrm-boundary'": "'build/student-mini/gpu-sign-boundary'",
        '17 -> 31 enabled cycles (SRT plus normalization register)':
        '17 -> 57 enabled cycles (NR sign/update and normalization registers)',
    }
    for old, new in changes.items():
        if text.count(old) != 1: raise ValueError('sign/update export seam changed: '+old)
        text = text.replace(old, new)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-work', type=Path, required=True)
    args = parser.parse_args(); original = ROOT/'scripts/export_student_mini_gpu_cut_boundary.py'
    paths = [Path(__file__), original, ROOT/'scripts/export_student_mini_gpu_nrm_boundary.py',
             ROOT/'scripts/student_mini_gpu_sign_overlay.py', ROOT/'scripts/student_mini_gpu_nrm_overlay.py',
             args.unit_work.resolve()/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-sign-export-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, physical_evidence_complete=False,
                  formal_baseline=False, arithmetic_latency=57)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work), stage='SIGN_EXPORT_AFTER_PROOF_QUEUED')), flush=True)
    with (work/'export.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--unit-work', str(args.unit_work.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'export.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['export'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('export', {}).get('complete') is True:
        result['status'] = 'GPU_SIGN_SOURCE_EXPORT_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'])), flush=True)
    return 0 if result['status'] == 'GPU_SIGN_SOURCE_EXPORT_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
