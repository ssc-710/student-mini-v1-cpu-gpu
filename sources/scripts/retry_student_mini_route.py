"""Retry a timed-out route in a new variant, never overwrite the original HOLD.

Only the wall-time budget changes. The bound global-route checkpoint, design
configuration, tools, clock and routing recipe are preserved. This is a route
producer, not a physical-package or baseline evaluator.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

CHECKPOINT_FILES = ('5_1_grt.odb', '5_1_grt.sdc', 'route.guide')
TARGETS = ('do-5_2_route', 'do-5_3_fillcell', 'do-5_route', 'do-5_route.sdc', 'do-finish')


def execute_locked_route(command, log_path, timeout, heartbeat):
    """Caller owns the queue lock until this function has reaped its tool tree."""
    child = None
    begin = time.monotonic()
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise InterruptedError('route termination requested')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with log_path.open('x') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while child.poll() is None:
                heartbeat('ROUTING')
                if time.monotonic()-begin > timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(10)
        return child.returncode
    finally:
        if child and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # make may exit before OpenROAD. A second group signal guarantees
            # descendants in this task's session cannot retain the EDA memory.
            try:
                os.killpg(child.pid, getattr(signal, 'SIGKILL', 9))
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        signal.signal(signal.SIGTERM, previous)


def verify(bindings):
    if not bindings:
        raise ValueError('empty source/checkpoint bindings')
    for name, digest in bindings.items():
        path = Path(name)
        if not path.is_file() or sha(path) != digest:
            raise ValueError('source/checkpoint changed: '+name)


def checked_parent(placement, timeout):
    if type(timeout) is not int or not 7200 < timeout <= 14400:
        raise ValueError('retry timeout must be bounded to (7200, 14400] seconds')
    parent = json.loads((placement/'completion.json').read_text())
    source = json.loads((placement/'inputs.json').read_text())
    route = json.loads((placement/'route/completion.json').read_text())
    wns = parent.get('placement_wns_ns')
    if type(wns) not in (int, float) or not math.isfinite(wns) or wns < 0:
        raise ValueError('nonnegative placement WNS required')
    if source.get('clock_period_ns') != 10 or source.get('threads') != 2:
        raise ValueError('original 10 ns / two-thread profile required')
    if parent.get('input_sha256') != placement.name or route.get('parent_input_sha256') != placement.name:
        raise ValueError('placement/route parent differs')
    if route.get('status') != 'HOLD' or not route.get('reason', '').startswith('TimeoutExpired:'):
        raise ValueError('only an explicitly timed-out HOLD can use this retry')
    verify(source['files'])
    config = placement/'config.mk'
    if parent['artifacts'].get(str(config)) != sha(config):
        raise ValueError('original design configuration changed')
    checkpoint = {str(Path(parent['result_directory'])/name):
                  route['artifacts'].get(str(Path(parent['result_directory'])/name))
                  for name in CHECKPOINT_FILES}
    verify(checkpoint)
    return source, parent, route, checkpoint


def prepare(placement, timeout, output_root):
    source, parent, route, checkpoint = checked_parent(placement, timeout)
    bindings = dict(source['files'])
    bindings.update(checkpoint)
    for path in (Path(__file__), placement/'inputs.json', placement/'completion.json',
                 placement/'config.mk', placement/'route/completion.json'):
        bindings[str(path)] = sha(path)
    inputs = dict(source, files=bindings, stage='route-retry-from-global-route',
        recovery=dict(parent_input_sha256=placement.name, previous_reason=route['reason'],
                      timeout_seconds=timeout, targets=list(TARGETS),
                      unchanged_design_config_sha256=sha(placement/'config.mk')))
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    work = output_root/identity
    work.mkdir(parents=True, exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs, indent=2)+'\n')
    shutil.copyfile(placement/'config.mk', work/'config.mk')
    variant = 'student-mini-retry-'+identity[:16]
    result_dir = Path(parent['result_directory']).parent/variant
    log_dir = Path(parent['metrics_directory']).parent/variant
    derived = dict(status='HOLD', physical_evidence_complete=False, profile='mini',
        operator=parent['operator'], input_sha256=identity, clock_period_ns=10.,
        placement_wns_ns=parent['placement_wns_ns'], placement_reused_from=str(placement),
        reason='Original placement retained; independent route retry pending',
        result_directory=str(result_dir), metrics_directory=str(log_dir),
        artifacts={str(p): sha(p) for p in (work/'inputs.json', work/'config.mk')})
    (work/'completion.json').write_text(json.dumps(derived, indent=2)+'\n')
    return work, inputs, result_dir, log_dir, checkpoint


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=10800)
    parser.add_argument('--queue-timeout', type=int, default=43200)
    args = parser.parse_args()
    if not 60 <= args.queue_timeout <= 43200:
        raise ValueError('queue wait must be bounded')
    work, inputs, result_dir, log_dir, checkpoint = prepare(args.placement.resolve(),
        args.timeout, ROOT/'build/student-mini/physical-retries')
    out = work/'route'
    out.mkdir()
    orfs = log_dir.parents[4]
    report_dir = orfs/'flow/reports/sky130hd'/result_dir.parent.name/result_dir.name
    tools = {Path(p).name: p for p in inputs['files'] if Path(p).name in ('openroad', 'yosys')}
    command = ['make', '-C', str(orfs/'flow'), *TARGETS,
        f'DESIGN_CONFIG={work}/config.mk', f'COURSE_ROOT={ROOT}', f'FLOW_VARIANT={result_dir.name}',
        f'OPENROAD_EXE={tools["openroad"]}', f'YOSYS_EXE={tools["yosys"]}', 'NUM_CORES=2']
    (out/'inputs.json').write_text(json.dumps(dict(command=command,
        timeout_seconds=args.timeout, parent_input_sha256=work.name,
        bindings={str(p): sha(p) for p in (work/'inputs.json', work/'completion.json', work/'config.mk')}), indent=2)+'\n')
    started = time.monotonic()
    result = dict(status='HOLD', physical_evidence_complete=False, parent_input_sha256=work.name,
                  clock_period_ns=10., previous_hold=str(args.placement.resolve()/'route/completion.json'))
    def heartbeat(stage):
        (out/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work), status='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            while True:
                heartbeat('WAITING_FOR_SERIAL_QUEUE')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic()-started > args.queue_timeout:
                        raise TimeoutError('serial queue wait expired')
                    time.sleep(10)
            verify(inputs['files'])
            for directory in (result_dir, log_dir, report_dir):
                directory.mkdir(parents=True, exist_ok=False)
            for path, digest in checkpoint.items():
                target = result_dir/Path(path).name
                shutil.copyfile(path, target)
                if sha(target) != digest:
                    raise ValueError('checkpoint copy differs')
            begin = time.monotonic()
            print(json.dumps(dict(work=str(work), status='ROUTING')), flush=True)
            code = execute_locked_route(command, out/'route.log', args.timeout, heartbeat)
            result['exit_code'] = code
            result['route_elapsed_seconds'] = time.monotonic()-begin
            result['reason'] = 'Route finished; raw signoff and workload power still require validation' if code == 0 else 'Route failed; inspect bound log'
            metrics = log_dir/'6_report.json'
            if metrics.is_file():
                result['metrics'] = json.loads(metrics.read_text())
            verify(inputs['files'])
            result['source_freshness_verified'] = True
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    finally:
        result['elapsed_seconds'] = time.monotonic()-started
        heartbeat('FINISHED' if result.get('exit_code') == 0 else 'HOLD')
        result['artifacts'] = {str(p): sha(p) for folder in (out, result_dir, log_dir, report_dir)
                               if folder.exists() for p in folder.iterdir() if p.is_file()}
        (out/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(work=str(work), **{k: v for k, v in result.items() if k not in ('artifacts', 'metrics')})), flush=True)
    return result.get('exit_code', 1)


if __name__ == '__main__':
    raise SystemExit(main())
