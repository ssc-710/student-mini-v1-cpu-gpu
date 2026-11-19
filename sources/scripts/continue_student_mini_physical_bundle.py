"""Wait for raw PDK/power proofs, then assemble and independently verify a bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.assemble_student_mini_physical import assemble
from scripts.verify_student_mini_physical_bundle import verify


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('placement', 'activity', 'power', 'pdk-audit'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=24000)
    args = parser.parse_args()
    paths = [Path(__file__), ROOT/'scripts/assemble_student_mini_physical.py', ROOT/'scripts/verify_student_mini_physical_bundle.py',
        ROOT/'scripts/audit_student_mini_route.py', ROOT/'scripts/audit_student_mini_pdk.py',
        ROOT/'scripts/run_student_mini_sourcebound_power.py', ROOT/'scripts/run_student_mini_p3_activity.py',
        ROOT/'scripts/run_student_mini_attention_activity.py', ROOT/'scripts/collect_openroad_activity_power.py',
        ROOT/'scripts/validate_student_mini_physical.py']
    bindings = {str(p): sha(p) for p in paths}
    config = {key: str(getattr(args, key).resolve()) for key in ('placement', 'activity', 'power', 'pdk_audit')}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, inputs=config), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/physical-bundle-continuation'/identity
    work.mkdir(parents=True, exist_ok=False)
    report = dict(status='HOLD', physical_evidence_complete=False, bindings=bindings, inputs=config,
                  formal_baseline=False, release_complete=False)
    started = time.monotonic()
    try:
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_RAW_SIGNOFF')), flush=True)
        while not all(getattr(args, key).is_file() for key in ('power', 'pdk_audit')):
            if time.monotonic()-started > args.wait_seconds: raise TimeoutError('raw signoff did not complete in the bounded wait')
            time.sleep(10)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != digest for p, digest in bindings.items()): raise ValueError('bundle validator source changed while waiting')
            profile = assemble(args.placement, args.activity, args.power, args.pdk_audit, ROOT/'build/student-mini/physical-packages')
            result = verify(profile, sha(profile))
            if any(sha(Path(p)) != digest for p, digest in bindings.items()): raise ValueError('bundle validator source changed during verification')
            report.update(result, profile=str(profile), reason='Physical bundle assembled and offline-verified; all other release gates remain independent')
    except Exception as error:
        report.update(status='HOLD', physical_evidence_complete=False, reason=f'{type(error).__name__}: {error}')
    report['elapsed_seconds'] = time.monotonic()-started
    (work/'completion.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=report['status'], reason=report['reason'])), flush=True)
    return 0 if report['physical_evidence_complete'] else 1


if __name__ == '__main__': raise SystemExit(main())
