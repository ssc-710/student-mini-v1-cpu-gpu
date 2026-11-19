"""Top level of the four-quadrant GPU: the partition's top module with the four hardened blocks.

Inputs: the block directory written by prepare_student_mini_gpu_quadrants.py (summary.json,
top module in top.v of the block directory) and, for every block, the completion.json of
its passing physical run (abstract LEF + liberty timing model).  Writes top.v, the block
placement (each block at its quadrant origin, rows left only in the cross channel and the chip
edge strips), the SDC (the GPU constraint with the chip-I/O clock latency of the blocks'
budgets plus the top clock tree) and config.mk.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_student_mini_gpu_quadrants import TOP_MET5_OFFSET  # noqa: E402


# single-input, non-logic cells a feedthrough chain inside a block may consist of (the inverting ones flip polarity)
CHAIN_CELL = re.compile(r'^sky130_fd_sc_hd__(buf|clkbuf|bufbuf|dlygate4sd\d|dlymetal6s\ds|clkdlybuf4s\d+|inv|clkinv|clkinvlp)_\d+$')


def block_drivers(netlist):
    """Module ports and the buffer/inverter/assign drivers of a block's final netlist: net -> (input net, inverting, cell)."""
    text = netlist.read_text()
    ports = {}
    for mm in re.finditer(r'^\s*(input|output)\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);', text, re.M):
        for n in mm.group(4).split(','):
            if n.strip():
                ports[n.strip()] = mm.group(1)
    drivers = {}
    for mm in re.finditer(r'^\s*assign\s+(\S+)\s*=\s*(\S+)\s*;', text, re.M):
        drivers[mm.group(1)] = (mm.group(2), False, 'assign')
    for mm in re.finditer(r'^\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\((.*?)\);', text, re.M | re.S):
        cell = CHAIN_CELL.match(mm.group(1))
        if not cell:
            continue
        pins = dict(re.findall(r'\.(\w+)\(([^()]*)\)', mm.group(3)))
        out = pins.get('X') or pins.get('Y')
        if 'A' in pins and out:
            drivers[out.strip()] = (pins['A'].strip(), cell.group(1).startswith(('inv', 'clkinv')), f'{mm.group(2)}:{mm.group(1)}')
    return ports, drivers


