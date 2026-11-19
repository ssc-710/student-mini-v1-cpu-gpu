"""Compile a routed SKY130 gate netlist into a gatesim program (tools/gatesim/gatesim.cpp).

Cell behaviour comes only from the Liberty file: every output pin `function`,
`ff` groups (clocked_on / next_state / clear / preset), `latch` groups and the
`latch_posedge` clock-gating cells.  OpenRAM macros are modelled natively by
the engine (posedge input registers, negedge write then read) from the widths
declared in their behavioural models.  Physical-only cells (tap, fill, decap,
diode) have no function and are excluded from simulation; their pins are not
switched nets.

    compile --liberty LIB --netlist 6_final.v --top TOP [--macro-model M.v ...] --out DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

PHYSICAL = re.compile(r'sky130_fd_sc_hd__(tapvpwrvgnd|fill|decap|diode|tap)_\d+$')


# ---------------------------------------------------------------- Liberty
def liberty_cells(path: Path) -> dict:
    text = path.read_text()
    cells = {}
    for match in re.finditer(r'\n\s*cell \("?([\w]+)"?\)\s*\{', text):
        name = match.group(1)
        start = match.end()
        depth, i = 1, start
        while depth:
            c = text[i]
            depth += (c == '{') - (c == '}')
            i += 1
        body = text[start:i - 1]
        cells[name] = parse_cell(name, body)
    return cells


def groups(body: str, kind: str):
    for match in re.finditer(r'\b' + kind + r'\s*\(([^)]*)\)\s*\{', body):
        depth, i = 1, match.end()
        while depth:
            depth += (body[i] == '{') - (body[i] == '}')
            i += 1
        yield match.group(1), body[match.end():i - 1]


def attr(body: str, key: str):
    found = re.search(r'\b' + key + r'\s*:\s*"([^"]*)"', body)
    return found.group(1) if found else None


def top_level_only(body: str) -> str:
    """Strip nested groups (timing, power) so attributes are read at pin level."""
    out, depth = [], 0
    for c in body:
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif depth == 0:
            out.append(c)
    return ''.join(out)


def parse_cell(name: str, body: str) -> dict:
    cell = dict(name=name, inputs=[], outputs={}, ff=None, latch=None, icg=None, tristate=False)
    for pin, pbody in groups(body, 'pin'):
        pin = pin.strip().strip('"')
        level = top_level_only(pbody)
        direction = attr(level, 'direction') or re.search(r'direction\s*:\s*"?(\w+)', level).group(1)
        if direction == 'input':
            cell['inputs'].append(pin)
        elif direction == 'output':
            function = attr(level, 'function')
            if attr(level, 'three_state'):
                cell['tristate'] = True
            if attr(level, 'state_function'):
                function = attr(level, 'state_function')
            cell['outputs'][pin] = function
    for head, gbody in groups(body, 'ff'):
        names = [x.strip().strip('"') for x in head.split(',')]
        level = top_level_only(gbody)
        cell['ff'] = dict(vars=names, clocked_on=attr(level, 'clocked_on'), next_state=attr(level, 'next_state'),
                          clear=attr(level, 'clear'), preset=attr(level, 'preset'))
    for head, gbody in groups(body, 'latch'):
        names = [x.strip().strip('"') for x in head.split(',')]
        level = top_level_only(gbody)
        cell['latch'] = dict(vars=names, enable=attr(level, 'enable'), data_in=attr(level, 'data_in'),
                             clear=attr(level, 'clear'), preset=attr(level, 'preset'))
    gating = attr(top_level_only(body), 'clock_gating_integrated_cell')
    if gating:
        if gating not in ('latch_posedge', 'latch_posedge_precontrol'):
            raise ValueError(f'{name}: unsupported clock gating style {gating}')
        # latch_posedge ICG: M0 follows the enable while CLK is low.
        enable = [p for p in cell['inputs'] if p in ('GATE', 'SCE')]
        cell['icg'] = dict(enable='|'.join(enable), clock='CLK')
    return cell


TOKEN = re.compile(r'\s*([A-Za-z_][\w]*|[01]|[!&|*+^()\'])')


def parse_expr(text: str):
    """Liberty boolean expression -> nested tuples.  Precedence: ! ' > & * (space) > ^ > | +."""
    tokens = [t for t in TOKEN.findall(text)]
    if ''.join(tokens) != re.sub(r'\s+', '', text):
        raise ValueError('cannot tokenize ' + text)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def primary():
        t = take()
        if t == '!':
            return ('not', primary())
        if t == '(':
            e = orx()
            if take() != ')':
                raise ValueError('unbalanced ' + text)
            node = e
        elif t in ('0', '1'):
            node = ('const', int(t))
        else:
            node = ('var', t)
        while peek() == "'":
            take()
            node = ('not', node)
        return node

    def andx():
        node = primary()
        while peek() is not None and (peek() in ('&', '*') or peek() == '!' or peek() == '(' or re.match(r'[A-Za-z_01]', peek())):
            if peek() in ('&', '*'):
                take()
            node = ('and', node, primary())
        return node

    def xorx():
        node = andx()
        while peek() == '^':
            take()
            node = ('xor', node, andx())
        return node

    def orx():
        node = xorx()
        while peek() in ('|', '+'):
            take()
            node = ('or', node, xorx())
        return node

    tree = orx()
    if pos != len(tokens):
        raise ValueError('trailing tokens in ' + text)
    return tree


