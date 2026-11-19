"""Bounded antenna repair from completed DRT wires, preserving the parent HOLD.

The sole implementation change is three additional ordinary repair iterations.
An isolated byte-bound flow script resumes 5_2_route.odb instead of rerouting the
original global guides. All finishing/extraction checks run again. This producer
never awards a physical package, even when the subprocess finishes successfully.
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
from scripts.retry_student_mini_route import execute_locked_route, verify, TARGETS
from scripts.retry_student_mini_route_registered import acquire_registered

CHECKPOINTS = ('5_2_route.odb', '5_1_grt.sdc', 'route.guide')


def resume_script(original):
    replacements = {
        'load_design 5_1_grt.odb 5_1_grt.sdc': 'load_design 5_2_route.odb 5_1_grt.sdc',
        '![grt::have_routes]': '![grt::have_detailed_routes]',
        '  log_cmd detailed_route {*}$all_args':
            '  check_antennas -report_file $env(REPORTS_DIR)/before_resume_antennas.log',
    }
    for before, after in replacements.items():
        if original.count(before) != 1:
            raise ValueError('unexpected upstream route anchor: '+before)
        original = original.replace(before, after)
    return original


def checked_parent(placement):
    source = json.loads((placement/'inputs.json').read_text())
    parent = json.loads((placement/'completion.json').read_text())
    route = json.loads((placement/'route/completion.json').read_text())
    if source.get('clock_period_ns') != 10 or source.get('threads') != 2:
        raise ValueError('frozen 10 ns / two-thread profile required')
    if parent.get('input_sha256') != placement.name or route.get('parent_input_sha256') != placement.name:
        raise ValueError('route/placement identity differs')
    if route.get('exit_code') != 0 or route.get('source_freshness_verified') is not True:
        raise ValueError('completed source-fresh route required')
    verify(source['files'])
    config = placement/'config.mk'
    if parent['artifacts'].get(str(config)) != sha(config):
        raise ValueError('parent configuration changed')
    results = Path(parent['result_directory']); logs = Path(parent['metrics_directory'])
    checkpoints = {str(results/name): route['artifacts'].get(str(results/name)) for name in CHECKPOINTS}
    raw = {str(logs/name): route['artifacts'].get(str(logs/name)) for name in ('5_2_route.json', '6_report.json')}
    verify(checkpoints); verify(raw)
    detailed = json.loads((logs/'5_2_route.json').read_text())
    finish = json.loads((logs/'6_report.json').read_text())
    for name in ('setup', 'hold'):
        value = finish.get('finish__timing__'+name+'__ws')
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('timing must already be closed for antenna-only experiment')
    if detailed.get('detailedroute__route__drc_errors') != 0:
        raise ValueError('DRC must already be zero')
    counts = [detailed.get('detailedroute__antenna__violating__'+name) for name in ('nets', 'pins')]
    if counts == [0, 0]:
        raise AntennaRepairNotRequired('route already has 0 antenna violations')
    for value in counts:
        if type(value) is not int or not 0 <= value <= 20 or counts == [0, 0]:
            raise ValueError('bounded nonzero antenna failure required')
    return source, parent, route, checkpoints


class AntennaRepairNotRequired(Exception):
    """The completed route has no antenna violation: nothing to repair, the route itself is signed off downstream."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--queue-timeout', type=int, default=43200)
    args = parser.parse_args()
    if not 60 <= args.timeout <= 7200: raise ValueError('bounded repair timeout required')
    placement = args.placement.resolve()
    try:
        source, parent, previous, checkpoints = checked_parent(placement)
    except AntennaRepairNotRequired as skipped:
        # clean-20261014: a route that closes antennas by itself needs no repair step; report the route directory
        # (it stays the sign-off input) and succeed without creating a repair directory.
        print(json.dumps(dict(work=str(placement), status='ANTENNA_REPAIR_NOT_REQUIRED', reason=str(skipped))), flush=True)
        return 0
    orfs = Path(parent['metrics_directory']).parents[4]
    scripts = orfs/'flow/scripts'
    overlay_sources = [p for p in scripts.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    bindings = dict(source['files'], **checkpoints)
    for path in [*overlay_sources, Path(__file__), ROOT/'scripts/retry_student_mini_route.py',
                 ROOT/'scripts/retry_student_mini_route_registered.py', placement/'inputs.json',
                 placement/'completion.json', placement/'config.mk', placement/'route/completion.json']:
        bindings[str(path)] = sha(path)
    inputs = dict(source, files=bindings, stage='additional-antenna-repair-from-completed-drt',
        recovery=dict(parent_input_sha256=placement.name, additional_iterations=3,
                      timeout_seconds=args.timeout, queue_timeout_seconds=args.queue_timeout,
                      unchanged_design_config_sha256=sha(placement/'config.mk')))
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/antenna-resume'/identity; work.mkdir(parents=True, exist_ok=False)
    overlay = work/'flow-scripts'
    for path in overlay_sources:
        destination = overlay/path.relative_to(scripts); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    replacement = overlay/'detail_route.tcl'
    replacement.write_text(resume_script((scripts/'detail_route.tcl').read_text()))
    for path in overlay.rglob('*'):
        if path.is_file(): bindings[str(path)] = sha(path)
    (work/'inputs.json').write_text(json.dumps(inputs, indent=2)+'\n')
    shutil.copyfile(placement/'config.mk', work/'config.mk')
    variant = 'student-mini-antenna-'+identity[:16]
    results = Path(parent['result_directory']).parent/variant
    logs = Path(parent['metrics_directory']).parent/variant
    reports = orfs/'flow/reports/sky130hd'/results.parent.name/variant
    derived = dict(status='HOLD', physical_evidence_complete=False, profile='mini',
        operator=parent['operator'], input_sha256=identity, clock_period_ns=10,
        placement_wns_ns=parent['placement_wns_ns'], placement_reused_from=str(placement),
        reason='Additional antenna repair experiment; no independent signoff yet',
        result_directory=str(results), metrics_directory=str(logs),
        artifacts={str(p): sha(p) for p in (work/'inputs.json', work/'config.mk')})
    (work/'completion.json').write_text(json.dumps(derived, indent=2)+'\n')
    out = work/'route'; out.mkdir()
    tools = {Path(p).name: p for p in bindings if Path(p).name in ('openroad', 'yosys')}
    command = ['make', '-C', str(orfs/'flow'), *TARGETS,
        f'DESIGN_CONFIG={work}/config.mk', f'COURSE_ROOT={ROOT}', f'FLOW_VARIANT={variant}',
        f'OPENROAD_EXE={tools["openroad"]}', f'YOSYS_EXE={tools["yosys"]}',
        f'SCRIPTS_DIR={overlay}', 'MAX_REPAIR_ANTENNAS_ITER_DRT=3', 'NUM_CORES=2']
    (out/'inputs.json').write_text(json.dumps(dict(command=command,
        timeout_seconds=args.timeout, parent_input_sha256=identity,
        bindings={str(p): sha(p) for p in (work/'inputs.json', work/'completion.json', work/'config.mk')}), indent=2)+'\n')
    result = dict(status='HOLD', physical_evidence_complete=False, parent_input_sha256=identity,
        clock_period_ns=10, previous_hold=str(placement/'route/completion.json'))
    started = time.monotonic()
    def heartbeat(stage):
        (out/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    try:
        Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').parent.mkdir(parents=True, exist_ok=True)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            acquire_registered(lock, args.queue_timeout); result['queue_seconds'] = time.monotonic()-started
            verify(bindings)
            for folder in (results, logs, reports): folder.mkdir(parents=True, exist_ok=False)
            for name, digest in checkpoints.items():
                destination = results/Path(name).name; shutil.copyfile(name, destination)
                if sha(destination) != digest: raise ValueError('checkpoint copy differs')
            begin = time.monotonic()
            code = execute_locked_route(command, out/'route.log', args.timeout, heartbeat)
            result.update(exit_code=code, route_elapsed_seconds=time.monotonic()-begin,
                reason='Antenna repair/finish ended; independent signoff remains' if code == 0 else 'Repair failed; inspect bound logs')
            if (logs/'6_report.json').exists(): result['metrics'] = json.loads((logs/'6_report.json').read_text())
            verify(bindings); result['source_freshness_verified'] = True
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    finally:
        result['elapsed_seconds'] = time.monotonic()-started
        heartbeat('FINISHED' if result.get('exit_code') == 0 else 'HOLD')
        result['artifacts'] = {str(p): sha(p) for folder in (out, results, logs, reports)
                               if folder.exists() for p in folder.iterdir() if p.is_file()}
        (out/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(work=str(work), exit_code=result.get('exit_code'), reason=result['reason'])), flush=True)
    return result.get('exit_code', 1)


if __name__ == '__main__': raise SystemExit(main())
