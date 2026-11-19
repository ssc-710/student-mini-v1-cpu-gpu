"""Per-seed CPU power from the routed netlists' own activity (P1/P2/P3 MINI-01, seeds 1-10).

The complete traced replay of the final CPU mapping (run_student_mini_cpu_activity_trace.py)
is replayed once on the routed CPU top netlist together with the 25 routed
ROM-bank hard-block netlists (one hierarchical gate model); every recorded
output cycle must agree.  Measurement windows are the CPU's own traffic-counter
windows (counter release to capture) of the selected records; each window's
length is checked against the cycle counter the firmware reported for that
record.  Power = top die (std cells + OpenRAM macros, final SPEF) + each ROM
bank (its own final netlist and SPEF), all from the same SAIF.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_gate_power import (CORNER, build_engine, compile_netlist, config_libs, gzip_file, power, replay,
                                             sanitize_macro_libs, tool_bindings)

OPERATORS = {'p1': 'P1-MINI-01', 'p2': 'P2-MINI-01', 'p3': 'P3-MINI-01'}
TOP = 'cpu_student_mini_physical_top_asic'
SRAM_MODEL = ROOT / 'build/openram/vortex-banked/vortex_sp_32x1024_w4/vortex_sp_32x1024_w4.v'


def bank_instances(netlist: Path) -> dict:
    """ROM-bank module -> instance name in the routed top netlist."""
    found = {}
    for module, inst in re.findall(r'^\s*(student_mini_cpu_rom_bank_\d\d)\s+(\\\S+|\S+)\s*\(', netlist.read_text(), re.M):
        found[module] = inst.lstrip('\\')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical', type=Path, required=True, help='CPU platform-physical work dir (route stage PASS)')
    parser.add_argument('--banks', type=Path, nargs=25, required=True, help='the 25 ROM-bank physical work dirs, in order')
    parser.add_argument('--activity', type=Path, required=True, help='cpu-activity-replay-launch dir (trace stage PASS)')
    parser.add_argument('--vectors', type=Path, required=True)
    args = parser.parse_args()
    physical, activity = args.physical.resolve(), args.activity.resolve()
    route = json.loads((physical / 'completion.json').read_text())
    if route['status'] != 'PLATFORM_PHYSICAL_ROUTE_STAGE_PASS' or route['platform'] != 'cpu':
        raise ValueError('passing CPU physical implementation required')
    for path, digest in route['artifacts'].items():
        if sha(Path(path)) != digest:
            raise ValueError('physical artifact changed: ' + path)
    results = Path(route['result_directory'])
    files = {k: results / f'6_final.{k}' for k in ('v', 'odb', 'sdc', 'spef')}
    banks = []
    for index, work in enumerate(args.banks):
        value = json.loads((work.resolve() / 'completion.json').read_text())
        if value['status'] != 'ROM_BANK_PHYSICAL_STAGE_PASS' or value['bank'] != index:
            raise ValueError(f'bank {index}: passing hard-block run required')
        bank_results = Path(value['result_directory'])
        bank_files = {k: bank_results / f'6_final.{k}' for k in ('v', 'odb', 'sdc', 'spef')}
        for path in bank_files.values():
            if value['artifacts'].get(str(path)) != sha(path):
                raise ValueError(f'bank {index} artifact changed: {path}')
        banks.append(dict(index=index, module=value['design'], work=work.resolve(), files=bank_files))
    traced = json.loads((activity / 'completion.json').read_text())
    if traced['status'] != 'CPU_ACTIVITY_TRACE_STAGE_PASS':
        raise ValueError('passing traced CPU replay required')
    child = Path(traced['child'])
    child_done = json.loads((child / 'completion.json').read_text())
    trace = child / 'port-trace.txt'
    if child_done['artifacts'].get('port-trace.txt') != sha(trace):
        raise ValueError('port trace changed after the replay')
    mapped = Path(child_done['parent_mapping']) / 'mapped.v'
    if not any(Path(p).name == 'mapped.v' and v == sha(mapped) for p, v in route['bindings'].items()):
        raise ValueError('physical CPU was not implemented from the traced mapping')
    counters = {row['ordinal']: row['actual'] for row in child_done['transcript_join']['raw_counter_comparisons']}
    instances = bank_instances(files['v'])
    if sorted(instances) != sorted(b['module'] for b in banks):
        raise ValueError('routed top does not instantiate exactly the 25 ROM banks')
    # a re-audited route stage keeps the routing run's config in that run's directory (reaudit_of)
    config = Path(route.get('reaudit_of') or physical) / 'config.mk'
    if route['bindings'].get(str(config.resolve())) not in (None, sha(config)):
        raise ValueError('CPU run config changed')
    libs = config_libs(config)
    vectors = [json.loads(line) for line in args.vectors.read_text().splitlines()]
    workloads = []
    for op, case in OPERATORS.items():
        rows = [(i, r) for i, r in enumerate(vectors) if r['case']['id'] == case]
        if sorted(r['seed'] for _, r in rows) != list(range(1, 11)):
            raise ValueError(f'{case} seeds 1-10 required')
        workloads += [dict(operator=op, case_id=case, seed=r['seed'], ordinal=i) for i, r in rows]
    bindings = dict(tool_bindings())
    bindings.update({str(p): sha(p) for p in (Path(__file__), physical / 'completion.json', config, activity / 'completion.json',
                                              child / 'completion.json', args.vectors.resolve(), SRAM_MODEL, *files.values(), *libs)})
    for b in banks:
        bindings[str(b['work'] / 'completion.json')] = sha(b['work'] / 'completion.json')
        bindings.update({str(p): sha(p) for p in b['files'].values()})
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, workloads=workloads), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/cpu-gate-power' / key
    work.mkdir(parents=True, exist_ok=False)
    result = dict(status='HOLD', platform='cpu', bindings=bindings, corner=CORNER, frequency_hz=100000000, records=[],
                  window="the record's traffic-counter window (counter release to capture) inside the complete replay",
                  boundary='CPU die: mapped VexRiscv SoC top (std cells + 12 OpenRAM macros) + 25 ROM-bank hard blocks; '
                           'external SDRAM, host and board power excluded')
    (work / 'inputs.json').write_text(json.dumps(dict(result, workloads=workloads), indent=2) + '\n')
    started = time.monotonic()
    try:
        engine = build_engine(work)
        program = compile_netlist(work, files['v'], TOP, [SRAM_MODEL], work / 'compile.log',
                                  modules=[f"{b['module']}={b['files']['v']}" for b in banks])
        result['program'] = json.loads((program / 'summary.json').read_text())
        ordinals = sorted(w['ordinal'] for w in workloads)
        sim_dir = work / 'replay'
        sim_dir.mkdir()
        then = time.monotonic()
        # Window 0 is the firmware's DMA probe (its own counter release/capture); record i is window i + 1.
        # Outputs are sampled while the clock is low, so cycle 0 is sampled before the first rising edge: every
        # register still holds its power-up value, which the design does not define (two-state gate replay starts
        # flops at 0; the RTL simulator picks its own).  Comparison starts at cycle 1, the first sample after a
        # clock edge with reset asserted; every later cycle of the 45 M-cycle trace is compared.
        sim = replay(engine, program, trace, sim_dir, 6 * 3600, windows=[o + 1 for o in ordinals], stop=True, check_from=1)
        result['replay'] = {k: v for k, v in sim.items() if k != 'windows'}
        result['replay']['seconds'] = time.monotonic() - then
        windows = {w['index']: w for w in sim['windows']}
        offsets = set()
        for w in workloads:
            window = windows[w['ordinal'] + 1]
            offsets.add(window['end_cycle'] - window['begin_cycle'] - counters[w['ordinal']]['cycles'])
        # Each window runs from the traffic-counter release to its capture (CSR writes, see the port recorder);
        # the firmware reads its cycle counter inside that window, so every window is the reported cycle count
        # plus the same fixed instrumentation code (CSR writes and counter reads).  One constant, small,
        # non-negative offset over all records proves the windows bracket exactly the measured operators; the
        # offset is recorded and is part of every power window.
        if len(offsets) != 1 or not 0 <= next(iter(offsets)) <= 128:
            raise ValueError(f'window lengths disagree with the reported cycle counters: offsets {sorted(offsets)}')
        result['window_instrumentation_cycles'] = next(iter(offsets))
        result['window_counter_offset_cycles'] = next(iter(offsets))
        items = []
        for w in workloads:
            out = work / f"{w['operator']}-seed{w['seed']:02d}"
            out.mkdir()
            (sim_dir / f"window-{w['ordinal'] + 1}.saif").rename(out / 'window.saif')
            items.append(out)
        power_libs, removed = sanitize_macro_libs([l for l in libs if 'vortex_' in l.name], work / 'power-libs')
        power_libs += [l for l in libs if 'vortex_' not in l.name]
        result['macro_power'] = dict(internal_power_groups_removed=removed, note=sanitize_macro_libs.__doc__.strip())
        top = power(files['odb'], files['sdc'], files['spef'], power_libs, f'TOP/{TOP}', [(o / 'window.saif', o) for o in items],
                    work / 'openroad-top.log')
        bank_power = []
        for b in banks:
            dirs = []
            for o in items:
                d = o / f"bank{b['index']:02d}"
                d.mkdir()
                dirs.append(d)
            bank_power.append(power(b['files']['odb'], b['files']['sdc'], b['files']['spef'], [],
                                    f"TOP/{TOP}/{instances[b['module']]}", [(o / 'window.saif', d) for o, d in zip(items, dirs)],
                                    work / f"openroad-bank{b['index']:02d}.log"))
        for i, (w, out) in enumerate(zip(workloads, items)):
            window = windows[w['ordinal'] + 1]
            parts = [top[i]] + [bp[i] for bp in bank_power]
            total_mw = sum(p['total_mw'] for p in parts)
            annotated, pins = sum(p['annotated_pins'] for p in parts), sum(p['total_pins'] for p in parts)
            seconds = window['duration_ps'] * 1e-12
            saif = gzip_file(out / 'window.saif')
            record = dict(w, input_sha256=hashlib.sha256(json.dumps(vectors[w['ordinal']]['inputs'], sort_keys=True).encode()).hexdigest(),
                          trace_sha256=sha(trace), activity_sha256=sha(saif), netlist_sha256=sha(files['v']), spef_sha256=sha(files['spef']),
                          begin_cycle=window['begin_cycle'], end_cycle=window['end_cycle'], begin_ns=window['begin_cycle'] * 10,
                          end_ns=window['end_cycle'] * 10, window_seconds=seconds, rtl_cycles_counter=counters[w['ordinal']]['cycles'],
                          checked_output_cycles=window['checked_cycles'], output_mismatches=window['mismatched_cycles'],
                          total_toggles=window['total_toggles'], total_mw=total_mw,
                          dynamic_mw=sum(p['dynamic_mw'] for p in parts), leakage_mw=sum(p['leakage_mw'] for p in parts),
                          top_mw=top[i]['total_mw'], rom_banks_mw=total_mw - top[i]['total_mw'],
                          annotated_pins=annotated, total_pins=pins, annotation_percent=100.0 * annotated / pins,
                          unannotated_pins=pins - annotated, unannotated_percent=100.0 * (pins - annotated) / pins,
                          unannotated_examples=[e for p in parts for e in p['unannotated_examples']][:20],
                          macro_reads=dict(zip([x['name'] for x in result['program']['macro_instances']], window['macro_reads'])),
                          macro_writes=dict(zip([x['name'] for x in result['program']['macro_instances']], window['macro_writes'])),
                          power_w=total_mw / 1000, energy_j=total_mw / 1000 * seconds)
            result['records'].append(record)
            print(json.dumps({k: record[k] for k in ('operator', 'seed', 'total_mw', 'annotation_percent', 'checked_output_cycles')}), flush=True)
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('power input changed during execution')
        result['summary'] = {op: dict(seeds=10, mean_total_mw=sum(r['total_mw'] for r in rows) / 10,
                                      mean_dynamic_mw=sum(r['dynamic_mw'] for r in rows) / 10,
                                      mean_leakage_mw=sum(r['leakage_mw'] for r in rows) / 10,
                                      mean_energy_j=sum(r['energy_j'] for r in rows) / 10,
                                      min_annotation_percent=min(r['annotation_percent'] for r in rows))
                             for op in OPERATORS for rows in [[r for r in result['records'] if r['operator'] == op]]}
        result.update(status='CPU_GATE_POWER_STAGE_PASS',
                      reason='Per-record routed-netlist activity (top + ROM banks) with zero output mismatches; SPEF-based power')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file() and p.name != 'gatesim'}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'CPU_GATE_POWER_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
