"""v2: execute all CPU baselines and native Nano with one question-independent Full_4k ROM.

Identical to run_student_mini_combined_cpu.py except that the BIOS package is
integration/litex/combined_mini_bios_v2 (prompt length read at run time).

An isolated BIOS package leaves all historical CPU sources/results untouched.
The existing mini loader accepts 1936-byte blocks: trailing zero padding is only
a transport container, not test cases, and its count is never used by this BIOS.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def python_build_environment(environment, executable):
    result=dict(environment)
    # Do not resolve(): a venv executable is normally a symlink to /usr/bin.
    binary_directory=Path(executable).absolute().parent
    result['PATH']=str(binary_directory)+os.pathsep+result.get('PATH','')
    if (binary_directory.parent/'pyvenv.cfg').is_file():
        result['VIRTUAL_ENV']=str(binary_directory.parent)
    return result


def build_child(work, image_dir, baseline_dir):
    os.cpu_count = lambda: min(2, len(os.sched_getaffinity(0)))
    from litex.soc.integration.builder import Builder
    from integration.litex.soc import build_soc
    original = Builder.add_software_package
    def add_package(self, name, *args, **kwargs):
        if name == 'bios':
            return original(self, name, str(ROOT/'integration/litex/combined_mini_bios_v2'))
        return original(self, name, *args, **kwargs)
    Builder.add_software_package = add_package
    os.environ.update(COURSE_ROOT=str(ROOT), COURSE_NATIVE_IMAGE_DIR=str(image_dir),
        COURSE_MINI_BASELINE_RECORD_COUNT='1000', COURSE_NATIVE_BASE_OFFSET=str((baseline_dir/'inputs.bin').stat().st_size))
    image = work/'loader.bin'
    build_soc(output_dir=work/'soc', run=False, cpu_b0=True, control_smoke=True,
              cpu_variant='full', student_mini_image=image,
              student_mini_count=image.stat().st_size//1936)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-dir', type=Path, required=True)
    parser.add_argument('--build-child', type=Path)
    parser.add_argument('--baseline-input-dir', type=Path, required=True)
    args = parser.parse_args()
    image_dir = args.image_dir.resolve()
    baseline_dir = args.baseline_input_dir.resolve()
    if args.build_child:
        build_child(args.build_child.resolve(), image_dir, baseline_dir)
        return 0
    import fcntl
    baseline_manifest = json.loads((baseline_dir/'manifest.json').read_text())
    if baseline_manifest['count'] != 1000 or (baseline_dir/'inputs.bin').stat().st_size != 1936000:
        raise ValueError('exact frozen 1000-record baseline input required')
    for name, digest in baseline_manifest['artifacts'].items():
        if sha(baseline_dir/name) != digest:
            raise ValueError('baseline input artifact changed')
    for name, digest in baseline_manifest['bindings'].items():
        if sha(ROOT/name) != digest:
            raise ValueError('baseline input source changed')
    manifest_path = image_dir/'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('contains_expected_tokens') is not False or sha(image_dir/'image.bin') != manifest['image_sha256']:
        raise ValueError('input-only image binding required')
    for name, digest in manifest['bindings'].items():
        if sha(ROOT/name) != digest:
            raise ValueError('image source changed: '+name)
    paths = [Path(__file__), manifest_path, image_dir/'image.bin', image_dir/'student_mini_native_image.h',
        ROOT/'integration/litex/soc.py', ROOT/'integration/litex/bios/Makefile',
        ROOT/'software/student_mini_native_nano.c', ROOT/'software/operator_scalar.c',
        ROOT/'build/vexriscv-profiles/VexRiscv_Full_4k.v']
    paths += list((ROOT/'integration/litex/native_nano_bios').glob('*'))
    paths += list((ROOT/'integration/litex/combined_mini_bios').glob('*'))
    paths += list((ROOT/'integration/litex/combined_mini_bios_v2').glob('*'))
    paths += [baseline_dir/'manifest.json', baseline_dir/'inputs.bin',
        ROOT/'integration/litex/bios/student_mini_session.c', ROOT/'software/student_mini_scalar.c']
    paths += list((ROOT/'software/include').glob('*.h'))
    paths += list((ROOT/'shared/rtl').glob('*.sv'))+list((ROOT/'shared/rtl').glob('*.svh'))
    paths += [ROOT/'exercises/05-integration/05.01-ibex-accelerator/solution/rtl/accelerator_shell.sv']
    import litex
    upstream = Path(litex.__file__).resolve().parent/'soc/software'
    paths += [upstream/'common.mak']
    paths += [p for p in (upstream/'bios').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [Path('/home/soclab/tools/verilator-5.040/bin')/name for name in ('verilator','verilator_bin')]
    bindings = {str(p): sha(p) for p in paths if p.is_file()}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/combined-cpu-v2'/identity
    work.mkdir(parents=True, exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(dict(bindings=bindings,
        runtime_input_contains_golden=False, loader_block_bytes=1936, baseline_count=1000,
        native_image_offset=1936000, input_manifest=baseline_manifest), indent=2)+'\n')
    blob = (baseline_dir/'inputs.bin').read_bytes()+(image_dir/'image.bin').read_bytes()
    (work/'loader.bin').write_bytes(blob+bytes((-len(blob)) % 1936))
    result = dict(status='HOLD', formal_baseline=False, accepted_nano_session=False,
                  bindings=bindings, target='VexRiscv_Full_4k', target_run_complete=False)
    started = time.monotonic()
    child = None
    lock = Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a')
    def interrupted(signum, frame):
        raise InterruptedError('CPU execution termination requested')
    previous = signal.signal(signal.SIGTERM, interrupted)
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    env = dict(os.environ, COURSE_ROOT=str(ROOT), COURSE_NATIVE_IMAGE_DIR=str(image_dir),
        COURSE_VERILATOR_BIN='/home/soclab/tools/verilator-5.040/bin/verilator',
        MAKEFLAGS='-j2', PYTHONUNBUFFERED='1', CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='')
    env = python_build_environment(env, sys.executable)
    env.pop('COURSE_STUDENT_MINI', None)
    try:
        if lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            print(json.dumps(dict(work=str(work), stage='WAITING_FOR_SERIAL_QUEUE')), flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('source changed while queued')
            heartbeat('BUILDING')
            with (work/'build.log').open('x') as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__)), '--image-dir', str(image_dir),
                    '--baseline-input-dir', str(baseline_dir), '--build-child', str(work)], cwd=ROOT, env=env, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                code = child.wait(timeout=1500)
                if code:
                    raise RuntimeError('CPU build failed: '+str(code))
            heartbeat('VEXRISCV_EXECUTING')
            child = subprocess.Popen([str(work/'soc/gateware/obj_dir/Vsim')], cwd=work/'soc/gateware',
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                errors='replace', bufsize=1, start_new_session=True)
            messages = queue.Queue()
            def drain():
                for line in child.stdout:
                    messages.put(line)
                messages.put(None)
            threading.Thread(target=drain, daemon=True).start()
            deadline = time.monotonic()+3600
            complete = False
            baseline_complete = False
            native_complete = False
            with (work/'console.log').open('x', buffering=1) as log:
                while time.monotonic() < deadline:
                    try:
                        line = messages.get(timeout=1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    log.write(line)
                    if line == 'STUDENT_CPU_COMPLETE count=1000\n':
                        baseline_complete = True
                    if line.startswith('STUDENT_NATIVE_CPU_COMPLETE '):
                        native_complete = True
                    if baseline_complete and native_complete:
                        complete = True
                        break
            if not complete:
                raise RuntimeError('missing baseline or native CPU completion marker')
            if any(sha(Path(p)) != digest for p, digest in bindings.items()):
                raise ValueError('source changed during target execution')
            result.update(target_run_complete=True, baseline_count=1000, same_rom_baseline_and_nano=True,
                reason='Actual target transcript collected; independent token/state join, quality, physical and release gates remain separate')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
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
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        signal.signal(signal.SIGTERM, previous)
        result['elapsed_seconds'] = time.monotonic()-started
        heartbeat('TARGET_TRANSCRIPT_READY' if result['target_run_complete'] else 'HOLD')
        files = [p for p in work.iterdir() if p.is_file()]
        files += [work/'soc/software/bios/bios.bin', work/'soc/gateware/obj_dir/Vsim',
                  work/'soc/gateware/sim.v', work/'soc/csr.csv']
        files += list((work/'soc/gateware').glob('*.init'))
        files += [work/'soc/gateware/build_sim.sh']
        result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in files if p.is_file()}
        (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(dict(work=str(work), complete=result['target_run_complete'], reason=result['reason'])), flush=True)
    return 0 if result['target_run_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
