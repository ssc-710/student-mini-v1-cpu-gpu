"""Private 57-cycle replay/physical continuations; never rewrite bound producers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def derive(source, root):
    anchor = '\nROOT = Path(__file__).resolve().parents[1]\n'
    if source.count(anchor) != 1: raise ValueError('continuation root seam changed')
    source = source.replace(anchor, '\nROOT = Path('+repr(str(root))+')\n')
    anchor = 'paths = [Path(__file__),'
    if source.count(anchor) != 1: raise ValueError('continuation source-binding seam changed')
    source = source.replace(anchor, anchor+"ROOT/'scripts/continue_student_mini_gpu_sign_chain.py',")
    # The parents contain no literal hashes or workload data; only the fixed
    # candidate latency, labels and equality gates are changed here.
    source, count = re.subn(r'(?<!\d)31(?!\d)', '57', source)
    if count < 8: raise ValueError('31-cycle pipeline gates missing')
    return source.replace('GPU_NRM_', 'GPU_SIGN_').replace('FPU_NRM_', 'FPU_SIGN_').replace('gpu-nrm-', 'gpu-sign-')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('replay', 'physical'), required=True)
    args, child_args = parser.parse_known_args()
    original = ROOT/'scripts'/('continue_student_mini_gpu_nrm_'+args.phase+'.py')
    bindings = {str(p): sha(p) for p in (Path(__file__), original)}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, arguments=child_args), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini'/('gpu-sign-'+args.phase+'-launch')/identity
    work.mkdir(parents=True, exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(), ROOT))
    bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD', bindings=bindings, arithmetic_latency=57,
                  physical_evidence_complete=False, formal_baseline=False)
    (work/'inputs.json').write_text(json.dumps(dict(result, arguments=child_args), indent=2)+'\n')
    verify(bindings); print(json.dumps(dict(work=str(work), stage='SIGN_'+args.phase.upper()+'_QUEUED')), flush=True)
    with (work/'child.log').open('x') as log:
        code = subprocess.call([sys.executable, str(producer), *child_args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    expected = {'replay': 'GPU_SIGN_REPRESENTATIVE_REPLAY_STAGE_PASS', 'physical': 'GPU_SIGN_PHYSICAL_PREFLIGHT_STAGE_PASS'}[args.phase]
    if code == 0 and result.get('child', {}).get('status') == expected:
        result['status'] = expected
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], child=result.get('child'))), flush=True)
    return 0 if result['status'] == expected else 1


if __name__ == '__main__': raise SystemExit(main())