def variables(tree, out=None):
    out = [] if out is None else out
    if tree[0] == 'var':
        if tree[1] not in out:
            out.append(tree[1])
    elif tree[0] != 'const':
        for child in tree[1:]:
            variables(child, out)
    return out


def evaluate(tree, env):
    op = tree[0]
    if op == 'const':
        return tree[1]
    if op == 'var':
        return env[tree[1]]
    if op == 'not':
        return 1 - evaluate(tree[1], env)
    a, b = evaluate(tree[1], env), evaluate(tree[2], env)
    return a & b if op == 'and' else a | b if op == 'or' else a ^ b


def truth_table(text: str):
    tree = parse_expr(text)
    names = variables(tree)
    if len(names) > 6:
        raise ValueError('more than 6 inputs: ' + text)
    tt = 0
    for idx in range(1 << len(names)):
        env = {n: (idx >> i) & 1 for i, n in enumerate(names)}
        tt |= evaluate(tree, env) << idx
    return names, tt


# ---------------------------------------------------------------- netlist
def strip_name(token: str) -> str:
    token = token.strip()
    return token[1:].rstrip() if token.startswith('\\') else token


def split_top(text: str, sep: str = ','):
    """Split on sep outside braces/parentheses (escaped identifiers kept)."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(text):
        c = text[i]
        if c == '\\':
            j = i
            while j < len(text) and not text[j].isspace():
                j += 1
            cur.append(text[i:j] + ' ')
            i = j
            continue
        if c in '({':
            depth += 1
        elif c in ')}':
            depth -= 1
        if c == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append(''.join(cur))
    return parts


def statements(text: str):
    """Yield ';'-terminated statements, honouring escaped identifiers."""
    start, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            while i < n and not text[i].isspace():
                i += 1
            continue
        if c == ';':
            yield text[start:i]
            start = i + 1
        elif c == 'e' and text.startswith('endmodule', i) and (i == 0 or text[i - 1].isspace()):
            yield 'endmodule'
            i += len('endmodule')
            start = i
            continue
        i += 1


def lsb_first(name, hi, lo):
    """Bits of name[hi:lo], least significant (the right-hand index) first."""
    step = 1 if hi >= lo else -1
    return [f'{name}[{k}]' for k in range(lo, hi + step, step)]


class Netlist:
    def __init__(self):
        self.nets = {}
        self.names = []
        self.ports = {}           # name -> (direction, [bit names lsb first])
        self.port_order = []
        self.buses = {}           # declared range per identifier
        self.instances = []       # (type, name, {pin: [bit names lsb first]})
        self.assigns = []

    def bits(self, expr: str):
        """Bit names, LSB first, of one connection expression."""
        expr = expr.strip()
        if not expr:
            return []
        if expr.startswith('{'):
            items = split_top(expr[1:-1])
            out = []
            for item in reversed(items):
                out.extend(self.bits(item))
            return out
        const = re.fullmatch(r"(\d+)'([bh])([0-9a-fA-F_xz]+)", expr)
        if const:
            width, base, digits = int(const.group(1)), const.group(2), const.group(3).replace('_', '')
            value = int(digits.replace('x', '0').replace('z', '0'), 2 if base == 'b' else 16)
            return [f"1'b{(value >> i) & 1}" for i in range(width)]
        if expr.startswith('\\'):
            return [strip_name(expr)]
        sel = re.fullmatch(r'([A-Za-z_][\w$]*)\s*\[(\d+)(?::(\d+))?\]', expr)
        if sel:
            name, hi = sel.group(1), int(sel.group(2))
            lo = int(sel.group(3)) if sel.group(3) is not None else hi
            return lsb_first(name, hi, lo)
        if expr in self.buses:
            return lsb_first(expr, *self.buses[expr])
        return [expr]


def parse_netlist(path: Path, top: str) -> Netlist:
    text = path.read_text()
    # Yosys netlists carry (* attributes *) and comments; OpenROAD ones do not.
    text = re.sub(r'\(\*.*?\*\)', ' ', text, flags=re.S)
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'(?m)^\s*//.*$', '', text)
    nl = Netlist()
    in_top = False
    for stmt in statements(text):
        stmt = stmt.strip()
        if not stmt:
            continue
        if stmt.startswith('module '):
            in_top = re.match(r'module\s+([^\s(]+)', stmt).group(1) == top
            continue
        if stmt == 'endmodule' or not in_top:
            continue
        head = re.match(r'(input|output|inout|wire)\s*(?:\[(\d+):(\d+)\])?\s*(.*)$', stmt, re.S)
        if head:
            kind, hi, lo, rest = head.groups()
            for name in split_top(rest):
                name = strip_name(name)
                if not name:
                    continue
                if hi is not None:
                    nl.buses[name] = (int(hi), int(lo))
                if kind in ('input', 'output', 'inout'):
                    bits = nl.bits(name) if hi is not None else [name]
                    nl.ports[name] = (kind, bits)
                    nl.port_order.append(name)
            continue
        if stmt.startswith('assign '):
            lhs, rhs = stmt[len('assign '):].split('=', 1)
            nl.assigns.append((nl.bits(lhs), nl.bits(rhs)))
            continue
        inst = re.match(r'(\S+)\s+(\\\S+\s|\S+)\s*\((.*)\)\s*$', stmt, re.S)
        if not inst:
            raise ValueError('unparsed statement: ' + stmt[:200])
        cell, name, body = inst.group(1), strip_name(inst.group(2)), inst.group(3)
        pins = {}
        for conn in split_top(body):
            conn = conn.strip()
            if not conn:
                continue
            m = re.match(r'\.(\w+)\s*\((.*)\)\s*$', conn, re.S)
            if not m:
                raise ValueError(f'unparsed connection in {name}: {conn[:120]}')
            pins[m.group(1)] = nl.bits(m.group(2))
        nl.instances.append((cell, name, pins))
    return nl


def macro_shape(model: Path) -> dict:
    text = model.read_text()
    name = re.search(r'^module\s+(\w+)', text, re.M).group(1)
    get = lambda key: int(re.search(r'parameter\s+' + key + r'\s*=\s*(\d+)', text).group(1))
    nwm = get('NUM_WMASKS') if 'NUM_WMASKS' in text else 0
    return dict(name=name, dw=get('DATA_WIDTH'), aw=get('ADDR_WIDTH'), nwm=nwm)


def saif_name(name: str) -> str:
    """Escape a design object name the way Verilator SAIF does for OpenSTA."""
    return re.sub(r'([\[\]])', r'\\\1', name)


def count_cells(entries):
    return sum(1 if e[0] == 'I' else count_cells(e[3]) for e in entries)


def compile_program(args):
    cells = liberty_cells(args.liberty)
    shapes = {s['name']: s for s in (macro_shape(m) for m in args.macro_model)}
    nl = parse_netlist(args.netlist, args.top)
    ids = {}
    names = []

    def net(bit):
        if bit not in ids:
            ids[bit] = len(names)
            names.append(bit)
        return ids[bit]

    const0, const1 = net("1'b0"), net("1'b1")
    driver = {}
    elements, flops, macros = [], [], []
    skipped = {}

    def drive(n, who):
        if n in driver:
            raise ValueError(f'net {names[n]} has two drivers: {driver[n]} and {who}')
        driver[n] = who

    for name in nl.port_order:
        kind, bits = nl.ports[name]
        if kind == 'input':
            for b in bits:
                drive(net(b), 'port:' + name)
    subs = {}
    for spec in args.module_netlist:
        module, path = spec.split('=', 1)
        subs[module] = parse_netlist(Path(path), module)
    internal = [0]
    tree = []

    def place(nl, prefix, bind, out):
        """Instantiate nl's cells; bind maps the module's port bits to parent nets."""
        def lnet(bit):
            if bit in ("1'b0", "1'b1"):
                return net(bit)
            if bit in bind:
                return bind[bit]
            return net(prefix + bit)
        for lhs, rhs in nl.assigns:
            for a, b in zip(lhs, rhs):
                o = lnet(a)
                drive(o, prefix + 'assign')
                elements.append(dict(kind='C', out=o, fn=([lnet(b)], 0b10)))
        for cell_type, inst, pins in nl.instances:
            full = prefix + inst
            if cell_type in subs:
                sub = subs[cell_type]
                child, ports = {}, []
                for pname in sub.port_order:
                    kind, bits = sub.ports[pname]
                    conn = pins.get(pname, [])
                    if not conn and kind == 'output':
                        conn = [None] * len(bits)
                    if len(conn) != len(bits):
                        raise ValueError(f'{full}: port {pname} connects {len(conn)} of {len(bits)} bits')
                    for b, c in zip(bits, conn):
                        n = net(f'$gatesim$nc${full}${b}') if c is None else lnet(c)
                        child[b] = n
                        ports.append((b, n))
                children = []
                place(sub, full + '/', child, children)
                out.append(('D', inst, ports, children))
                continue
            if PHYSICAL.match(cell_type):
                skipped[cell_type] = skipped.get(cell_type, 0) + 1
                # Antenna diodes have an input pin on a switched net: annotate it.
                connected = [(p, lnet(bits[0])) for p, bits in pins.items() if bits]
                if connected:
                    out.append(('I', inst, connected))
                continue
            if cell_type in shapes:
                s = shapes[cell_type]
                get = lambda p, w: [lnet(b) for b in pins.get(p, [])] if w else []
                m = dict(name=full, model=cell_type, shape=s, clk0=lnet(pins['clk0'][0]), csb0=lnet(pins['csb0'][0]), clk1=lnet(pins['clk1'][0]),
                         csb1=lnet(pins['csb1'][0]), addr0=get('addr0', 1), wmask0=get('wmask0', s['nwm']), din0=get('din0', 1),
                         addr1=get('addr1', 1), dout1=get('dout1', 1))
                if len(m['addr0']) != s['aw'] or len(m['din0']) != s['dw'] or len(m['dout1']) != s['dw'] or len(m['wmask0']) != s['nwm']:
                    raise ValueError(f'macro {inst} pin widths differ from its model')
                for n in m['dout1']:
                    drive(n, full)
                macros.append(m)
                out.append(('I', inst, [(f'{p}[{i}]' if len(bits) > 1 else p, lnet(b)) for p, bits in pins.items() for i, b in enumerate(bits)]))
                continue
            if cell_type not in cells:
                raise ValueError(f'cell {cell_type} ({inst}) has no Liberty model')
            cell = cells[cell_type]
            if cell['tristate']:
                raise ValueError(f'tri-state cell {cell_type} is not supported')
            pin_net = {p: lnet(bits[0]) for p, bits in pins.items() if bits}
            # Output pins left unconnected (clock-load cells, spare tie outputs)
            # still switch their own output: give each a private net.
            for pin in cell['outputs']:
                if pin not in pin_net:
                    pin_net[pin] = net(f'$gatesim$nc${full}${pin}')
            local = dict(pin_net)
            state = cell['ff'] or cell['latch']
            if state or cell['icg']:
                internal[0] += 1
                iq = net(f'$gatesim$iq${internal[0]}')
                iqn = net(f'$gatesim$iqn${internal[0]}')
                if state:
                    local[state['vars'][0]] = iq
                    if len(state['vars']) > 1:
                        local[state['vars'][1]] = iqn
                else:
                    local['M0'] = iq
                drive(iq, full)
                drive(iqn, full)
                elements.append(dict(kind='C', out=iqn, fn=([iq], 0b01)))

                def fn(text):
                    if text is None:
                        return None
                    vars_, tt = truth_table(text)
                    missing = [v for v in vars_ if v not in local]
                    if missing:
                        raise ValueError(f'{inst}: unconnected {missing} in "{text}"')
                    return ([local[v] for v in vars_], tt)
                if cell['ff']:
                    ff = cell['ff']
                    clk = ff['clocked_on'].strip()
                    pol = 0 if clk.startswith('!') else 1
                    clk_pin = clk.lstrip('!').strip('() ')
                    if clk_pin not in pin_net:
                        raise ValueError(f'{inst}: unsupported clocked_on {clk}')
                    flops.append(dict(clk=pin_net[clk_pin], pol=pol, iq=iq, ns=fn(ff['next_state']), clr=fn(ff['clear']), pre=fn(ff['preset'])))
                elif cell['latch']:
                    la = cell['latch']
                    if la['clear'] or la['preset']:
                        raise ValueError(f'{inst}: latch clear/preset not supported')
                    elements.append(dict(kind='L', out=iq, en=fn(la['enable']), fn=fn(la['data_in'])))
                else:
                    elements.append(dict(kind='L', out=iq, en=fn('!' + cell['icg']['clock']), fn=fn(cell['icg']['enable'])))
            for pin, function in cell['outputs'].items():
                if pin not in pin_net:
                    continue
                if function is None:
                    raise ValueError(f'{cell_type}.{pin} has no function')
                vars_, tt = truth_table(function)
                ins = []
                for v in vars_:
                    if v not in local:
                        raise ValueError(f'{inst}: output {pin} uses unconnected {v}')
                    ins.append(local[v])
                drive(pin_net[pin], full)
                elements.append(dict(kind='C', out=pin_net[pin], fn=(ins, tt)))
            out.append(('I', inst, [(p, n) for p, n in pin_net.items()]))

    place(nl, '', {}, tree)
    # Levelize: sources (inputs, constants, flop state, macro outputs) are level 0.
    level = [0] * len(names)
    produced = {}
    for i, e in enumerate(elements):
        produced[e['out']] = i
    consumers = {}
    indeg = [0] * len(elements)
    for i, e in enumerate(elements):
        ins = list(e['fn'][0]) + (list(e['en'][0]) if e['kind'] == 'L' else [])
        for n in set(ins):
            if n in produced:
                consumers.setdefault(n, []).append(i)
                indeg[i] += 1
    ready = [i for i in range(len(elements)) if indeg[i] == 0]
    order = []
    while ready:
        i = ready.pop()
        order.append(i)
        e = elements[i]
        ins = list(e['fn'][0]) + (list(e['en'][0]) if e['kind'] == 'L' else [])
        e['level'] = 1 + max((level[n] for n in ins), default=0)
        level[e['out']] = e['level']
        for j in consumers.get(e['out'], []):
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
    if len(order) != len(elements):
        raise ValueError(f'combinational loop: {len(elements) - len(order)} elements unordered')
    undriven = sorted({n for e in elements for n in e['fn'][0] if n not in driver and n not in (const0, const1)}
                      | {n for f in flops for n in f['ns'][0] if n not in driver and n not in (const0, const1)})
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    fmt = lambda f: '-1' if f is None else f"{len(f[0])} {' '.join(map(str, f[0]))} {f[1]:x}".replace('  ', ' ')
    with (out / 'program.txt').open('w') as p:
        p.write(f'NETS {len(names)} {const0} {const1}\n')
        for name in nl.port_order:
            kind, bits = nl.ports[name]
            p.write(f'PORT {name} {len(bits)} ' + ' '.join(str(net(b)) for b in bits) + '\n')
        for i in order:
            e = elements[i]
            if e['kind'] == 'C':
                p.write(f"C {e['out']} {e['level']} {fmt(e['fn'])}\n")
            else:
                p.write(f"L {e['out']} {e['level']} {fmt(e['en'])} {fmt(e['fn'])}\n")
        for f in flops:
            p.write(f"F {f['clk']} {f['pol']} {f['iq']} {fmt(f['ns'])} {fmt(f['clr'])} {fmt(f['pre'])}\n")
        for m in macros:
            s = m['shape']
            p.write(f"M {s['dw']} {s['aw']} {max(s['nwm'], 1)} {m['clk0']} {m['csb0']} {m['clk1']} {m['csb1']} "
                    + ' '.join(map(str, m['addr0'])) + f" {len(m['wmask0'])} " + ' '.join(map(str, m['wmask0'] + m['din0'] + m['addr1'] + m['dout1'])) + '\n')
    with (out / 'saifmap.txt').open('w') as s:
        s.write(saif_name(args.top) + '\n')
        for name in nl.port_order:
            kind, bits = nl.ports[name]
            for b in bits:
                s.write(f'T {saif_name(b)} {net(b)}\n')
        def emit(entries):
            for e in entries:
                if e[0] == 'I':
                    s.write(f'I {saif_name(e[1])}\n')
                    for pin, n in e[2]:
                        s.write(f'P {saif_name(pin)} {n}\n')
                else:
                    s.write(f'D {saif_name(e[1])}\n')
                    for b, n in e[2]:
                        s.write(f'T {saif_name(b)} {n}\n')
                    emit(e[3])
                    s.write('X\n')
        emit(tree)
    summary = dict(top=args.top, nets=len(names), elements=len(elements), flops=len(flops), macros=len(macros),
                   macro_instances=[dict(name=m['name'], model=m['model']) for m in macros],
                   instances_simulated=count_cells(tree), physical_only_cells=skipped, max_level=max(level) if level else 0,
                   undriven_nets=len(undriven), undriven_examples=[names[n] for n in undriven[:20]],
                   ports={n: dict(direction=nl.ports[n][0], width=len(nl.ports[n][1])) for n in nl.port_order})
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'ports'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('compile')
    c.add_argument('--liberty', type=Path, required=True)
    c.add_argument('--netlist', type=Path, required=True)
    c.add_argument('--top', required=True)
    c.add_argument('--macro-model', type=Path, action='append', default=[])
    c.add_argument('--module-netlist', action='append', default=[], help='MODULE=routed netlist of a hard block')
    c.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.setrecursionlimit(10000)
    compile_program(args)


if __name__ == '__main__':
    main()
