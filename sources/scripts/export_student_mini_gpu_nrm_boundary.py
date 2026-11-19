"""Export an isolated 31-cycle candidate only after its real RTL differential.

Preserves the earlier source-bound producer; creates a checked private producer
instead of mutating an active or historically bound file.
"""
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


def derive(source, root):
    changes = {
        'ROOT=Path(__file__).resolve().parents[1]': 'ROOT=Path(' + repr(str(root)) + ')',
        'from scripts.student_mini_gpu_cut_overlay import CONFIGS,checked_config,create_overlay':
        'from scripts.student_mini_gpu_nrm_overlay import CONFIGS,checked_config,create_overlay',
        "files += [Path(__file__),ROOT/'scripts/student_mini_gpu_cut_overlay.py',":
        "files += [Path(__file__),ROOT/'scripts/export_student_mini_gpu_nrm_boundary.py',ROOT/'scripts/export_student_mini_gpu_cut_boundary.py',ROOT/'scripts/student_mini_gpu_nrm_overlay.py',ROOT/'scripts/student_mini_gpu_cut_overlay.py',",
        "report['status']!='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS'":
        "report['status']!='FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS'",
        "report['latency_after']!=30": "report['latency_after']!=31",
        "'build/student-mini/gpu-cut-boundary'": "'build/student-mini/gpu-nrm-boundary'",
        '17 -> 30 enabled cycles': '17 -> 31 enabled cycles (SRT plus normalization register)',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('normalization export seam changed: ' + old)
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-work', type=Path, required=True)
    args = parser.parse_args()
    original = ROOT/'scripts/export_student_mini_gpu_cut_boundary.py'
    paths = [Path(__file__), original, ROOT/'scripts/student_mini_gpu_nrm_overlay.py',
             args.unit_work.resolve()/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/gpu-nrm-export-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'
    producer.write_text(derive(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, physical_evidence_complete=False,
                  formal_baseline=False, arithmetic_latency=31)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), stage='NRM_EXPORT_QUEUED')), flush=True)
    verify(bindings)
    with (work/'export.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), '--unit-work',
                                str(args.unit_work.resolve())], cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'export.log').read_text().splitlines()
            if line.startswith('{')]
    if rows:
        result['export'] = rows[-1]
    verify(bindings)
    if code == 0 and result.get('export', {}).get('complete') is True:
        result['status'] = 'GPU_NRM_SOURCE_EXPORT_STAGE_PASS'
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'])), flush=True)
    return 0 if result['status'] == 'GPU_NRM_SOURCE_EXPORT_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