def direct_chip_feedthroughs(top_text, insts, netlists):
    """Logic-equivalent top-level rewiring: a block input fed at the top by another block's output that is only a
    buffer/inverter feedthrough of a chip input (e.g. rst_ni threaded through the quadrants by the partition) is
    connected to that chip input directly (through one top-level inverter when the chain inverts), so the signal
    no longer crosses the other blocks in series.  Returns the new top text and the rewiring record."""
    blocks = {inst: block_drivers(path) for inst, path in zip(insts, netlists)}
    chip_inputs = set()
    for mm in re.finditer(r'^\s*input\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);', top_text, re.M):
        for n in mm.group(3).split(','):
            if n.strip() and not mm.group(1):
                chip_inputs.add(n.strip())
    conns = {}  # inst -> {port: top net}
    for inst in insts:
        body = re.search(r'^\s*\S+\s+' + re.escape(inst) + r'\s*\((.*?)\);', top_text, re.M | re.S).group(1)
        conns[inst] = dict(re.findall(r'\.(\S+?)\(([^()]*)\)', body))
    top_driver = {net: (inst, port) for inst in insts for port, net in conns[inst].items()
                  if blocks[inst][0].get(port) == 'output'}

    def resolve(net, depth=0):
        # (chip input, inverted, chain) that the top net is a pure feedthrough of, or None
        if net in chip_inputs:
            return net, False, []
        if net not in top_driver or depth > 8:
            return None
        inst, port = top_driver[net]
        ports, drivers = blocks[inst]
        cur, inv, chain = port, False, []
        for _ in range(1000):
            if ports.get(cur) == 'input':
                up = resolve(conns[inst].get(cur), depth + 1)
                return None if up is None else (up[0], up[1] != inv, up[2] + [f'{inst}/{c}' for c in chain])
            if cur not in drivers:
                return None
            cur, flips, cell = drivers[cur]
            inv ^= flips
            chain.append(cell)
        return None

    record, new_text, inverters = [], top_text, {}
    for inst in insts:
        for port, net in conns[inst].items():
            if blocks[inst][0].get(port) != 'input' or net not in top_driver:
                continue
            found = resolve(net)
            if not found:
                continue
            chip, inverted, chain = found
            if inverted:
                inverters.setdefault(chip, f'{chip}_top_inv')
            source = inverters[chip] if inverted else chip
            body_re = re.compile(r'(^\s*\S+\s+' + re.escape(inst) + r'\s*\(.*?)\.' + re.escape(port) + r'\(' + re.escape(net) + r'\)', re.M | re.S)
            new_text, n = body_re.subn(lambda m: m.group(1) + f'.{port}({source})', new_text, count=1)
            if n != 1:
                raise ValueError(f'cannot rewire {inst}.{port}')
            record.append(dict(block=inst, port=port, old_net=net, source=chip, inverted=inverted, chain=chain))
    if inverters:
        decl = ''.join(f' wire {n};\n' for n in inverters.values())
        cells = ''.join(f' sky130_fd_sc_hd__inv_4 {n}_cell (.A({chip}),\n    .Y({n}));\n' for chip, n in inverters.items())
        new_text = re.sub(r'\n(\s*\S+\s+' + re.escape(insts[0]) + r'\s*\()', '\n' + decl + cells + r'\1', new_text, count=1)
    return new_text, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks', type=Path, required=True)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--block-runs', type=Path, nargs=4, help='completion.json of q0 q1 q2 q3 (LL LR UL UR)')
    src.add_argument('--orfs-results', type=Path, nargs=4,
                     help='exploration only: ORFS results directories of q0..q3 holding <module>.lef and <module>_typ.lib')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--io-latency', type=float, default=4.5,
                        help='chip I/O virtual clock latency (ns): the blocks see 2.5 ns at their clock pin, which the top tree reaches after ~2 ns (= the flat GPU constraint, 4.5)')
    args = parser.parse_args()
    summary = json.loads((args.blocks / 'summary.json').read_text())
    # top module as written by prepare_student_mini_gpu_quadrants.py (cut ports already renamed)
    text = (args.blocks / 'top.v').read_text()
    top = summary['top']
    m = re.search(r'^module ' + re.escape(top) + r'\b.*?^endmodule', text, re.S | re.M)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    top_text = m.group(0)
    if args.block_runs:
        insts = [summary['blocks'][n]['module'] + '_inst' for n in ('LL', 'LR', 'UL', 'UR')]
        netlists = [Path(json.loads(r.read_text())['result_directory']) / '6_final.v' for r in args.block_runs]
        top_text, rewired = direct_chip_feedthroughs(top_text, insts, netlists)
        (out / 'feedthrough_rewiring.json').write_text(json.dumps(rewired, indent=2) + '\n')
    (out / 'top.v').write_text(top_text + '\n')
    lefs, libs, place = [], [], ['# Hardened quadrant blocks at their quadrant origins.']
    names = ('LL', 'LR', 'UL', 'UR')
    for q in range(4):
        module = summary['blocks'][names[q]]['module']
        if args.block_runs:
            run = args.block_runs[q]
            done = json.loads(run.read_text())
            if done.get('status') != 'PLATFORM_PHYSICAL_ROUTE_STAGE_PASS' or 'abstract' not in done:
                raise ValueError(f'block {names[q]} has no passing hardened run: {run}')
            lef, lib = Path(done['abstract']['lef']), Path(done['abstract']['lib'])
            # the runner verified that no signal wire of the route or any antenna round uses met5
            if done.get('max_routing_layer') != 'met4':
                raise ValueError(f'block {names[q]} run was not restricted to met4 signal routing')
            route_log = None
        else:
            d = args.orfs_results[q].resolve()
            lef, lib = d / f'{module}.lef', d / f'{module}_typ.lib'
            route_log = Path(str(d).replace('/results/', '/logs/')) / '5_2_route.log'
        for f in (lef, lib, *([route_log] if route_log else [])):
            if not f.is_file():
                raise ValueError(f'block {names[q]}: missing {f}')
        # met5 of a block carries only its power stripes (MAX_ROUTING_LAYER met4): the met5
        # obstruction of the abstract is dropped so the top met5 grid can meet the met5 pins
        if route_log:
            met5 = re.findall(r'Total wire length on LAYER met5 = (\d+) um', route_log.read_text(errors='replace'))
            if not met5 or int(met5[-1]) != 0:
                raise ValueError(f'block {names[q]} routes signals on met5: {met5[-1:] or "unknown"} um')
        text_lef, n = re.subn(r'\n    LAYER met5 ;\n     RECT [^\n]*;', '', lef.read_text(), count=1)
        if n != 1 or 'LAYER met5' not in text_lef.split('  OBS')[0]:
            raise ValueError(f'block {names[q]}: unexpected abstract met5 layout in {lef}')
        (out / lef.name).write_text(text_lef)
        lefs.append(str(out / lef.name))
        libs.append(str(lib))
        x, y = summary['blocks'][names[q]]['origin']
        inst = f'{module}_inst'
        place.append(f'place_macro -macro_name {{{inst}}} -location {{{x:.3f} {y:.3f}}} -orientation R0 -exact')
    place.append('cut_rows -halo_width_x 2 -halo_width_y 2')
    # chip pins on the die edge at the y of the block's chip-edge pin (straight met3 stub)
    io = ['# Chip pins aligned with the chip-edge pins of the quadrant blocks.']
    count, placed, edge_ys = 0, set(), []
    for q in range(4):
        f = args.blocks / f'q{q}_{names[q]}' / 'chip_pins.json'
        for p in (json.loads(f.read_text()) if f.is_file() else []):
            io.append(f"place_pin -pin_name {{{p['port']}}} -layer met3 -location {{{p['die_x']:.3f} {p['y']:.3f}}} -pin_size {{1.0 0.3}}")
            placed.add(p['port'])
            edge_ys.append((p['die_x'], p['y']))
            count += 1
    # chip ports whose receivers all left the chip-edge block (e.g. rst_ni after partition moves) reach a
    # block only through a channel-edge pin: they get fixed slots on the same die edge just past the
    # chip-pin window, two met3 tracks apart, and the top level routes them along the edge strip
    ports = []
    for mm in re.finditer(r'^\s*(input|output)\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);', m.group(0), re.M):
        for n in mm.group(4).split(','):
            n = n.strip()
            if n:
                ports += [f'{n}[{i}]' for i in range(int(mm.group(3)), int(mm.group(2)) + 1)] if mm.group(2) else [n]
    extra = [p for p in ports if p not in placed]
    if extra:
        die_x, top_y = edge_ys[0][0], max(y for _, y in edge_ys)
        for k, port in enumerate(extra):
            io.append(f'place_pin -pin_name {{{port}}} -layer met3 -location {{{die_x:.3f} {top_y + 2.72 + 1.36 * k:.3f}}} -pin_size {{1.0 0.3}}')
            count += 1
    (out / 'io.tcl').write_text('\n'.join(io) + '\n', newline='\n')
    (out / 'macro-placement.tcl').write_text('\n'.join(place) + '\n', newline='\n')
    sdc = (ROOT / 'integration/student-mini/gpu_constraint.sdc').read_text()
    sdc = re.sub(r'set_clock_latency \S+ \[get_clocks io_clock\]', f'set_clock_latency {args.io_latency} [get_clocks io_clock]', sdc)
    (out / 'constraint.sdc').write_text(sdc, newline='\n')
    die = summary['die']
    (out / 'config.mk').write_text('\n'.join([
        'export PLATFORM = sky130hd',
        f'export DESIGN_NAME = {top}',
        f'export SYNTH_NETLIST_FILES = {out / "top.v"}',
        f'export VERILOG_FILES = {out / "top.v"}',
        f'export SDC_FILE = {out / "constraint.sdc"}',
        f'export DIE_AREA = 0 0 {die:g} {die:g}',
        f'export CORE_AREA = 10 10 {die - 10:g} {die - 10:g}',
        f'export MACRO_PLACEMENT_TCL = {out / "macro-placement.tcl"}',
        f'export ADDITIONAL_LEFS = {" ".join(lefs)}',
        f'export ADDITIONAL_LIBS = {" ".join(libs)}',
        f'export IO_CONSTRAINTS = {out / "io.tcl"}',
        f'export PDN_TCL = {ROOT / "integration/student-mini/gpu_top_pdn.tcl"}',
        f'export POST_PDN_TCL = {ROOT / "integration/student-mini/gpu_top_pdn_bridge.tcl"}',
        f'export STUDENT_MINI_TOP_MET5_OFFSET = {TOP_MET5_OFFSET:.2f}',
        'export PLACE_DENSITY = 0.30',
        # chip ports wire straight to block pins that the blocks already buffer
        'export DONT_BUFFER_PORTS = 1',
        f'export PRE_RESIZE_TCL = {ROOT / "integration/student-mini/gpu_top_skip_empty_metrics.tcl"}',
        f'export PRE_DETAIL_PLACE_TCL = {ROOT / "integration/student-mini/gpu_top_skip_empty_metrics.tcl"}',
        'export GLOBAL_ROUTE_ARGS = -congestion_report_iter_step 5 -allow_congestion',
        f'export PRE_GLOBAL_ROUTE_TCL = {ROOT / "integration/student-mini/grt_allow_congestion.tcl"}',
        # clock tree to the four block clock pins: one leaf per block, buffered long wires, balanced levels, and a
        # buffer right at every block clk_i (gpu_top_clock_pin_buffers.tcl); without it one buffer drove three
        # blocks over ~1 mm of top wire and the slow edge failed the blocks' half-cycle paths (full-chip STA 2026-10-14)
        'export CTS_ARGS = -sink_clustering_enable -repair_clock_nets -sink_clustering_size 1 -sink_clustering_max_diameter 50 '
        '-macro_clustering_size 1 -macro_clustering_max_diameter 50 -distance_between_buffers 300 -balance_levels',
        f'export POST_CTS_TCL = {ROOT / "integration/student-mini/gpu_top_clock_pin_buffers.tcl"}',
        'export NUM_CORES = 8', '']), newline='\n')
    print(json.dumps(dict(out=str(out), top=top, chip_pins=count, blocks=[str(p) for p in (args.block_runs or args.orfs_results)],
                          sha256=hashlib.sha256((out / 'config.mk').read_bytes()).hexdigest())))


if __name__ == '__main__':
    main()
