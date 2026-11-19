"""Recover enabled synchronous cache read ports before SRAM mapping.

Consumes the newly executed-ROM reset continuation. No macro is substituted;
the output remains an unmapped storage inventory, never physical acceptance.
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
from scripts.prepare_student_mini_cpu_reset_boundary import TOP, memory_inventory
from scripts.retry_student_mini_route import execute_locked_route


def compare_memories(before, after):
    """Require exact geometry, contents and write ports; only read FF absorption."""
    def memories(design):
        return {name: cell for name, cell in design['modules'][TOP+'_asic']['cells'].items()
                if cell['type'] in ('$mem', '$mem_v2')}
    original, current = memories(before), memories(after)
    if not original or original.keys() != current.keys():
        raise ValueError('storage cells were added or removed')
    unchanged = ('WIDTH', 'SIZE', 'OFFSET', 'INIT', 'WR_PORTS', 'WR_CLK_ENABLE',
                 'WR_CLK_POLARITY', 'RD_PORTS')
    changes = []
    for name in original:
        left, right = original[name]['parameters'], current[name]['parameters']
        if any(left.get(key) != right.get(key) for key in unchanged):
            raise ValueError('storage geometry/content/write semantics changed: '+name)
        before_clock, after_clock = int(left['RD_CLK_ENABLE'], 2), int(right['RD_CLK_ENABLE'], 2)
        if before_clock & ~after_clock:
            raise ValueError('clocked read became asynchronous: '+name)
        if before_clock != after_clock:
            changes.append(dict(name=name, before_clock_mask=before_clock, after_clock_mask=after_clock))
    cache_names = [name for name in original if name.startswith('VexRiscv.') and
                   ('IBusCachedPlugin_cache.' in name or 'dataCache_1.ways_' in name)]
    if len(cache_names) != 7:
        raise ValueError('unexpected frozen CPU cache storage set')
    for name in cache_names:
        row = current[name]
        if int(row['parameters']['RD_CLK_ENABLE'], 2) != 1 or int(row['parameters']['RD_CLK_POLARITY'], 2) != 1:
            raise ValueError('cache read clock not recovered: '+name)
        if row['connections']['RD_EN'] in (['0'], ['1']):
            raise ValueError('cache read enable unexpectedly constant: '+name)
    return changes


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-continuation', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=43200)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 43200:
        raise ValueError('bounded wait required')
    parent = args.reset_continuation.resolve()
    yosys = Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    paths = [Path(__file__), ROOT/'scripts/student_mini.py',
             ROOT/'scripts/prepare_student_mini_cpu_reset_boundary.py',
             ROOT/'scripts/retry_student_mini_route.py', yosys,
             yosys.parent.parent/'libexec/yosys',
             ROOT/'tests/rtl/student_mini_enabled_memory.sv',
             ROOT/'tests/test_student_mini_cpu_memory_enable.py']
    bindings = {str(path): sha(path) for path in paths}
    identity = hashlib.sha256(json.dumps(dict(parent=str(parent), bindings=bindings), sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-storage'/identity
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', formal_baseline=False, physical_evidence_complete=False,
                  reset_equivalence=False, sram_mapping_complete=False, bindings=bindings,
                  parent=str(parent))
    started = time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,
            updated_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started))+'\n')
    def fresh():
        if any(sha(Path(path)) != value for path, value in bindings.items()):
            raise ValueError('CPU storage source changed')
    try:
        print(json.dumps(dict(work=str(work), stage='WAITING_FOR_EXECUTED_ROM_RESET_BOUNDARY')), flush=True)
        while not (parent/'completion.json').exists():
            heartbeat('WAITING_FOR_EXECUTED_ROM_RESET_BOUNDARY')
            if time.monotonic()-started > args.wait_seconds:
                raise TimeoutError('reset continuation wait expired')
            time.sleep(10)
        continuation = json.loads((parent/'completion.json').read_text())
        output = Path(continuation.get('output', ''))
        if continuation['status'] != 'RESET_STORAGE_PROJECTION_STAGE_PASS' or not output.is_file() or sha(output) != continuation.get('output_sha256'):
            raise ValueError('same-ROM reset continuation is not qualified')
        completed = json.loads(output.read_text())
        if completed.get('boundary_complete') is not True:
            raise ValueError('reset projection incomplete')
        bindings.update(completed['bindings'])
        bindings.update(continuation['bindings'])
        bindings.update({str(path): sha(path) for path in (parent/'completion.json', output)})
        for name in ('cpu-asic.v', 'memories.json'):
            path = output.parent/name
            if completed['artifacts'].get(name) != sha(path):
                raise ValueError('reset artifact differs: '+name)
            bindings[str(path)] = sha(path)
        script = work/'storage.ys'
        script.write_text(f'read_verilog -sv "{output.parent}/cpu-asic.v"\n'
            f'hierarchy -check -top {TOP}_asic\nproc\nflatten\nopt_dff\nopt_clean\n'
            f'memory_dff\nmemory_collect\nopt_clean\ncheck -assert\n'
            f'write_json "{work}/memories.json"\nwrite_rtlil "{work}/storage.il"\n')
        bindings[str(script)] = sha(script)
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE'); fcntl.flock(lock, fcntl.LOCK_EX); fresh()
            code = execute_locked_route([str(yosys), '-Q', '-T', '-s', str(script)],
                work/'yosys.log', 600, lambda _: heartbeat('ELABORATING_ENABLED_STORAGE'))
            if code:
                raise RuntimeError('storage elaboration failed')
            before = json.loads((output.parent/'memories.json').read_text())
            after = json.loads((work/'memories.json').read_text())
            changes = compare_memories(before, after)
            inventory = memory_inventory(after)
            fresh()
        result.update(status='SYNCHRONOUS_STORAGE_INVENTORY_STAGE_PASS', read_clock_changes=changes,
            memories=inventory, reason='Enabled cache read FFs absorbed without changing storage geometry or INIT; actual SRAM mapping, reset equivalence and physical implementation remain')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    heartbeat(result['status'])
    result['elapsed_seconds'] = time.monotonic()-started
    result['artifacts'] = {p.name: sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'SYNCHRONOUS_STORAGE_INVENTORY_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
