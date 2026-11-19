"""Block and top inputs for the four-quadrant GPU implementation.

Input: the output of integration/student-mini/gpu_quadrant_partition.tcl (quad.v,
nets.tsv, ports.tsv, macros.tsv) taken on the placed flat quadrant-ring design.
For every quadrant q (0 LL, 1 LR, 2 UL, 3 UR) this writes a block directory with
  * the block netlist (module vortex_physical_top_part{q}_q, gate level -> ORFS
    SYNTH_NETLIST_FILES, no re-synthesis),
  * its die (the quadrant minus half the cross channel; origin on the 15.64 um
    M1-M4 track-grid quantum, so macro track phase and pin tracks match the top),
  * macro placement relative to the block origin (+ rows cut around macros),
  * fixed pins: inter-block nets on the channel-facing edges at the position the
    flat placement implies (both blocks of an adjacent pair share the coordinate, so
    the top-level route is a straight hop across the channel); chip ports on the
    chip edge where the flat design had them; clock/reset next to the channel cross,
  * an SDC with per-port budgets from flat STA: a net whose driver has arrival A and
    slack S gives the driving block the output budget T - A - S/2 and the receiving
    block the input delay A + S/2 (S < 0 split as 0), all against a virtual io_clock
    whose latency approximates the block's own clock-tree insertion delay;
and a top directory with the top netlist and the block placement.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FLOW = '/home/soclab/src/orfs-clean-aabf2a/flow'
QUANTUM = 15.64
NAMES = ('LL', 'LR', 'UL', 'UR')


def snap_up(v):
    return -(-v // QUANTUM) * QUANTUM


def snap_down(v):
    return (v // QUANTUM) * QUANTUM


def split_modules(text):
    mods = {}
    for m in re.finditer(r'^module (\S+?)\s*\((.*?)^endmodule', text, re.S | re.M):
        mods[m.group(1)] = m.group(0)
    return mods


def dedupe_ports(module_text):
    """write_partition_verilog emits one port (header entry and declaration) per connected pin;
    keep one per name.  Returns (text, conflicts) where conflicts lists names declared with
    different directions."""
    head, rest = module_text.split(';', 1)
    name, plist = head.split('(', 1)
    seen, ports = set(), []
    for p in plist.rstrip(') \n').split(','):
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            ports.append(p)
    directions, out, conflicts = {}, [], []
    for line in rest.split('\n'):
        m = re.match(r'^\s*(input|output|inout)\s*(\[\d+:\d+\])?\s*([^;\s]+)\s*;\s*$', line)
        if m:
            key = m.group(3)
            if key in directions:
                if directions[key] != m.group(1):
                    conflicts.append(key)
                continue
            directions[key] = m.group(1)
        out.append(line)
    # An escaped identifier ends at whitespace: keep a space before the separator.
    text = name + '(' + ',\n    '.join(x + ' ' if x.startswith('\\') else x for x in ports) + ');' + '\n'.join(out)
    return text, conflicts


# Chip-level phase of the top-level met5 VDD stripe centres (mod 27.2 um) produced by
# integration/student-mini/gpu_top_pdn.tcl with offset TOP_MET5_OFFSET on the 7400 um die
# (measured: top offset 13.6 -> phase 10.88; the phase moves 1:1 with the offset).
MET5_PITCH = 27.2
TOP_MET5_OFFSET = 2.04
TOP_MET5_PHASE = 26.52


def met5_offset(block_y0):
    """Block PDN met5 offset that puts the block's met5 stripes on the top-level ones: inside a
    block (core inset 10 um, rows from 10.88) the VDD stripe centres sit at offset - 2.72 (mod pitch)."""
    return round((TOP_MET5_PHASE + 2.72 - block_y0) % MET5_PITCH, 3)


def sanitize_ports(mods):
    """Rename the escaped cut-net ports (\\part_a.b[3] ) to plain identifiers (part_a_b_3_) in every
    module, the top included.  Escaped names with brackets do not survive the liberty timing model
    of a hardened block (the reader takes them for bus bits).  Returns {plain: original}."""
    pat = re.compile(r'\\(part_\S+)(?=\s)')
    names, words = set(), set()
    for t in mods.values():
        names.update(pat.findall(t))
        words.update(re.findall(r'\b[A-Za-z_][A-Za-z0-9_$]*\b', t))
    mapping, used = {}, set(words)
    for n in sorted(names):
        s = base = re.sub(r'[^A-Za-z0-9_]', '_', n)
        k = 1
        while s in used:
            s, k = f'{base}_{k}', k + 1
        used.add(s)
        mapping[n] = s
    for k, t in mods.items():
        mods[k] = pat.sub(lambda m: mapping[m.group(1)], t)
    return {v: k for k, v in mapping.items()}


def port_list(module_text):
    """[(name, direction, msb, lsb)] of a written partition module."""
    ports = []
    for m in re.finditer(r'^\s*(input|output|inout)\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);', module_text, re.M):
        for name in m.group(4).split(','):
            name = name.strip()
            if name:
                ports.append((name, m.group(1), int(m.group(2)) if m.group(2) else None, int(m.group(3)) if m.group(3) else None))
    return ports


def legalize(wanted, lo, hi, pitch, forbidden):
    """Assign distinct grid slots in [lo, hi] outside forbidden spans, close to the wanted coordinates."""
    slots = []
    x = snap_up(lo) if False else lo
    k = int(-(-lo // pitch))
    while k * pitch <= hi:
        v = k * pitch
        if not any(a <= v <= b for a, b in forbidden):
            slots.append(v)
        k += 1
    order = sorted(range(len(wanted)), key=lambda i: wanted[i])
    if len(order) > len(slots):
        raise ValueError(f'{len(order)} pins do not fit {len(slots)} slots')
    # Forward greedy, then pull back so the last pins still fit.
    result = [None] * len(wanted)
    import bisect
    pos = 0
    picks = []
    for rank, i in enumerate(order):
        j = max(pos, bisect.bisect_left(slots, wanted[i]))
        j = min(j, len(slots) - (len(order) - rank))
        picks.append(j)
        pos = j + 1
    for rank, i in enumerate(order):
        result[i] = slots[picks[rank]]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partition', type=Path, required=True, help='gpu_quadrant_partition.tcl output directory')
    parser.add_argument('--flat-config', type=Path, required=True, help='config.mk of the flat quadrant design')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--die', type=float, default=6800.0)
    parser.add_argument('--channel', type=float, default=100.0)
    parser.add_argument('--inset', type=float, default=15.64, help='block distance from the chip edge (um)')
    parser.add_argument('--period', type=float, default=10.0)
    parser.add_argument('--io-latency', type=float, default=2.5, help='expected block clock insertion delay (ns)')
    parser.add_argument('--pin-pitch', type=float, nargs=2, default=(1.36, 0.92), metavar=('VERT_EDGE', 'HORZ_EDGE'))
    parser.add_argument('--budgets', type=Path, help='JSON {net: X ns}; default X = period/2 for every cut net')
    parser.add_argument('--channel-delay', type=float, default=0.15, help='cross-channel wire allowance (ns)')
    parser.add_argument('--fallback-latency', type=float, default=2.7,
                        help='block clock-tree latency of the flat-STA budget of a cut net missing from --budgets (ns)')
    parser.add_argument('--flat-budgets', type=float, metavar='LATENCY',
                        help='derive budgets from flat STA (arrival + LATENCY + slack/2) instead of --budgets')
    parser.add_argument('--keepout', type=float, default=40.0, help='pin keep-out beyond a near-edge macro (um)')
    parser.add_argument('--setup-margin', type=float, default=0.2,
                        help='SETUP_SLACK_MARGIN (ns) of the blocks\' timing repair.  Repair runs on placement/global-route '
                             'parasitic estimates, which read 0.4-0.5 ns optimistic against the extracted (RCX) SPEF of the '
                             'routed blocks; final runs use 0.6 so repair aims past that gap')
    parser.add_argument('--rc-scale', type=float,
                        help='calibrated wire RC (integration/student-mini/rc_calibrated.tcl) for the parasitic estimates '
                             'of placement, resizing, CTS and global-route repair: every layer R and C times this factor '
                             '(1.1 matches the final RCX SPEF of the routed blocks)')
    parser.add_argument('--pull-flops', action='append', default=[], metavar='BLOCK:GLOB[,GLOB...]',
                        help='POST_GLOBAL_PLACE hook (integration/student-mini/gpu_block_pull_flops.tcl) pulling the '
                             'matching capture flops to the far end of their D-input chain, '
                             'e.g. UL:*icache*core_rsp_queue*data_out_r*')
    parser.add_argument('--timing-gpl-blocks', nargs='*', default=['LR', 'UL'], choices=NAMES,
                        help='blocks placed with stronger timing-driven net reweighting (half-cycle SRAM read paths: '
                             'LR dcache bank, UL icache array)')
    parser.add_argument('--compact-banks', nargs='*', default=[], choices=('LL', 'LR', 'UL', 'UR'),
                        help='blocks whose eight dcache slices are re-placed as a 2x4 cluster next to the channel')
    parser.add_argument('--keepout-reach', type=float, default=250.0, help='macro distance from an edge that triggers a keep-out (um)')
    args = parser.parse_args()
    part = args.partition.resolve()
    budgets = json.loads(args.budgets.read_text()) if args.budgets else {}
    flat_latency = args.flat_budgets
    text = (part / 'quad.v').read_text()
    mods = split_modules(text)
    top_name = next(n for n in mods if not n.endswith(tuple(f'_q{q}' for q in range(4))))
    conflicts = {}
    for n in list(mods):
        if n != top_name:
            mods[n], bad = dedupe_ports(mods[n])
            conflicts[n] = bad
    if any(conflicts.values()):
        raise ValueError('ports with conflicting directions: ' + json.dumps({k: v[:5] for k, v in conflicts.items() if v}))
    original_port = sanitize_ports(mods)
    fallback_nets = 0
    dense_edges = []
    d, half = args.die, args.channel / 2
    c = d / 2
    # Block boxes in chip coordinates (origins on the track quantum).
    x0 = [snap_up(args.inset), snap_up(c + half)]
    x1 = [snap_down(c - half), snap_down(d - args.inset)]
    y0, y1 = x0, x1
    boxes = {0: (x0[0], y0[0], x1[0], y1[0]), 1: (x0[1], y0[0], x1[1], y1[0]),
             2: (x0[0], y0[1], x1[0], y1[1]), 3: (x0[1], y0[1], x1[1], y1[1])}
    nets = {}
    for line in (part / 'nets.tsv').read_text().splitlines():
        f = line.split('\t')
        parts = {}
        for item in f[5:]:
            q, n, x, y = item.split(':')
            parts[int(q)] = (int(n), float(x), float(y))
        nets[f[0].replace('\\', '')] = dict(driver=int(f[1]), arrival=float(f[2]), slack=float(f[3]), chip_ports=int(f[4]), parts=parts)
    chip = {}
    for line in (part / 'ports.tsv').read_text().splitlines():
        name, io, a, b, cc, dd = line.split('\t')
        chip[name.replace('\\', '')] = (io, (float(a) + float(cc)) / 2, (float(b) + float(dd)) / 2)
    macros = [l.split('\t') for l in (part / 'macros.tsv').read_text().splitlines()]
    # Macro views as ORFS resolves them for the flat design (the flat config sets the SRAM liberty
    # through an include: copying only literal export lines silently dropped ADDITIONAL_LIBS, and the
    # blocks then timed the SRAMs as black boxes).
    keep = []
    for name in ('PLATFORM', 'PRE_PDN_TCL', 'ADDITIONAL_LEFS', 'ADDITIONAL_LIBS'):
        printed = subprocess.run(['make', '-s', '-C', FLOW, f'DESIGN_CONFIG={args.flat_config.resolve()}', f'COURSE_ROOT={ROOT}',
                                  f'print-{name}'], capture_output=True, text=True, check=True).stdout
        found = re.search(r'^' + name + r': ?(.*)$', printed, re.M)
        value = ' '.join(found.group(1).split()) if found else ''
        if not value:
            raise ValueError(f'flat config resolves no {name}')
        if name.startswith('ADDITIONAL_') or name == 'PRE_PDN_TCL':
            missing = [t for t in value.split() if not Path(t).is_file()]
            if missing:
                raise ValueError(f'{name} names a missing file: {missing[0]}')
        keep.append(f'export {name} = {value}')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for q in range(4):
        mod = f'{top_name}_part{q}_q' if f'{top_name}_part{q}_q' in mods else next(n for n in mods if n.endswith(f'_q{q}') or n.endswith(f'part{q}_q'))
        bx0, by0, bx1, by1 = boxes[q]
        w, h = bx1 - bx0, by1 - by0
        right_side, upper_side = q in (1, 3), q in (2, 3)
        vert_edge_x = 0.0 if right_side else w            # local x of the channel-facing vertical edge
        horz_edge_y = 0.0 if upper_side else h            # local y of the channel-facing horizontal edge
        bdir = out / f'q{q}_{NAMES[q]}'
        bdir.mkdir(exist_ok=True)
        (bdir / 'block.v').write_text(mods[mod] + '\n')
        mine = [m for m in macros if int(m[2]) == q]
        if NAMES[q] in args.compact_banks:
            # The flat ring spreads a dcache bank's eight data slices along two block edges; the bank's
            # read mux is then up to ~3 mm from the farthest slice (falling-edge SRAM read data has half a
            # cycle).  Re-place the slices as two rows of four in the bottom corner next to the vertical
            # channel, read pins (top edge) facing the logic.
            slices = sorted((m for m in mine if m[1] == 'vortex_sp_64x128_w8'),
                            key=lambda m: int(re.search(r'g_data_slice\\\[(\d+)\\\]', m[0]).group(1)))
            if len(slices) != 8:
                raise ValueError(f'{NAMES[q]}: compact-banks expects 8 dcache slices, found {len(slices)}')
            moved = {}
            for k, m in enumerate(slices):
                row, col = divmod(k, 4)
                lx = 60.25 + col * 594.32 if right_side else w - 60.25 - 543.9 - (3 - col) * 594.32
                ly = 94.4 + row * 453.56
                moved[m[0]] = [m[0], m[1], m[2], f'{lx + bx0:.3f}', f'{ly + by0:.3f}', 'R0']
            mine = [moved.get(m[0], m) for m in mine]
        forbid_v, forbid_h, unmatched = [], [], []
        lines = ['# Macro placement relative to the block origin (from the flat quadrant ring).']
        for name, master, _, mx, my, orient in mine:
            lx, ly = float(mx) - bx0, float(my) - by0
            lines.append(f'place_macro -macro_name {{{name}}} -location {{{lx:.3f} {ly:.3f}}} -orientation {orient} -exact')
        sizes = {'vortex_dp_80x64_w4': (616.18, 272.69), 'vortex_sp_32x1024_w4': (700.26, 661.19),
                 'vortex_sp_32x256_w1': (491.18, 383.405), 'vortex_sp_64x128_w8': (543.9, 394.21)}
        # Rows between side-by-side macros: a gap that the 25 um row-cut halo leaves as a few-site-wide,
        # mm-long sliver collects repair buffers that detailed placement cannot legalize (DPL-0033, UL with
        # two SRAM columns; a placement blockage over the sliver crashes DPL instead).  The x halo grows
        # until every such gap (< 110 um) is cut completely.
        rects = [(float(mx) - bx0, float(my) - by0, *sizes[master]) for _, master, _, mx, my, _ in mine]
        halo_x = 25.0
        for ax, ay, aw, ah in rects:
            for bx, by, bw, bh in rects:
                gap = bx - (ax + aw)
                if 2 * halo_x < gap < 110 and min(ay + ah, by + bh) > max(ay, by):
                    halo_x = math.ceil(gap / 2 + 1)
        # same for a strip between a macro and the core's left/right edge (core = die - 10 um) that the
        # halo would leave narrower than 15 um (UL: column 1 at 34.6 um from the core edge)
        for ax, ay, aw, ah in rects:
            for gap in (ax - 10, (w - 10) - (ax + aw)):
                if halo_x < gap < halo_x + 15:
                    halo_x = math.ceil(gap + 1)
        lines.append(f'cut_rows -halo_width_x {halo_x:g} -halo_width_y 61')
        for name, master, _, mx, my, orient in mine:
            mw, mh = sizes[master]
            lx, ly = float(mx) - bx0, float(my) - by0
            # macro close to the vertical channel edge -> no pins along its y extent (+ clearance)
            if min(abs(lx - (0.0 if right_side else w)), abs(lx + mw - (0.0 if right_side else w))) < args.keepout_reach:
                forbid_v.append((ly - args.keepout, ly + mh + args.keepout))
            if min(abs(ly - (0.0 if upper_side else h)), abs(ly + mh - (0.0 if upper_side else h))) < args.keepout_reach:
                forbid_h.append((lx - args.keepout, lx + mw + args.keepout))
        (bdir / 'macro-placement.tcl').write_text('\n'.join(lines) + '\n', newline='\n')
        # Pins.  Names: write_partition_verilog emits escaped identifiers (\\part_a.b[3] ) for
        # cut nets whose names contain brackets; OpenDB keeps them as part_a.b\\[3\\], bus bits
        # as name[i].  Matching uses the name without backslashes.
        ports = port_list(mods[mod])
        vert, horz, outer, sdc, budget_ports = [], [], [], [], []
        for name, direction, msb, lsb in ports:
            escaped = name.startswith('\\')
            raw = name.lstrip('\\')
            if msb is None:
                bits = [(raw, raw.replace('[', '\\[').replace(']', '\\]') if escaped else raw)]
            else:
                bits = [(f'{raw}[{i}]', f'{raw}[{i}]') for i in range(min(msb, lsb), max(msb, lsb) + 1)]
            for bit, sdc_name in bits:
                flat_name = original_port.get(bit, bit)
                net_name = flat_name[len('part_'):] if flat_name.startswith('part_') else flat_name
                info = nets.get(net_name)
                if bit in chip and info is not None and q in info['parts'] and _inside(chip[bit][1:], boxes[q], 40):
                    outer.append((bit, chip[bit][2] - by0))              # chip port on this block's chip edge
                elif bit in ('clk_i', 'rst_ni') or info is None:
                    unmatched.append(bit) if info is None and bit not in chip else None
                    horz.append((bit, (w - 30.0) if not right_side else 30.0, True))
                else:
                    own = info['parts'].get(q, (0, bx0 + w / 2, by0 + h / 2))
                    others = [v for k, v in info['parts'].items() if k != q]
                    ox = sum(v[1] for v in others) / max(len(others), 1)
                    oy = sum(v[2] for v in others) / max(len(others), 1)
                    cross_x = any((k % 2) != (q % 2) for k in info['parts'] if k != q)
                    cross_y = any((k // 2) != (q // 2) for k in info['parts'] if k != q)
                    if cross_x and (not cross_y or abs(c - own[1]) <= abs(c - own[2])):
                        vert.append((bit, (own[2] + oy) / 2 - by0, False))
                    else:
                        horz.append((bit, (own[1] + ox) / 2 - bx0, False))
                # nets without a timing path in the flat design (infinite slack) stay unconstrained
                if info is not None and info['driver'] >= 0 and bit not in chip and info['slack'] < 1e29:
                    # X = time of the boundary crossing after the clock edge at the block clock pins
                    # (the top clock tree delivers the clock to all four blocks with matched delay).
                    if flat_latency is not None:
                        # path-consistent first budgets from flat placement STA: crossing time = flat driver
                        # arrival + expected block clock-tree latency + half the (non-negative) flat slack
                        x = round(max(info['arrival'], 0.0) + flat_latency + max(info['slack'], 0.0) / 2, 3)
                    else:
                        # nets cut for the first time (no path budget yet): flat-STA estimate
                        x = budgets.get(net_name)
                        if x is None:
                            x = round(max(info['arrival'], 0.0) + args.fallback_latency + max(info['slack'], 0.0) / 2, 3)
                            fallback_nets += 1
                    if info['driver'] == q:
                        sdc.append(f'set_output_delay {args.period - x:.3f} -clock core_clock [get_ports {{{sdc_name}}}]')
                    else:
                        sdc.append(f'set_input_delay {x + args.channel_delay:.3f} -clock core_clock [get_ports {{{sdc_name}}}]')
                    budget_ports.append(dict(port=sdc_name, net=net_name, side='out' if info['driver'] == q else 'in', x=x))
        margin = 70.0
        # Channel-edge pins two routing tracks apart; an edge with more pins than that holds
        # falls back to one-track spacing: vertical edges (met3) at 0.68 um, horizontal edges
        # alternating met2/met4 at half pitch (still two tracks apart on each layer).
        try:
            pv = legalize([v[1] for v in vert], margin, h - margin, args.pin_pitch[0], forbid_v)
        except ValueError:
            pv = legalize([v[1] for v in vert], margin, h - margin, args.pin_pitch[0] / 2, forbid_v)
            dense_edges.append(f'{NAMES[q]}:vertical')
        horz_layer = 'met2'
        try:
            ph = legalize([v[1] for v in horz], margin, w - margin, args.pin_pitch[1], forbid_h)
        except ValueError:
            ph = legalize([v[1] for v in horz], margin, w - margin, args.pin_pitch[1] / 2, forbid_h)
            horz_layer = None
            dense_edges.append(f'{NAMES[q]}:horizontal')
        # chip edge: one met3 track, as in the flat design; the clock input (wide NDR clock wire after
        # CTS) gets its slot with three free tracks on each side
        po = []
        if outer:
            clk = [i for i, (bit, _) in enumerate(outer) if bit == 'clk_i']
            clk_forbid = []
            if clk:
                clk_y = legalize([outer[clk[0]][1]], 20.0, h - 20.0, 0.68, [])[0]
                clk_forbid = [(clk_y - 2.05, clk_y + 2.05)]
            rest = [i for i in range(len(outer)) if i not in clk]
            ys = legalize([outer[i][1] for i in rest], 20.0, h - 20.0, 0.68, clk_forbid)
            po = [None] * len(outer)
            for i, y in zip(rest, ys):
                po[i] = y
            if clk:
                po[clk[0]] = clk_y
        io = ['# Fixed block pins (channel-facing edges; chip ports on the chip edge), keyed by the',
              '# port name without backslashes and applied to the matching OpenDB port.',
              'set student_mini_pins [dict create]']
        for (bit, _, _), y in zip(vert, pv):
            io.append(f'dict set student_mini_pins {{{bit}}} {{met3 {vert_edge_x:.3f} {y:.3f} 1.0 0.3}}')
        for (bit, _, _), x in zip(horz, ph):
            layer = horz_layer or ('met2' if round(x / (args.pin_pitch[1] / 2)) % 2 == 0 else 'met4')
            io.append(f'dict set student_mini_pins {{{bit}}} {{{layer} {x:.3f} {horz_edge_y:.3f} 0.3 1.0}}')
        # chip ports sit on the chip edge the block touches (left or right, wherever the flat
        # design put the I/O window), never on a channel-facing edge
        chip_x = 0.0 if outer and chip[outer[0][0]][1] < d / 2 else w
        for (bit, _), y in zip(outer, po):
            io.append(f'dict set student_mini_pins {{{bit}}} {{met3 {chip_x:.3f} {y:.3f} 1.0 0.3}}')
        # chip-port pins in chip coordinates, for the top level (same y on the die edge)
        (bdir / 'chip_pins.json').write_text(json.dumps(
            [dict(port=bit, x=round(bx0 + chip_x, 3), y=round(by0 + y, 3), die_x=0.0 if chip_x == 0.0 else d)
             for (bit, _), y in zip(outer, po)]) + '\n')
        io += ['set student_mini_placed 0',
               'foreach bt [[ord::get_db_block] getBTerms] {',
               '  set key [regsub -all {\\\\} [$bt getName] {}]',
               '  if {![dict exists $student_mini_pins $key]} { continue }',
               '  lassign [dict get $student_mini_pins $key] layer x y sx sy',
               '  place_pin -pin_name [$bt getName] -layer $layer -location [list $x $y] -pin_size [list $sx $sy]',
               '  incr student_mini_placed',
               '}',
               'puts "STUDENT_MINI_PINS_PLACED $student_mini_placed of [dict size $student_mini_pins]"',
               'if {$student_mini_placed != [dict size $student_mini_pins]} { error "block pins not all matched" }']
        (bdir / 'io.tcl').write_text('\n'.join(io) + '\n', newline='\n')
        sdc_text = [f'# Block budgets from flat STA (see scripts/prepare_student_mini_gpu_quadrants.py).',
                    f'create_clock -name core_clock -period {args.period:.3f} [get_ports clk_i]',
                    f'create_clock -name io_clock -period {args.period:.3f}',
                    f'set_clock_latency {args.io_latency:.3f} [get_clocks io_clock]']
        for b, _ in outer:
            kind = chip.get(b, ('',))[0]
            if kind == 'INPUT' and b != 'clk_i':
                sdc_text.append(f'set_input_delay 0.5 -clock io_clock [get_ports {{{b}}}]')
            elif kind == 'OUTPUT':
                sdc_text.append(f'set_output_delay 0.5 -clock io_clock [get_ports {{{b}}}]')
        (bdir / 'constraint.sdc').write_text('\n'.join(sdc_text + sdc) + '\n', newline='\n')
        (bdir / 'budgets.json').write_text(json.dumps(budget_ports) + '\n')
        (bdir / 'config.mk').write_text('\n'.join(
            ['export PLATFORM = sky130hd', f'export DESIGN_NAME = {mod}',
             f'export PRE_PDN_TCL = {ROOT / "ppa/openram/connect_openram_power.tcl"}',
             f'export SYNTH_NETLIST_FILES = {bdir / "block.v"}',
             f'export VERILOG_FILES = {bdir / "block.v"}',
             f'export SDC_FILE = {bdir / "constraint.sdc"}',
             f'export DIE_AREA = 0 0 {w:.2f} {h:.2f}',
             f'export CORE_AREA = 10 10 {w - 10:.2f} {h - 10:.2f}',
             f'export MACRO_PLACEMENT_TCL = {bdir / "macro-placement.tcl"}',
             f'export IO_CONSTRAINTS = {bdir / "io.tcl"}',
             'export PLACE_DENSITY = 0.30',
             'export SKIP_INCREMENTAL_REPAIR = 0',
             'export SKIP_CTS_REPAIR_TIMING = 0',
             # SRAM read data leaves ~3 ns after the falling edge: repair aims past zero and buffers long
             # resistive SRAM-output nets early (tighter cap/slew limits)
             f'export SETUP_SLACK_MARGIN = {args.setup_margin:g}',
             'export CAP_MARGIN = 20',
             'export SLEW_MARGIN = 20',
             # half-cycle SRAM read nets span a quadrant: reweight more critical nets, harder, more often
             *(['export GLOBAL_PLACEMENT_ARGS = -timing_driven_net_weight_max 10 -timing_driven_nets_percentage 20'
                ' -timing_driven_net_reweight_overflow {79 64 49 35 20}'] if NAMES[q] in args.timing_gpl_blocks else []),
             # met5 = power only (block pins); its stripes land on the top-level met5 stripes
             f'export PDN_TCL = {ROOT / "integration/student-mini/gpu_block_pdn.tcl"}',
             f'export STUDENT_MINI_BLOCK_MET5_OFFSET = {met5_offset(by0):.2f}',
             'export MAX_ROUTING_LAYER = met4',
             # residual local GRT overflow is left to detailed routing (sign-off requires DRC 0)
             'export GLOBAL_ROUTE_ARGS = -congestion_report_iter_step 5 -allow_congestion',
             *([f'export PRE_GLOBAL_ROUTE_TCL = {ROOT / "integration/student-mini/grt_allow_congestion.tcl"}']
               if args.rc_scale is None else
               [f'export PRE_GLOBAL_ROUTE_TCL = {ROOT / "integration/student-mini/pre_global_route_calibrated.tcl"}',
                *(f'export PRE_{step}_TCL = {ROOT / "integration/student-mini/rc_calibrated.tcl"}'
                  for step in ('GLOBAL_PLACE', 'RESIZE', 'CTS')),
                f'export STUDENT_MINI_RC_SCALE = {args.rc_scale:g}']),
             *[line for spec in args.pull_flops if spec.split(':', 1)[0] == NAMES[q] for line in (
                 f'export POST_GLOBAL_PLACE_TCL = {ROOT / "integration/student-mini/gpu_block_pull_flops.tcl"}',
                 'export STUDENT_MINI_PULL_PATTERN = ' + ' '.join(spec.split(':', 1)[1].split(',')))],
             'export NUM_CORES = 8', *keep]) + '\n', newline='\n')
        summary[NAMES[q]] = dict(module=mod, origin=[bx0, by0], size=[w, h], macros=len(mine), unmatched_ports=len(unmatched),
                                 vertical_edge_pins=len(vert),
                                 horizontal_edge_pins=len(horz), chip_edge_pins=len(outer), budgets=len(sdc),
                                 cells=len(re.findall(r'^\s*sky130_fd_sc_hd__\S+\s', mods[mod], re.M)))
    (out / 'top.v').write_text(mods[top_name] + '\n' + ''.join(f'(* blackbox *) module {summary[NAMES[q]]["module"]}(); endmodule\n'
                                                              for q in range(4) if False))
    (out / 'common.mk').write_text('\n'.join(keep) + '\n')
    (out / 'summary.json').write_text(json.dumps(dict(top=top_name, die=d, channel=args.channel, boxes=boxes,
                                                      blocks=summary), indent=2) + '\n')
    summary['fallback_budget_ports'] = fallback_nets
    summary['one_track_pin_edges'] = dense_edges
    print(json.dumps(summary))


def _inside(point, box, tol):
    x, y = point
    return box[0] - tol <= x <= box[2] + tol and box[1] - tol <= y <= box[3] + tol


if __name__ == '__main__':
    main()
