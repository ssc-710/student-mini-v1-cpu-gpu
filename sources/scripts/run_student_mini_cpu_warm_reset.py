"""Execute cold boot then real quiescent warm reset on the mapped DFI CPU.

The DUT and external memory instance persist. Nothing reloads RAM at reset.
This is scoped reset evidence, not a full bus/protocol or baseline certificate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'shared/python')]
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify, execute_locked_route
from scripts.student_mini_cpu_warm_reset import bridge_source, driver_source, read_phases, compare_baselines
from scripts.assemble_student_mini_native_session import reference, transcript
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('selected-run', 'baseline-replay', 'image-dir', 'candidate'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    selected = args.selected_run.resolve(); baseline = args.baseline_replay.resolve()
    selected_packet = selected/'completion.json'; base_packet = baseline/'completion.json'
    parent = json.loads(selected_packet.read_text()); base = json.loads(base_packet.read_text())
    if (parent['status'] != 'SELECTED_MAPPED_CPU_NUMERICAL_STAGE_PASS' or parent['baseline_records'] != 1000
        or parent['bindings'].get(str(base_packet)) != sha(base_packet)
        or base['status'] != 'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'):
        raise ValueError('complete selected-model execution on this exact DFI parent required')
    verify(parent['bindings']); verify(base['bindings'])
    image = args.image_dir.resolve(); candidate = args.candidate.resolve()
    manifest_path = image/'manifest.json'; manifest = json.loads(manifest_path.read_text())
    checkpoint = candidate.parent/parent['deployment']['quantized']
    for path in (manifest_path, candidate, checkpoint, selected/'console.log'):
        recorded = parent['bindings'].get(str(path), parent['artifacts'].get(path.name))
        if recorded != digest(path): raise ValueError('selected-model source/artifact differs: '+str(path))
    if manifest['deployment'] != parent['deployment']: raise ValueError('selected deployment differs')
    driver = ROOT/'tests/rtl/student_mini_cpu_failfast_main.cpp'; bridge = baseline/'bridge.sv'
    if base['bindings'].get(str(bridge)) != sha(bridge) or base['bindings'].get(str(driver)) != sha(driver):
        raise ValueError('qualified base harness differs')
    paths = [Path(__file__), ROOT/'scripts/student_mini_cpu_warm_reset.py',
             ROOT/'scripts/resume_student_mini_interrupted.py', ROOT/'scripts/retry_student_mini_route.py',
             ROOT/'scripts/assemble_student_mini_native_session.py', selected_packet, base_packet,
             bridge, driver, manifest_path, checkpoint, candidate, selected/'console.log']
    bindings = dict(parent['bindings']); bindings.update({str(p):digest(p) for p in paths})
    for path in selected.glob('*.init'):
        if parent['artifacts'].get(path.name) != digest(path): raise ValueError('selected RAM input changed')
        bindings[str(path)] = digest(path)
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-warm-reset'/key; work.mkdir(parents=True, exist_ok=False)
    new_bridge = work/'bridge.sv'; new_driver = work/'main.cpp'
    new_bridge.write_text(bridge_source(bridge.read_text())); new_driver.write_text(driver_source(driver.read_text()))
    for path in selected.glob('*.init'): shutil.copyfile(path, work/path.name)
    for path in (new_bridge, new_driver, *work.glob('*.init')): bindings[str(path)] = digest(path)
    command = list(base['compile_command'])
    for old, new in ((str(bridge), str(new_bridge)), (str(driver), str(new_driver)),
                     (str(baseline/'obj'), str(work/'obj'))):
        if command.count(old) != 1: raise ValueError('ambiguous original compile argument')
        command[command.index(old)] = new
    result = dict(status='HOLD', bindings=bindings, compile_command=command,
                  rtl_changed=False, harness_only=True, reset_held_cycles=8,
                  external_memory_reloaded_at_reset=False, clock_period_ns=10,
                  formal_baseline=False, physical_evidence_complete=False, whole_soc_protocol=False,
                  in_flight_reset_qualified=False, warm_reset_at_quiescent_boundary_complete=False)
    (work/'inputs.json').write_text(json.dumps(result, indent=2)+'\n')
    begin = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-begin))+'\n')
    def cwd_command(arguments):
        return ['bash', '-c', 'ulimit -c 0; cd -- "$1" || exit; shift; exec "$@"', 'warm-cpu', str(work), *arguments]
    print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); verify(bindings)
            if execute_locked_route(cwd_command(command), work/'compile.log', 1800, lambda _:heartbeat('COMPILING_RESET_HARNESS')):
                raise ValueError('warm-reset harness compile failed')
            binary = work/'obj/Vcpu_boundary_replay'; bindings[str(binary)] = digest(binary)
            if execute_locked_route(cwd_command([str(binary), str(selected/'console.log')]), work/'raw-console.log',
                                    3600, lambda _:heartbeat('EXECUTING_COLD_AND_WARM_PHASES')):
                raise ValueError('actual reset execution failed; raw logs preserved')
            phases = read_phases(work/'raw-console.log')
            actual_baselines = compare_baselines((selected/'console.log').read_text(), phases)
            golden = reference(MiniNanoRuntime.from_npz(checkpoint), manifest['prompt_tokens'])
            sessions = [transcript(phase, 'cpu', golden, len(manifest['prompt_tokens'])) for phase in phases]
            if any(s['token_sha256'] != parent['native_join']['token_sha256'] for s in sessions):
                raise ValueError('selected token identity changed across reset')
            for index, phase in enumerate(phases): (work/f'phase-{index}.log').write_text(phase)
            (work/'actual-baselines.json').write_text(json.dumps(actual_baselines)+'\n')
            result.update(status='CPU_QUIESCENT_WARM_RESET_STAGE_PASS',
                          warm_reset_at_quiescent_boundary_complete=True, phase_baseline_records=[1000,1000],
                          sessions=sessions, reason='Real ASIC reset after a complete workload, retained external RAM, full outputs and model states independently verified; in-flight reset and other protocol gates remain')
            verify(bindings)
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.name:digest(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['warm_reset_at_quiescent_boundary_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
