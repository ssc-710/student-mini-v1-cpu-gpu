"""Path-based boundary budgets for the four-quadrant GPU (block-level static timing).

Every block contributes its timing abstract (integration/student-mini/gpu_block_abstract_timing.tcl):
reg_out (register -> output port arrival), in_reg (input port -> register time) and ft
(input -> output combinational delays).  On the graph of cut nets (one node per net: driver
output port, receiver input ports, cross-channel delay c):
    A(n) = max(reg_out(o_n), max_{i -> o_n} A(net(i)) + c + d(i, o_n))      arrival at the crossing
    R(n) = min over receivers i of  min(T - in_reg(i), min_{i -> o} R(net(o)) - d(i, o)) - c
    X(n) = A(n) + (R(n) - A(n)) / 2
A block on a feed-through chain then receives exactly its measured in->out delay, the launching
and the capturing block share the path slack, and the budgets of a chain are consistent.
Nets with R < A have negative path slack: no budget closes them; they are listed.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks', type=Path, required=True, help='directory with q*_*/budgets.json and abstract/ timing files')
    parser.add_argument('--abstract', default='abstract', help='sub-directory of each block holding reg_out/in_reg/ft.tsv')
    parser.add_argument('--period', type=float, default=10.0)
    parser.add_argument('--channel-delay', type=float, default=0.15)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dump', type=Path, help='also write {net: [A, R]}')
    args = parser.parse_args()
    T, c = args.period, args.channel_delay
    norm = lambda s: s.replace('\\', '')
    out_port = {}                      # net -> (block, port)
    in_ports = defaultdict(list)       # net -> [(block, port)]
    reg_out, in_reg = {}, {}           # (block, port) -> value
    ft_from = defaultdict(list)        # (block, in port) -> [(out port, d)]
    ft_to = defaultdict(list)          # (block, out port) -> [(in port, d)]
    for bdir in sorted(args.blocks.glob('q*_*')):
        b = bdir.name
        ports = {norm(p['port']): p for p in json.loads((bdir / 'budgets.json').read_text())}
        for p in ports.values():
            key = (b, norm(p['port']))
            if p['side'] == 'out':
                out_port[p['net']] = key
            else:
                in_ports[p['net']].append(key)
        a = bdir / args.abstract
        for line in (a / 'reg_out.tsv').read_text().splitlines():
            n, v = line.split('\t')
            # a port reached only through feed-throughs reports the -100 ns isolation delay: no register path
            if float(v) > -50:
                reg_out[(b, norm(n))] = float(v)
        for line in (a / 'in_reg.tsv').read_text().splitlines():
            n, v = line.split('\t')
            if float(v) > -50:
                in_reg[(b, norm(n))] = float(v)
        for line in (a / 'ft.tsv').read_text().splitlines():
            i, o, d = line.split('\t')
            ft_from[(b, norm(i))].append((norm(o), float(d)))
            ft_to[(b, norm(o))].append((norm(i), float(d)))
    port_net = {}
    for n, k in out_port.items():
        port_net[k] = n
    for n, ks in in_ports.items():
        for k in ks:
            port_net[k] = n
    sys.setrecursionlimit(100000)
    A, R, state = {}, {}, {}

    def arrival(n):
        if n in A:
            return A[n]
        if state.get(n) == 'a':
            raise ValueError('combinational loop through cut net ' + n)
        state[n] = 'a'
        o = out_port.get(n)
        v = reg_out.get(o, -1e9) if o else -1e9
        for i, d in ft_to.get(o, []):
            src = port_net.get((o[0], i))
            if src is not None:
                v = max(v, arrival(src) + c + d)
        if v < -1e8:
            v = 0.0
        A[n] = v
        return v

    def required(n):
        if n in R:
            return R[n]
        if state.get(n) == 'r':
            raise ValueError('combinational loop through cut net ' + n)
        state[n] = 'r'
        v = 1e9
        for k in in_ports.get(n, []):
            r = T - in_reg[k] if k in in_reg else 1e9
            for o, d in ft_from.get(k, []):
                dst = port_net.get((k[0], o))
                if dst is not None:
                    r = min(r, required(dst) - d)
            v = min(v, r - c)
        if v > 1e8:
            v = T
        R[n] = v
        return v

    nets = set(out_port) | set(in_ports)
    budgets, negative = {}, []
    for n in nets:
        a, r = arrival(n), required(n)
        budgets[n] = round(a + (r - a) / 2, 3)
        if r < a:
            negative.append((round(r - a, 3), n))
    args.out.write_text(json.dumps(budgets, indent=0) + '\n')
    if args.dump:
        args.dump.write_text(json.dumps({n: [round(A[n], 3), round(R[n], 3)] for n in nets}) + '\n')
    negative.sort()
    print(json.dumps(dict(nets=len(budgets), feedthrough_edges=sum(len(v) for v in ft_from.values()),
                          negative_path_slack=len(negative), worst=negative[:10], out=str(args.out))))


if __name__ == '__main__':
    main()
