"""100 MHz placement preflight of the replayed repaired GPU; no failed route."""
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
from scripts.run_student_mini_cpu_placement import TARGETS


def checked_synthesis(parent):
    if parent.get('status') != 'RETIMED_GPU_SYNTHESIS_STAGE_PASS' or parent.get('synthesis_complete') is not True:
        raise ValueError('successful repaired GPU synthesis required')
    if parent.get('clock_period_ns') != 10 or parent.get('macro_count') != 37 or parent.get('threads') != 2:
        raise ValueError('frozen 100 MHz / 37 macro / two-thread profile required')
    boundary = [name for name in parent['bindings'] if '/gpu-port-boundary/' in name and name.endswith('/completion.json')]
    replay = [name for name in parent['bindings'] if '/gpu-physical-replay/' in name and name.endswith('/completion.json')]
    if len(boundary) != 1 or len(replay) != 1:
        raise ValueError('complete repaired boundary and actual representative replay must both be bound')


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis-continuation', type=Path, required=True)
    args = parser.parse_args(); prior = args.synthesis_continuation.resolve()
    files = [Path(__file__), ROOT / 'scripts/run_student_mini_cpu_placement.py', ROOT / 'scripts/retry_student_mini_route.py',
             ROOT / 'integration/student-mini/check_gpu_macro_power.tcl', prior / 'inputs.json']
    bindings = {str(p): sha(p) for p in files}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-repaired-placement' / identity; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', preflight_complete=False, physical_evidence_complete=False, formal_baseline=False,
                  bindings=bindings, clock_period_ns=10, threads=2, macro_count=37)
    (work / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    begin = time.monotonic(); folders = [work]
    def heartbeat(stage):
        (work / 'heartbeat.json').write_text(json.dumps(dict(stage=stage, updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=time.monotonic()-begin)) + '\n')
    try:
        heartbeat('WAITING_FOR_REPAIRED_SYNTHESIS'); print(json.dumps(dict(work=str(work), stage='WAITING_FOR_REPAIRED_SYNTHESIS')), flush=True)
        while not (prior / 'completion.json').is_file():
            if time.monotonic()-begin > 43200:
                raise TimeoutError('bounded synthesis wait expired')
            time.sleep(10)
        receipt = prior / 'completion.json'; continuation = json.loads(receipt.read_text())
        if continuation['status'] != 'REPAIRED_GPU_SYNTHESIS_PREFLIGHT_STAGE_PASS':
            raise ValueError('repaired synthesis continuation failed')
        synthesis = Path(continuation['synthesis']['work']); packet = synthesis / 'completion.json'
        parent = json.loads(packet.read_text()); checked_synthesis(parent)
        bindings.update(parent['bindings']); bindings.update({str(p): sha(p) for p in (receipt, packet)})
        old_results = Path(parent['result_directory'])
        checkpoints = [old_results / name for name in ('1_synth.odb', '1_synth.sdc')]
        for path in checkpoints:
            if parent['artifacts'].get(str(path)) != sha(path):
                raise ValueError('synthesis checkpoint changed')
            bindings[str(path)] = sha(path)
        config = work / 'config.mk'; shutil.copyfile(parent['config'], config); bindings[str(config)] = sha(config)
        variant = 'student-mini-gpu-repaired-' + identity[:16]
        results = old_results.parent / variant; logs = Path(parent['metrics_directory']).parent / variant
        orfs = Path('/home/soclab/src/orfs-clean-aabf2a')
        reports = orfs / 'flow/reports/sky130hd/vortex_physical_top' / variant
        folders += [results, logs, reports]
        result.update(config=str(config), result_directory=str(results), metrics_directory=str(logs), reports_directory=str(reports),
                      parent_synthesis=str(synthesis))
        (work / 'qualified-inputs.json').write_text(json.dumps(result, indent=2) + '\n')
        verify(bindings)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            result['queue_and_parent_wait_seconds'] = time.monotonic()-begin
            for folder in (results, logs, reports): folder.mkdir(parents=True, exist_ok=False)
            for path in checkpoints:
                shutil.copyfile(path, results / path.name)
                if sha(results / path.name) != bindings[str(path)]: raise ValueError('checkpoint copy differs')
            base = ['make', '-j1', '-C', str(orfs / 'flow'), f'DESIGN_CONFIG={config}', f'FLOW_VARIANT={variant}',
                    f'COURSE_ROOT={ROOT}', 'OPENROAD_EXE=/home/soclab/.local/bin/openroad',
                    'YOSYS_EXE=/home/soclab/tools/oss-cad-suite/bin/yosys', 'NUM_CORES=2']
            for target in TARGETS:
                if execute_locked_route(base + [target], work / (target + '.log'), 600, lambda _: heartbeat(target)):
                    raise ValueError('GPU placement failed: ' + target)
                if target == 'do-2_4_floorplan_pdn':
                    command = ['env', f'STUDENT_MINI_PDN_ODB={results}/2_4_floorplan_pdn.odb', '/home/soclab/.local/bin/openroad',
                               '-exit', str(ROOT / 'integration/student-mini/check_gpu_macro_power.tcl')]
                    if execute_locked_route(command, work / 'macro-power.log', 60, lambda _: heartbeat('CHECKING_74_MACRO_SUPPLY_PINS')):
                        raise ValueError('GPU macro supply check failed')
                    if (work / 'macro-power.log').read_text().splitlines().count('GPU_MACRO_POWER_CONNECTED macros=37 pins=74') != 1:
                        raise ValueError('missing actual macro supply assertion')
                    result['macro_power_connected'] = True
            metrics = json.loads((logs / '3_5_place_dp.json').read_text())
            wns = metrics['detailedplace__timing__setup__ws']; result['placement_wns_ns'] = wns
            if type(wns) not in (float, int) or not math.isfinite(wns) or wns < 0:
                raise ValueError('100 MHz GPU placement timing fails; route prohibited')
            verify(bindings)
            result.update(status='REPAIRED_GPU_PLACEMENT_PREFLIGHT_STAGE_PASS', preflight_complete=True,
                          reason='Actual corrected GPU placement passes 100 MHz; complete route, pin access and per-load power remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {str(p): sha(p) for folder in folders if folder.exists() for p in folder.rglob('*') if p.is_file()}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['preflight_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
