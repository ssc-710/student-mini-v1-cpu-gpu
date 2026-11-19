"""Map the executed-ROM CPU storage using explicit, conservative SRAM semantics.

This stage does not authorize physical synthesis/signoff or whole-core
equivalence. Remaining logic memories and macro use are recorded explicitly.
"""
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
from scripts.prepare_student_mini_cpu_reset_boundary import TOP
from scripts.retry_student_mini_route import execute_locked_route


def retained_roms(original, mapped):
    before = original['modules'][TOP+'_asic']['cells']
    after = mapped['modules'][TOP+'_asic']['cells']
    records = []
    for name, cell in before.items():
        if cell['type'] != '$mem_v2' or int(cell['parameters']['WR_PORTS'], 2) != 0:
            continue
        params = cell['parameters']
        if not any(bit in '01' for bit in params['INIT']): continue
        current = after.get(name, {}).get('parameters', {})
        if any(current.get(key) != params[key] for key in ('INIT', 'WIDTH', 'SIZE', 'OFFSET')):
            raise ValueError('executed initialized ROM changed during SRAM mapping: '+name)
        records.append(dict(name=name, width=int(params['WIDTH'], 2), depth=int(params['SIZE'], 2),
            init_bits_sha256=hashlib.sha256(params['INIT'].encode()).hexdigest()))
    if not records: raise ValueError('no executed initialized ROM retained')
    return records


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=43200)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 43200: raise ValueError('bounded parent wait required')
    storage = args.storage.resolve()
    local = ROOT/'integration/student-mini'
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    macro = ROOT/'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'
    paths = [Path(__file__), ROOT/'scripts/student_mini.py',
             ROOT/'scripts/prepare_student_mini_cpu_reset_boundary.py',
             ROOT/'scripts/retry_student_mini_route.py', yosys,
             yosys.parent.parent/'libexec/yosys', macro]
    paths += [local/name for name in ('cpu_sram_library.txt', 'cpu_sram_map.sv', 'cpu_sram_32x1024.sv')]
    bindings = {str(path): sha(path) for path in paths}
    identity = hashlib.sha256(json.dumps(dict(storage=str(storage), bindings=bindings), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-macro-mapping'/identity; work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', formal_baseline=False, physical_evidence_complete=False,
        whole_core_equivalence=False, physical_flow_ready=False, bindings=bindings, parent=str(storage),
        collision_contract='SRAM same-address read/write is indeterminate; no wrtrans guarantee declared')
    started = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(path)) != value for path, value in bindings.items()):
            raise ValueError('CPU macro-mapping source changed')
    try:
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_EXECUTED_ROM_STORAGE')), flush=True)
        while not (storage/'completion.json').exists():
            heartbeat('WAITING_FOR_EXECUTED_ROM_STORAGE')
            if time.monotonic()-started > args.wait_seconds: raise TimeoutError('storage wait expired')
            time.sleep(10)
        parent = json.loads((storage/'completion.json').read_text())
        if parent['status'] != 'SYNCHRONOUS_STORAGE_INVENTORY_STAGE_PASS':
            raise ValueError('same-ROM storage inventory did not pass')
        bindings.update(parent['bindings'])
        bindings[str(storage/'completion.json')] = sha(storage/'completion.json')
        for name in ('memories.json', 'storage.il'):
            path = storage/name
            if parent['artifacts'].get(name) != sha(path): raise ValueError('storage artifact changed')
            bindings[str(path)] = sha(path)
        script = work/'mapping.ys'
        script.write_text(f'read_rtlil "{storage}/storage.il"\n'
            # opt merges equivalent per-bit enables before byte-lane mapping.
            f'opt\nmemory_share\nopt\nmemory_libmap -lib "{local}/cpu_sram_library.txt"\n'
            f'techmap -map "{local}/cpu_sram_map.sv"\n'
            f'read_verilog -sv "{local}/cpu_sram_32x1024.sv"\n'
            f'read_verilog -lib "{macro}"\n'
            f'hierarchy -check -top {TOP}_asic\nproc\nopt_clean\ncheck -assert\n'
            f'write_json "{work}/mapped.json"\nwrite_verilog -noattr "{work}/mapped.v"\n')
        bindings[str(script)] = sha(script)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); fresh()
            if execute_locked_route([str(yosys), '-Q', '-T', '-s', str(script)], work/'yosys.log',
                    900, lambda _: heartbeat('MAPPING_ACTUAL_CPU_STORAGE')):
                raise RuntimeError('CPU SRAM mapping failed')
            mapped = json.loads((work/'mapped.json').read_text())
            original = json.loads((storage/'memories.json').read_text())
            roms = retained_roms(original, mapped)
            cells = mapped['modules'][TOP+'_asic']['cells']
            macros = [name for name, cell in cells.items() if cell['type']=='student_mini_cpu_sram_32x1024']
            if not macros: raise ValueError('no actual CPU SRAM mapped')
            if any(cell['type'].startswith('$__STUDENT_CPU_') for cell in cells.values()):
                raise ValueError('unexpanded CPU SRAM template')
            remainder = [dict(name=name, width=int(cell['parameters']['WIDTH'], 2),
                depth=int(cell['parameters']['SIZE'], 2), write_ports=int(cell['parameters']['WR_PORTS'], 2))
                for name, cell in cells.items() if cell['type']=='$mem_v2']
            fresh()
        result.update(status='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS', macro_instances=macros,
            macro_count=len(macros), remaining_logic_memories=remainder, executed_roms=roms,
            reason='Real CPU memories structurally mapped with ROM contents retained; full-core replay, reset/DFI equivalence and all physical gates remain mandatory')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status']); result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status']=='CPU_SRAM_MAPPING_STRUCTURE_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
