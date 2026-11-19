"""Read actual final CPU/GPU macro access points after a qualified route only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.student_mini_macro_access import parse
from scripts.audit_student_mini_route import check_metrics


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--platform', choices=('cpu', 'gpu'), required=True)
    args = parser.parse_args(); route = args.route.resolve()
    hook = ROOT/'integration/student-mini/report_macro_pin_access.tcl'
    tool = Path('/home/soclab/.local/bin/openroad')
    paths = [Path(__file__), hook, tool, route/'inputs.json', ROOT/'scripts/student_mini_macro_access.py',
             ROOT/'scripts/retry_student_mini_route.py', ROOT/'scripts/audit_student_mini_route.py']
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(dict(platform=args.platform, bindings=bindings), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/platform-macro-access'/key; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', bindings=bindings, platform=args.platform, formal_baseline=False, physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n'); start = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-start))+'\n')
    print(json.dumps(dict(work=str(work), stage='WAITING_FOR_QUALIFIED_ROUTE')), flush=True)
    try:
        packet = route/'completion.json'
        while not packet.is_file():
            heartbeat('WAITING_FOR_QUALIFIED_ROUTE')
            if time.monotonic()-start > 14400: raise TimeoutError('bounded route wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text())
        if (parent['status'] != 'PLATFORM_ROUTE_STAGE_PASS' or parent['platform'] != args.platform
            or parent['macro_power_connected'] is not True or parent['clock_period_ns'] != 10
            or parent['source_freshness_verified'] is not True):
            raise ValueError('same-platform qualified complete 100 MHz route required')
        verify(parent['bindings']); bindings.update(parent['bindings']); bindings[str(packet)] = sha(packet)
        results = Path(parent['result_directory']); logs = Path(parent['metrics_directory'])
        files = [results/'6_final.odb', results/'6_final.def', results/'6_final.sdc', results/'6_final.v',
                 logs/'5_2_route.json', logs/'6_report.json']
        for path in files:
            if parent['artifacts'].get(str(path)) != sha(path): raise ValueError('route artifact changed')
            bindings[str(path)] = sha(path)
        metrics = check_metrics(json.loads(files[-2].read_text()), json.loads(files[-1].read_text()), files[2].read_text())
        if metrics != parent['metrics']: raise ValueError('raw signoff differs from route receipt')
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            command = ['env', f'STUDENT_MINI_ROUTE_ODB={files[0]}', str(tool), '-exit', str(hook)]
            if execute_locked_route(command, work/'access.log', 180, lambda _: heartbeat('READING_FINAL_MACRO_ACCESS')):
                raise ValueError('OpenDB macro access probe failed')
            observation = parse((work/'access.log').read_text(), args.platform)
            result['observation'] = observation
            if observation['status'] != 'MACRO_CONNECTED_SIGNAL_ACCESS_OBSERVED': raise ValueError('connected macro signal has no routed access')
            verify(bindings)
            result.update(status='PLATFORM_MACRO_ACCESS_STAGE_PASS', route_metrics=metrics,
                          reason='Final bound database has access points and routed nets for all connected macro signals; per-load power and whole acceptance remain')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-start
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'PLATFORM_MACRO_ACCESS_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
