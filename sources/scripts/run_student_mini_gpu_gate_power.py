"""Per-seed GPU power from the routed hierarchical netlists' own activity (P1/P2/P3 MINI-01, seeds 1-10).

The final GPU is the four-quadrant hierarchical implementation: one top-level run (vortex_physical_top
with the blocks vortex_physical_top_q0..q3 as vortex_physical_top_q<i>_inst plus top-level clock/repair
buffers) and four quadrant hard-block runs (each with its OpenRAM macros), all guarded
run_student_mini_platform_physical.py route-stage PASSes; the blocks were cut from the frozen gpu-partition
stage (freeze_student_mini_gpu_partition.py) and the assembled chip closed the full-chip STA
(run_student_mini_gpu_fullchip_sta.py).

Lineage: the top run binds the partition stage and its bound config reads the four block runs' abstract
liberty files, its top module is the partition's top module, every block run's config is the partition's
frozen block config, the full-chip sign-off bound exactly these top and block netlists and SPEF, and the
partition's flat GPU synthesis config synthesised exactly the mapped RTL (project-banked.v) the activity
and baseline executions were built from (see check_source_lineage).

For each workload the mapped-GPU RTL execution with the port recorder (run_student_mini_gpu_activity_trace.py)
must reproduce the bound baseline execution exactly (same output, instructions and cycles).  Its port trace
is replayed on the routed top netlist linked with the four routed block netlists (one hierarchical gate
model, OpenRAM macros from their behavioural models); every recorded output cycle must agree.  The window
is the whole one-case command from reset release to the end of simulation.  Power = top level (std cells,
final SPEF; the blocks appear only as abstract models without power groups) + each quadrant block (its own
final netlist, SDC and SPEF, the same SAIF scoped to its instance), OpenROAD at 100 MHz; activity coverage
and unannotated pins are recorded per part and in total.
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
from scripts.prepare_student_mini_gpu_top import direct_chip_feedthroughs
from scripts.student_mini_gate_power import (CORNER, build_engine, compile_netlist, config_libs, gpu_rule, gzip_file, power,
                                             replay, reset_release_cycle, sanitize_macro_libs, tool_bindings, trace_layout,
                                             write_qualifiers)

OPERATORS = {'p1': 'P1-MINI-01', 'p2': 'P2-MINI-01', 'p3': 'P3-MINI-01'}
TOP = 'vortex_physical_top'
BLOCKS = tuple(f'{TOP}_q{q}' for q in range(4))
QUADRANTS = ('q0_LL', 'q1_LR', 'q2_UL', 'q3_UR')      # partition directories (freeze_student_mini_gpu_partition.NAMES)
FREQUENCY_HZ = 100000000
# A power group in a block's abstract liberty would add the block a second time to the top-level power.
ABSTRACT_POWER = re.compile(r'\b(?:internal_power|leakage_power)\s*\(|\bcell_leakage_power\s*:')


def completion(path: Path) -> Path:
    path = path.resolve()
    return path if path.name == 'completion.json' else path / 'completion.json'


def routed(path: Path, platform: str) -> dict:
    """A passing guarded route-stage run whose every artifact is unchanged."""
    done = completion(path)
    value = json.loads(done.read_text())
    if value.get('status') != 'PLATFORM_PHYSICAL_ROUTE_STAGE_PASS' or value.get('platform') != platform:
        raise ValueError(f'{done}: passing {platform} physical implementation required')
    for p, digest in value['artifacts'].items():
        if sha(Path(p)) != digest:
            raise ValueError(f'{platform} physical artifact changed: {p}')
    results = Path(value['result_directory'])
    files = {k: results / f'6_final.{k}' for k in ('v', 'odb', 'sdc', 'spef')}
    for p in files.values():
        if str(p) not in value['artifacts']:
            raise ValueError(f'{done}: {p.name} is not a bound artifact of the run')
    # a re-audited, antenna-resumed or post-route-ECO route stage keeps the routing run's config in the directory
    # of the original routing run (followed back through reaudit_of / resumed_from / eco_from)
    origin, earlier = done.parent, value
    while any(earlier.get(k) for k in ('eco_from', 'resumed_from', 'reaudit_of')):
        origin = Path(next(earlier[k] for k in ('eco_from', 'resumed_from', 'reaudit_of') if earlier.get(k)))
        earlier = json.loads((origin / 'completion.json').read_text())
    config = origin / 'config.mk'
    if value['bindings'].get(str(config)) != sha(config):
        raise ValueError(f'{done}: run config changed')
    design = re.search(r'^export DESIGN_NAME = (\S+)$', config.read_text(), re.M).group(1)
    return dict(completion=done, work=done.parent, value=value, files=files, config=config, design=design,
                libs=config_libs(config))


def module_text(netlist: Path, module: str) -> str:
    found = re.search(r'^module ' + re.escape(module) + r'\b.*?^endmodule', netlist.read_text(), re.S | re.M)
    if not found:
        raise ValueError(f'{netlist} has no module {module}')
    return found.group(0)


def block_instances(netlist: Path) -> dict:
    """Quadrant-block module -> its single instance name in the routed top netlist."""
    found = {}
    for module, inst in re.findall(r'^\s*(' + re.escape(TOP) + r'_q\d)\s+(\\\S+|\S+)\s*\(', netlist.read_text(), re.M):
        found.setdefault(module, []).append(inst.lstrip('\\'))
    if sorted(found) != sorted(BLOCKS) or any(len(v) != 1 for v in found.values()):
        raise ValueError(f'routed top does not instantiate each quadrant block exactly once: {found}')
    return {m: v[0] for m, v in found.items()}


def partition_stage(path: Path) -> dict:
    """The frozen partition stage, its unchanged artifacts and its bound flat sources."""
    done = completion(path)
    value = json.loads(done.read_text())
    if value.get('status') != 'GPU_PARTITION_STAGE_PASS':
        raise ValueError(f'{done}: passing GPU partition stage required')
    work = done.parent
    for rel, digest in value['artifacts'].items():
        if sha(work / rel) != digest:
            raise ValueError('partition artifact changed: ' + rel)
    bound = [Path(p) for p in value['bindings']]

    def pick(what, test):
        # freeze_student_mini_gpu_partition.py binds exactly one completion.json (--flat-parent), one config.mk
        # outside the quadrant directories (--flat-config) and one netlist besides quad.v/top.v/block.v (--flat-netlist)
        found = [p for p in bound if test(p)]
        if len(found) != 1:
            raise ValueError(f'partition stage does not bind exactly one {what}: {found}')
        return found[0]
    flat_parent = pick('flat parent', lambda p: p.name == 'completion.json')
    flat_config = pick('flat config', lambda p: p.name == 'config.mk' and p.parent.name not in QUADRANTS)
    flat_netlist = pick('flat netlist', lambda p: p.suffix == '.v' and p.name not in ('quad.v', 'top.v', 'block.v'))
    for p in (flat_parent, flat_config, flat_netlist):
        if sha(p) != value['bindings'][str(p)]:
            raise ValueError(f'partition flat source changed: {p}')
    return dict(completion=done, work=work, value=value, flat_parent=flat_parent, flat_config=flat_config,
                flat_netlist=flat_netlist)


PORT_DECL = re.compile(r'^(\s*(?:input|output)\s+)\[(\d+):(\d+)\](\s+)([A-Za-z_]\w*)(\s*;\s*)$')


def port_ranges(netlist: Path, module: str) -> dict:
    """Declared [msb:lsb] of every vector port of a netlist module."""
    return {m.group(5): (int(m.group(2)), int(m.group(3)))
            for m in map(PORT_DECL.match, module_text(netlist, module).splitlines()) if m}


def replay_port_order(netlist: Path, reference: Path, out: Path) -> list:
    """Copy of the top netlist for the gate replay whose vector ports are declared in the bit order of the reference.

    The port trace is the MSB-first concatenation of the RTL ports, the replay maps it onto the netlist ports by
    position.  The partition's top declares the per-memory-port vectors [1:0] where the RTL (and the flat netlist,
    replay-equal to it) declares [0:1]: same bits by index (every connection names its bit), opposite MSB.  The copy
    differs from the netlist only in those declaration lines (asserted); the power uses the unchanged netlist's
    database and parasitics."""
    ref = port_ranges(reference, TOP)
    lines, changed = netlist.read_text().splitlines(keepends=True), []
    in_top = False
    for i, line in enumerate(lines):
        if line.startswith('module '):
            in_top = re.match(r'module\s+([^\s(]+)', line).group(1) == TOP
        m = PORT_DECL.match(line.rstrip('\n')) if in_top else None
        if not m or m.group(5) not in ref:
            continue
        hi, lo, (rhi, rlo) = int(m.group(2)), int(m.group(3)), ref[m.group(5)]
        if sorted((hi, lo)) != sorted((rhi, rlo)):
            raise ValueError(f'port {m.group(5)} is [{hi}:{lo}] in the netlist but [{rhi}:{rlo}] in {reference}')
        if (hi, lo) != (rhi, rlo):
            lines[i] = f'{m.group(1)}[{rhi}:{rlo}]{m.group(4)}{m.group(5)}{m.group(6)}' + ('\n' if line.endswith('\n') else '')
            changed.append(dict(port=m.group(5), netlist=f'[{hi}:{lo}]', replay=f'[{rhi}:{rlo}]'))
    out.write_text(''.join(lines))
    differing = [i for i, (a, b) in enumerate(zip(netlist.read_text().splitlines(), out.read_text().splitlines())) if a != b]
    if len(differing) != len(changed) or len(netlist.read_text().splitlines()) != len(out.read_text().splitlines()):
        raise ValueError('replay netlist differs from the routed netlist beyond port declarations')
    return changed


def check_source_lineage(part: dict, act: dict, base: dict) -> dict:
    """The flat GPU the partition was cut from was synthesised from the traced mapped RTL.

    The activity and baseline build.json record the mapped RTL as `boundary` (a boundary directory) and bind
    <boundary>/project-banked.v by SHA.  The partition binds the flat ORFS config by SHA, and that config
    names the synthesised project in GPU_PROJECT: this path and SHA are the common identifier.  The flat
    parent completion.json (the source stage handed to the freeze) records its own `boundary`; it may be an
    ancestor of the traced boundary (boundary completion.json files name their `parent`), which is checked
    when the field exists and recorded either way.
    """
    project = Path(act['boundary']) / 'project-banked.v'
    named = re.search(r'^\s*(?:export\s+)?GPU_PROJECT\s*[:?]?=\s*(\S+)\s*$', part['flat_config'].read_text(), re.M)
    if not named:
        raise ValueError(f'flat config {part["flat_config"]} names no GPU_PROJECT')
    digest = sha(project)
    if Path(named.group(1)) != project or act['bindings'].get(str(project)) != digest \
            or base['bindings'].get(str(project)) != digest:
        raise ValueError(f'flat GPU synthesised {named.group(1)}, not the traced mapped RTL {project}')
    chain, here = [], Path(act['boundary'])
    while here is not None and here not in chain and len(chain) < 32:
        chain.append(here)
        record = here / 'completion.json'
        parent = json.loads(record.read_text()).get('parent') if record.is_file() else None
        here = (Path(parent).parent if Path(parent).name == 'completion.json' else Path(parent)) if parent else None
    flat = json.loads(part['flat_parent'].read_text())
    if flat.get('boundary') is not None and Path(flat['boundary']) not in chain:
        raise ValueError(f'flat parent boundary {flat["boundary"]} is not in the traced RTL lineage {chain}')
    return dict(traced_boundary=act['boundary'], traced_project=str(project), traced_project_sha256=digest,
                flat_config=str(part['flat_config']), flat_netlist=str(part['flat_netlist']),
                flat_parent=str(part['flat_parent']), flat_parent_status=flat.get('status'),
                flat_parent_boundary=flat.get('boundary'), traced_boundary_ancestry=[str(p) for p in chain])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--top', type=Path, required=True, help='top-level platform-physical completion.json or work dir (gpu)')
    parser.add_argument('--blocks', type=Path, nargs=4, required=True,
                        help='quadrant-block platform-physical completion.json or work dirs (gpu-block), q0 q1 q2 q3')
    parser.add_argument('--partition', type=Path, required=True, help='gpu-partition completion.json or dir')
    parser.add_argument('--signoff', type=Path, required=True, help='gpu-fullchip-sta completion.json or dir')
    parser.add_argument('--activity', type=Path, required=True, help='gpu-activity-rtl work dir with executed traces')
    parser.add_argument('--baseline', type=Path, required=True, help='gpu-platform-rtl work dir of the formal results')
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--operators', nargs='*', default=sorted(OPERATORS))
    args = parser.parse_args()
    activity, baseline = args.activity.resolve(), args.baseline.resolve()
    top = routed(args.top, 'gpu')
    blocks = [routed(b, 'gpu-block') for b in args.blocks]
    part = partition_stage(args.partition)
    signoff_path = completion(args.signoff)
    signoff = json.loads(signoff_path.read_text())
    if signoff.get('status') != 'GPU_FULLCHIP_SIGNOFF_PASS':
        raise ValueError('passing GPU full-chip sign-off required')
    files = top['files']
    if top['design'] != TOP:
        raise ValueError(f'top run implements {top["design"]}, not {TOP}')
    # hierarchy and partition lineage
    summary = json.loads((part['work'] / 'summary.json').read_text())
    if summary.get('top') != TOP:
        raise ValueError('partition top module differs')
    if not any(top['value']['bindings'].get(str(p)) == sha(p) for p in (part['completion'], part['work'] / 'top.v')):
        raise ValueError('top run does not bind the partition stage')
    top_source = re.search(r'^export VERILOG_FILES = (\S+)$', top['config'].read_text(), re.M)
    # the partition's top module, with the logic-equivalent chip-input feedthrough rewiring that
    # prepare_student_mini_gpu_top.py derives from these block runs' final netlists
    expected_top, _ = direct_chip_feedthroughs(module_text(part['work'] / 'top.v', TOP), [f'{m}_inst' for m in BLOCKS],
                                               [b['files']['v'] for b in blocks])
    if not top_source or module_text(Path(top_source.group(1)), TOP) != expected_top:
        raise ValueError("top run's top module is not the partition's top module (with the feedthrough rewiring)")
    instances = block_instances(files['v'])
    abstract_libs = []
    for q, (b, quadrant) in enumerate(zip(blocks, QUADRANTS)):
        if b['design'] != BLOCKS[q] or summary['blocks'][quadrant[3:]]['module'] != BLOCKS[q]:
            raise ValueError(f'block {q}: run implements {b["design"]}, partition quadrant {quadrant} expects {BLOCKS[q]}')
        frozen = part['work'] / quadrant / 'config.mk'
        digest = part['value']['artifacts'].get(f'{quadrant}/config.mk')
        if digest is None or b['value']['bindings'].get(str(frozen)) != digest:
            raise ValueError(f'block {q}: run config is not the frozen partition config {frozen}')
        # The abstract lies in the ORFS results tree, which the runner does not bind (config_inputs skips FLOW);
        # its path is unique to the block run (variant key) and named by the top's bound run config, and its
        # SHA is a checked artifact of the block run.
        if 'abstract' not in b['value']:
            raise ValueError(f'block {q}: run has no abstract model')
        lib = Path(b['value']['abstract']['lib'])
        if lib not in top['libs'] or str(lib) not in b['value']['artifacts']:
            raise ValueError(f"block {q}: top run was not built on this block run's abstract model")
        found = len(ABSTRACT_POWER.findall(lib.read_text()))
        if found:
            raise ValueError(f'block {q}: abstract liberty carries {found} power groups (top power would double count it)')
        abstract_libs.append(lib)
        b['instance'] = instances[b['design']]
    # the sign-off timed exactly these runs
    design_files = [top['completion'], files['v'], files['spef'], files['sdc']]
    for b in blocks:
        design_files += [b['completion'], b['files']['v'], b['files']['spef']]
    if any(signoff['bindings'].get(str(p)) != sha(p) for p in design_files):
        raise ValueError('full-chip sign-off was not run on these top and block implementations')
    act = json.loads((activity / 'build.json').read_text())
    base = json.loads((baseline / 'build.json').read_text())
    if act['status'] != 'GPU_PLATFORM_RTL_BUILD_STAGE_PASS' or base['status'] != 'GPU_PLATFORM_RTL_BUILD_STAGE_PASS':
        raise ValueError('passing activity and baseline RTL builds required')
    if act['boundary'] != base['boundary'] or act['input_directory'] != base['input_directory']:
        raise ValueError('activity and baseline executions differ in mapped RTL or inputs')
    lineage = check_source_lineage(part, act, base)
    stray = [l for l in top['libs'] if l not in abstract_libs and l.name.startswith(TOP)]
    if stray:
        raise ValueError(f'top reads block abstracts of other runs: {stray}')
    macro_libs = {}    # OpenRAM libraries of the top (if any) and of the blocks, by file name
    for lib in [l for l in top['libs'] if l not in abstract_libs] + [l for b in blocks for l in b['libs']]:
        if macro_libs.setdefault(lib.name, lib) != lib:
            raise ValueError(f'two different macro libraries named {lib.name}')
    models = [Path(p) for p, _ in act['bindings'].items() if Path(p).suffix == '.v' and Path(p).name.startswith('vortex_')
              and Path(p).parent.parent.name == 'vortex-banked']
    vectors = [json.loads(line) for line in args.vectors.read_text().splitlines()]
    workloads = []
    for op in args.operators:
        rows = [(i, r) for i, r in enumerate(vectors) if r['case']['id'] == OPERATORS[op]]
        if sorted(r['seed'] for _, r in rows) != list(range(1, 11)):
            raise ValueError(f'{OPERATORS[op]} seeds 1-10 required')
        workloads += [dict(operator=op, case_id=OPERATORS[op], seed=r['seed'], ordinal=i) for i, r in rows]
    bindings = dict(tool_bindings())
    bindings.update({str(p): sha(p) for p in (Path(__file__), top['completion'], top['config'], *files.values(), *top['libs'],
                                              part['completion'], part['work'] / 'top.v', part['work'] / 'summary.json',
                                              part['flat_config'], part['flat_parent'], signoff_path,
                                              activity / 'build.json', baseline / 'build.json', args.vectors.resolve(), *models)})
    for b in blocks:
        bindings.update({str(p): sha(p) for p in (b['completion'], b['config'], *b['files'].values(), *b['libs'])})
    key = hashlib.sha256(json.dumps(dict(bindings=bindings, workloads=workloads), sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-gate-power' / key
    work.mkdir(parents=True, exist_ok=False)
    hierarchy = dict(top=dict(module=TOP, run=str(top['completion'])),
                     blocks=[dict(module=b['design'], instance=b['instance'], run=str(b['completion'])) for b in blocks],
                     partition=str(part['completion']), signoff=str(signoff_path))
    result = dict(status='HOLD', platform='gpu', bindings=bindings, corner=CORNER, frequency_hz=FREQUENCY_HZ, records=[],
                  hierarchy=hierarchy, lineage=lineage,
                  window='reset release to end of the one-case command (whole kernel launch sequence)',
                  boundary='GPU core die only: top level (std cells, clock/repair buffers) + four quadrant hard blocks '
                           '(mapped Vortex + command/memory adapters + OpenRAM macros); host, external DRAM and board power excluded',
                  double_counting='blocks are measured from their own netlists and SPEF; at the top they are abstract liberty '
                                  'models checked to carry no internal/leakage power groups, so the top part counts only '
                                  'top-level cells and the switching of top-level nets (block pin capacitance as load)')
    (work / 'inputs.json').write_text(json.dumps(dict(result, workloads=workloads), indent=2) + '\n')
    started = time.monotonic()
    try:
        engine = build_engine(work)
        replay_top = work / 'replay-top.v'
        reordered = replay_port_order(files['v'], part['flat_netlist'], replay_top)
        result['replay_port_order'] = dict(reference=str(part['flat_netlist']), reordered_ports=reordered,
                                           replay_netlist_sha256=sha(replay_top), note=replay_port_order.__doc__.strip())
        program = compile_netlist(work, replay_top, TOP, models, work / 'compile.log',
                                  modules=[f"{b['design']}={b['files']['v']}" for b in blocks])
        result['program'] = json.loads((program / 'summary.json').read_text())
        replays = []
        for w in workloads:
            label = f"{w['operator']}-seed{w['seed']:02d}"
            then = time.monotonic()
            traced = json.loads((activity / 'runs' / f"{w['ordinal']:04d}-c0" / 'record.json').read_text())
            reference = json.loads((baseline / 'runs' / f"{w['ordinal']:04d}-c0" / 'record.json').read_text())
            same = ('output', 'instructions', 'cycles', 'device_fault', 'device_launches')
            if not traced.get('complete') or any(traced.get(k) != reference.get(k) for k in same):
                raise ValueError(f'{label}: traced execution differs from the baseline execution')
            trace = activity / 'runs' / f"{w['ordinal']:04d}-c0" / 'port-trace.txt'
            begin = reset_release_cycle(trace, 'rst_ni')
            out = work / label
            out.mkdir()
            qualify = out / 'qualify.txt'
            write_qualifiers(qualify, trace_layout(trace), gpu_rule)
            sim = replay(engine, program, trace, out, 7200, begin_cycle=begin, qualify=qualify, check_from=begin)
            replays.append((w, out, trace, sim, reference, time.monotonic() - then))
            print(json.dumps(dict(replayed=label, checked_output_cycles=sim['checked_cycles'])), flush=True)
        clean, removed = sanitize_macro_libs(sorted(macro_libs.values()), work / 'power-libs')
        clean = {c.name: c for c in clean}
        result['macro_power'] = dict(internal_power_groups_removed=removed, note=sanitize_macro_libs.__doc__.strip())
        top_libs = abstract_libs + [clean[l.name] for l in top['libs'] if l not in abstract_libs]
        top_power = power(files['odb'], files['sdc'], files['spef'], top_libs, f'TOP/{TOP}',
                          [(out / 'window.saif', out) for _, out, *_ in replays], work / 'openroad-top.log')
        block_power = []
        for q, b in enumerate(blocks):
            dirs = []
            for _, out, *_ in replays:
                d = out / f'q{q}'
                d.mkdir()
                dirs.append(d)
            block_power.append(power(b['files']['odb'], b['files']['sdc'], b['files']['spef'], [clean[l.name] for l in b['libs']],
                                     f"TOP/{TOP}/{b['instance']}", [(out / 'window.saif', d) for (_, out, *_), d in zip(replays, dirs)],
                                     work / f'openroad-q{q}.log'))
        part_fields = ('total_mw', 'dynamic_mw', 'leakage_mw', 'annotated_pins', 'total_pins', 'annotation_percent',
                       'unannotated_pins', 'unannotated_percent')
        for i, (w, out, trace, sim, reference, seconds_sim) in enumerate(replays):
            window = sim['windows'][0]
            seconds = window['duration_ps'] * 1e-12
            parts = [top_power[i]] + [bp[i] for bp in block_power]
            total_mw = sum(p['total_mw'] for p in parts)
            annotated, pins = sum(p['annotated_pins'] for p in parts), sum(p['total_pins'] for p in parts)
            saif = gzip_file(out / 'window.saif')
            breakdown = {b['design']: dict({k: bp[i][k] for k in part_fields}, instance=b['instance'],
                                           netlist_sha256=sha(b['files']['v']), spef_sha256=sha(b['files']['spef']))
                         for b, bp in zip(blocks, block_power)}
            record = dict(w, input_sha256=hashlib.sha256(json.dumps(vectors[w['ordinal']]['inputs'], sort_keys=True).encode()).hexdigest(),
                          trace_sha256=sha(trace), activity_sha256=sha(saif), netlist_sha256=sha(files['v']), spef_sha256=sha(files['spef']),
                          begin_cycle=window['begin_cycle'], end_cycle=window['end_cycle'], begin_ns=window['begin_cycle'] * 10,
                          end_ns=window['end_cycle'] * 10, window_seconds=seconds, frequency_hz=FREQUENCY_HZ,
                          rtl_cycles_counter=reference['cycles'],
                          checked_output_cycles=sim['checked_cycles'], output_mismatches=sim['mismatched_cycles'],
                          macro_read_write_conflicts=sim['macro_read_write_conflicts'], total_toggles=window['total_toggles'],
                          macro_reads=dict(zip([x['name'] for x in result['program']['macro_instances']], window['macro_reads'])),
                          macro_writes=dict(zip([x['name'] for x in result['program']['macro_instances']], window['macro_writes'])),
                          total_mw=total_mw, dynamic_mw=sum(p['dynamic_mw'] for p in parts),
                          leakage_mw=sum(p['leakage_mw'] for p in parts),
                          annotated_pins=annotated, total_pins=pins, annotation_percent=100.0 * annotated / pins,
                          unannotated_pins=pins - annotated, unannotated_percent=100.0 * (pins - annotated) / pins,
                          unannotated_examples=[e for p in parts for e in p['unannotated_examples']][:20],
                          top_mw=top_power[i]['total_mw'], blocks_mw=total_mw - top_power[i]['total_mw'],
                          top={k: top_power[i][k] for k in part_fields}, blocks=breakdown,
                          power_w=total_mw / 1000, energy_j=total_mw / 1000 * seconds, replay_seconds=seconds_sim)
            result['records'].append(record)
            print(json.dumps({k: record[k] for k in ('operator', 'seed', 'total_mw', 'annotation_percent', 'checked_output_cycles')}), flush=True)
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('power input changed during execution')
        summary = {}
        for op in args.operators:
            rows = [r for r in result['records'] if r['operator'] == op]
            summary[op] = dict(seeds=len(rows), mean_total_mw=sum(r['total_mw'] for r in rows) / len(rows),
                               mean_dynamic_mw=sum(r['dynamic_mw'] for r in rows) / len(rows),
                               mean_leakage_mw=sum(r['leakage_mw'] for r in rows) / len(rows),
                               mean_energy_j=sum(r['energy_j'] for r in rows) / len(rows),
                               min_annotation_percent=min(r['annotation_percent'] for r in rows),
                               mean_top_mw=sum(r['top_mw'] for r in rows) / len(rows),
                               mean_block_mw={m: sum(r['blocks'][m]['total_mw'] for r in rows) / len(rows) for m in BLOCKS})
        result.update(summary=summary, status='GPU_GATE_POWER_STAGE_PASS',
                      reason='Per-seed routed hierarchical netlist activity (top + 4 quadrant blocks) replayed with zero output '
                             'mismatches; SPEF-based power of every part recorded')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic() - started
    result['artifacts'] = {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file() and p.name != 'gatesim'}
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])), flush=True)
    return 0 if result['status'] == 'GPU_GATE_POWER_STAGE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
