"""Bounded CPU/GPU CTS and route from a fresh, nonnegative 100 MHz placement.

Writes a new ORFS variant, never mutates placement evidence, and never issues a
complete physical package. Workload activity, power and protocol gates remain.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.audit_student_mini_route import check_metrics


def nonnegative(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(label + ' must pass before the next physical stage')
    return value


def checked_parent(parent, platform):
    status = {'cpu': 'CPU_PLACEMENT_PREFLIGHT_STAGE_PASS',
              'gpu': 'REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS'}
    if platform not in status or parent.get('status') != status[platform]:
        raise ValueError('matching successful platform placement required')
    if (parent.get('preflight_complete') is not True or parent.get('clock_period_ns') != 10
        or parent.get('threads') != 2 or parent.get('macro_power_connected') is not True):
        raise ValueError('10 ns / 2-thread / real macro power preflight required')
    nonnegative(parent.get('placement_wns_ns'), '100 MHz placement WNS')
    if platform == 'gpu':
        count = parent.get('macro_count')
        if count != 37:
            raise ValueError('frozen 37-macro GPU geometry required')
    else:
        count = parent.get('geometry', {}).get('macro_count')
        if count not in (29, 30):
            raise ValueError('qualified actual CPU macro count required')
    return count


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--platform', choices=('cpu', 'gpu'), required=True)
    args = parser.parse_args(); placement = args.placement.resolve()
    orfs = Path('/home/soclab/src/orfs-clean-aabf2a')
    paths = [Path(__file__), ROOT/'scripts/retry_student_mini_route.py',
             ROOT/'scripts/audit_student_mini_route.py', placement/'inputs.json']
    bindings = {str(p): sha(p) for p in paths}
    identity = hashlib.sha256(json.dumps(dict(bindings=bindings, platform=args.platform), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/platform-route'/identity; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', platform=args.platform, bindings=bindings,
                  formal_baseline=False, physical_evidence_complete=False, clock_period_ns=10, threads=2)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    begin = time.monotonic(); folders = [work]
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-begin))+'\n')
    try:
        heartbeat('WAITING_FOR_PLACEMENT'); print(json.dumps(dict(work=str(work), stage='WAITING_FOR_PLACEMENT')), flush=True)
        packet = placement/'completion.json'
        while not packet.is_file():
            if time.monotonic()-begin > 43200:
                raise TimeoutError('bounded placement wait expired')
            time.sleep(10)
        parent = json.loads(packet.read_text()); count = checked_parent(parent, args.platform)
        verify(parent['bindings']); bindings.update(parent['bindings']); bindings[str(packet)] = sha(packet)
        old_results = Path(parent['result_directory'])
        top = {'cpu': 'cpu_student_mini_physical_top_asic', 'gpu': 'vortex_physical_top'}[args.platform]
        expected_parent = orfs/'flow/results/sky130hd'/top
        if old_results.parent != expected_parent:
            raise ValueError('placement results are not the selected physical top')
        checkpoints = [old_results/name for name in ('3_place.odb', '3_place.sdc')]
        for path in [*checkpoints, Path(parent['config'])]:
            if parent['artifacts'].get(str(path)) != sha(path):
                raise ValueError('placement checkpoint/config changed')
            bindings[str(path)] = sha(path)
        # Use the same actual OpenDB supply assertion as this placement.
        checker_names = ('check-tag-cpu-power.tcl',) if args.platform == 'cpu' and count == 29 else (
            'check_cpu_macro_power.tcl' if args.platform == 'cpu' else 'check_gpu_macro_power.tcl',)
        checkers = [Path(p) for p in bindings if Path(p).name in checker_names]
        if len(checkers) != 1:
            raise ValueError('unique source-bound actual macro supply checker required')
        variant = 'student-mini-' + args.platform + '-route-' + identity[:16]
        results = expected_parent/variant; logs = orfs/'flow/logs/sky130hd'/top/variant
        reports = orfs/'flow/reports/sky130hd'/top/variant; folders += [results, logs, reports]
        config = work/'config.mk'; shutil.copyfile(parent['config'], config); bindings[str(config)] = sha(config)
        result.update(config=str(config), result_directory=str(results), metrics_directory=str(logs),
                      reports_directory=str(reports), macro_count=count, placement=str(placement))
        (work/'qualified-inputs.json').write_text(json.dumps(result, indent=2)+'\n')
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            result['queue_and_parent_wait_seconds'] = time.monotonic()-begin
            for folder in (results, logs, reports):
                folder.mkdir(parents=True, exist_ok=False)
            for path in checkpoints:
                shutil.copyfile(path, results/path.name)
                if sha(results/path.name) != bindings[str(path)]:
                    raise ValueError('copied placement checkpoint differs')
            base = ['make', '-j1', '-C', str(orfs/'flow'), f'DESIGN_CONFIG={config}',
                f'FLOW_VARIANT={variant}', f'COURSE_ROOT={ROOT}', 'NUM_CORES=2',
                'OPENROAD_EXE=/home/soclab/.local/bin/openroad', 'YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys']
            stages = [('do-4_1_cts', 1800), ('do-4_cts', 120), ('do-5_1_grt', 1800),
                      ('do-5_2_route', 7200), ('do-5_3_fillcell', 300), ('do-5_route', 120),
                      ('do-5_route.sdc', 120), ('do-finish', 1800)]
            result['stages'] = []
            for target, timeout in stages:
                start = time.monotonic()
                if execute_locked_route(base+[target], work/(target+'.log'), timeout, lambda _: heartbeat(target)):
                    raise ValueError('physical stage failed: ' + target)
                result['stages'].append(dict(target=target, elapsed_seconds=time.monotonic()-start))
                verify(bindings)
                if target == 'do-5_1_grt':
                    metrics = json.loads((logs/'5_1_grt.json').read_text())
                    result['global_route_wns_ns'] = nonnegative(metrics.get('globalroute__timing__setup__ws'), '100 MHz global-route WNS')
            result['metrics'] = check_metrics(json.loads((logs/'5_2_route.json').read_text()),
                json.loads((logs/'6_report.json').read_text()), (results/'6_final.sdc').read_text())
            for name in ('6_final.def', '6_final.v', '6_final.sdc', '6_final.spef', '6_final.odb'):
                if not (results/name).is_file() or not (results/name).stat().st_size:
                    raise ValueError('missing final physical artifact: ' + name)
            command = ['env', f'STUDENT_MINI_PDN_ODB={results}/6_final.odb',
                       '/home/soclab/.local/bin/openroad', '-exit', str(checkers[0])]
            if execute_locked_route(command, work/'final-macro-power.log', 120, lambda _: heartbeat('FINAL_MACRO_POWER_CHECK')):
                raise ValueError('final actual macro supply assertion failed')
            marker = f'{args.platform.upper()}_MACRO_POWER_CONNECTED macros={count} pins={2*count}'
            if (work/'final-macro-power.log').read_text().splitlines().count(marker) != 1:
                raise ValueError('missing final supply assertion marker')
            verify(bindings)
            result.update(status='PLATFORM_ROUTE_STAGE_PASS', source_freshness_verified=True,
                macro_power_connected=True, reason='Routed 100 MHz timing/DRC/antenna and supply stage only; per-load activity, power, pin access and whole-release qualification remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {str(p): sha(p) for folder in folders if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'PLATFORM_ROUTE_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
