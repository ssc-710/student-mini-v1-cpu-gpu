"""Extract the single-ROM baseline/Nano CPU boundary without rewriting old evidence.

This is a synthesis entry, NOT reset equivalence, memory mapping or physical PASS.
The emitted ROM is independently checked against the executed BIOS bytes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.export_student_mini_cpu_boundary import cut_dfi_inputs, validate_boundary, PREFIX, DFI_OUTPUTS
from scripts.retry_student_mini_route import execute_locked_route


def check_rom(text, bios):
    words = text.split()
    if not words or any(not re.fullmatch(r'[0-9a-fA-F]{8}', word) for word in words):
        raise ValueError('ROM must contain explicit 32-bit words, without unknowns or addresses')
    decoded = b''.join(int(word, 16).to_bytes(4, 'little') for word in words)
    padded = bios + bytes((-len(bios)) % 4)
    if not bios or decoded != padded:
        raise ValueError('ROM differs from executed BIOS')
    return dict(bytes=len(bios), words=len(words), bios_sha256=hashlib.sha256(bios).hexdigest())


def checked_parent(parent):
    completed = json.loads((parent/'completion.json').read_text())
    original = json.loads((parent/'inputs.json').read_text())
    if (completed.get('target_run_complete') is not True or
        completed.get('same_rom_baseline_and_nano') is not True or
        type(completed.get('baseline_count')) is not int or completed['baseline_count'] != 1000):
        raise ValueError('complete 1000-case and Nano single-ROM target replay required')
    bindings = original.get('bindings')
    if not bindings or completed.get('bindings') != bindings:
        raise ValueError('target source bindings differ')
    for name, digest in bindings.items():
        if sha(Path(name)) != digest:
            raise ValueError('target source changed: '+name)
    for name in ('soc/gateware/sim.v', 'soc/software/bios/bios.bin', 'console.log'):
        if completed.get('artifacts', {}).get(name) != sha(parent/name):
            raise ValueError('target artifact changed: '+name)
    return original, completed


def checked_sources(gateware, original):
    generated = (gateware/'sim.v').resolve()
    sources = [Path(name).resolve() for name in re.findall(r'--cc ([^ "\n]+)', (gateware/'build_sim.sh').read_text())]
    if not sources or sources.count(generated) != 1 or len(set(sources)) != len(sources):
        raise ValueError('ambiguous original compiled source list')
    for source in sources:
        if source != generated and original['bindings'].get(str(source)) != sha(source):
            raise ValueError('compiled source lacks exact target binding: '+str(source))
    return sources


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu-run', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=14400)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 43200:
        raise ValueError('bounded target wait required')
    parent = args.cpu_run.resolve()
    initial = {str(p): sha(p) for p in (Path(__file__), parent/'inputs.json',
        ROOT/'scripts/export_student_mini_cpu_boundary.py', ROOT/'scripts/retry_student_mini_route.py')}
    identity = hashlib.sha256(json.dumps(initial, sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/combined-cpu-boundary'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', physical_evidence_complete=False, extraction_complete=False,
        bindings=initial, parent=str(parent), accepted_nano_session=False)
    started = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(p)) != value for p, value in result['bindings'].items()):
            raise ValueError('bound source or target artifact changed')
    try:
        print(json.dumps(dict(work=str(work), status='WAITING_FOR_CPU_REPLAY')), flush=True)
        while not (parent/'completion.json').exists():
            heartbeat('WAITING_FOR_CPU_REPLAY')
            if time.monotonic()-started > args.wait_seconds:
                raise TimeoutError('CPU replay wait expired')
            time.sleep(10)
        fresh()
        original, completed = checked_parent(parent)
        gateware = parent/'soc/gateware'
        sources = checked_sources(gateware, original)
        result['rom_check'] = check_rom((gateware/'sim_rom.init').read_text(), (parent/'soc/software/bios/bios.bin').read_bytes())
        yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys').resolve()
        paths = [*sources, *gateware.glob('*.init'), gateware/'build_sim.sh',
                 parent/'completion.json', parent/'soc/software/bios/bios.bin', parent/'console.log', yosys]
        result['bindings'].update(original['bindings'])
        result['bindings'].update({str(p): sha(p) for p in paths})
        cut = work/'sim-dfi-boundary.v'
        cut.write_text(cut_dfi_inputs((gateware/'sim.v').read_text()))
        compilation = [cut if p == gateware/'sim.v' else p for p in sources]
        script = work/'extract.ys'
        script.write_text('\n'.join([
            'read_verilog -sv '+' '.join(str(p) for p in compilation),
            'hierarchy -check -top sim', 'proc',
            'expose '+' '.join('sim/w:'+PREFIX+name for name in DFI_OUTPUTS),
            'opt_clean -purge', 'memory_collect', 'opt_clean -purge',
            'opt', 'opt_hier', 'opt_clean -purge',
            'rename sim cpu_student_mini_physical_top', 'check -assert',
            f'write_json {work}/boundary.json', f'write_verilog -noattr {work}/boundary.v', 'stat'])+'\n')
        # LiteX emits relative readmemh paths. Set cwd without rewriting its RTL.
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE')
            fcntl.flock(lock, fcntl.LOCK_EX)
            fresh()
            command = ['bash', '-c', 'cd -- "$1" && exec "$2" -Q -T -s "$3"',
                       'cpu-boundary', str(gateware), str(yosys), str(script)]
            code = execute_locked_route(command, work/'yosys.log', 600, heartbeat)
            if code:
                raise RuntimeError('CPU boundary extraction failed; see yosys.log')
            result['top_memories'] = validate_boundary(json.loads((work/'boundary.json').read_text()))
            fresh()
        result.update(extraction_complete=True,
            reason='Single executed ROM and on-chip boundary extracted; reset/DFI equivalence, mapped SRAM and physical signoff remain unqualified')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-started
    heartbeat('BOUNDARY_EXTRACTED' if result['extraction_complete'] else 'HOLD')
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), complete=result['extraction_complete'], reason=result['reason'])), flush=True)
    return 0 if result['extraction_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
