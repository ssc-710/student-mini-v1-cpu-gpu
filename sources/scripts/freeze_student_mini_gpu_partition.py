"""Freeze the four-quadrant GPU partition as a bound stage for the guarded block runs.

The block netlists are written by integration/student-mini/gpu_quadrant_partition.tcl from the placed flat
GPU (ORFS on the frozen GPU synthesis) and prepared by scripts/prepare_student_mini_gpu_quadrants.py with the
converged boundary budgets.  This stage copies every generated block file into one content-addressed
directory, rewrites the block configs to point at the copies, binds the flat source, the scripts and the
forced-move list by SHA and checks that the four partitions together hold exactly the flat design's logic
cells (no cell lost or duplicated).  Its completion.json is the --parent of every GPU block run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

NAMES = ('q0_LL', 'q1_LR', 'q2_UL', 'q3_UR')
FILES = ('block.v', 'constraint.sdc', 'io.tcl', 'macro-placement.tcl', 'budgets.json', 'chip_pins.json', 'config.mk')


def cells(text):
    return re.findall(r'^\s*(sky130_fd_sc_hd__\S+|vortex_\S+)\s+(\S+)\s*\(', text, re.M)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks', type=Path, required=True, help='prepared block directory (closed budget pass)')
    parser.add_argument('--partition', type=Path, required=True, help='partition directory (quad.v, nets.tsv, partition.log)')
    parser.add_argument('--flat-config', type=Path, required=True)
    parser.add_argument('--flat-netlist', type=Path, required=True, help='placed flat netlist the partition was cut from (3_place.v)')
    parser.add_argument('--flat-parent', type=Path, required=True, help='completion.json of the GPU synthesis the flat run used')
    parser.add_argument('--moves', type=Path, required=True)
    parser.add_argument('--budgets', type=Path, required=True)
    parser.add_argument('--macro-moves', type=Path, help='STUDENT_MINI_MACRO_MOVES the partition was cut with (relocated macros)')
    args = parser.parse_args()
    parent = json.loads(args.flat_parent.read_text())
    if not parent.get('status', '').endswith('PASS') and not parent.get('status', '').endswith('READY'):
        raise ValueError('flat GPU source has no passing synthesis stage')
    blocks, part = args.blocks.resolve(), args.partition.resolve()
    scripts = [ROOT / 'integration/student-mini/gpu_quadrant_partition.tcl', ROOT / 'scripts/prepare_student_mini_gpu_quadrants.py',
               ROOT / 'scripts/student_mini_gpu_path_budgets.py', ROOT / 'integration/student-mini/gpu_block_pdn.tcl',
               ROOT / 'integration/student-mini/grt_allow_congestion.tcl',
               ROOT / 'integration/student-mini/gpu_block_pull_flops.tcl', ROOT / 'integration/student-mini/rc_calibrated.tcl',
               ROOT / 'integration/student-mini/pre_global_route_calibrated.tcl', Path(__file__)]
    bindings = {str(p): sha(p) for p in [args.flat_config.resolve(), args.flat_netlist.resolve(), args.flat_parent.resolve(),
                                         args.moves.resolve(), args.budgets.resolve(), part / 'quad.v', part / 'nets.tsv',
                                         part / 'macros.tsv', blocks / 'summary.json', blocks / 'top.v', *scripts]}
    if args.macro_moves:
        bindings[str(args.macro_moves.resolve())] = sha(args.macro_moves)
        placed = {f[0]: (float(f[3]), float(f[4]), f[5]) for f in
                  (l.split('\t') for l in (part / 'macros.tsv').read_text().splitlines() if l)}
        for line in filter(None, args.macro_moves.read_text().splitlines()):
            name, x, y, orient = line.split('\t')
            if name not in placed or abs(placed[name][0] - float(x)) > 0.01 or abs(placed[name][1] - float(y)) > 0.01 \
                    or placed[name][2] != orient:
                raise ValueError(f'partition was not cut with macro move {name}')
    for b in NAMES:
        for f in FILES:
            bindings[str(blocks / b / f)] = sha(blocks / b / f)
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-partition' / key
    work.mkdir(parents=True, exist_ok=True)
    # logic-cell conservation: the four partitions hold exactly the flat design's logic cells
    flat = {i.replace('\\', '') for _, i in cells(args.flat_netlist.read_text())
            if not re.search(r'tapvpwrvgnd|fill|decap', _)}
    split, per = set(), {}
    for b in NAMES:
        found = {i.replace('\\', '') for _, i in cells((blocks / b / 'block.v').read_text())}
        if split & found:
            raise ValueError(f'cells in more than one partition: {sorted(split & found)[:3]}')
        split |= found
        per[b] = len(found)
    if split != flat:
        raise ValueError(f'partition cells differ from the flat netlist: missing {sorted(flat - split)[:3]}, extra {sorted(split - flat)[:3]}')
    for b in NAMES:
        (work / b).mkdir(exist_ok=True)
        for f in FILES:
            text = (blocks / b / f).read_text()
            if f == 'config.mk':
                text = text.replace(str(blocks / b), str(work / b))
            (work / b / f).write_text(text, newline='\n')
    for f in ('summary.json', 'top.v'):
        shutil.copyfile(blocks / f, work / f)
    record = dict(status='GPU_PARTITION_STAGE_PASS', bindings=bindings, blocks=per, flat_logic_cells=len(flat),
                  artifacts={str(p.relative_to(work)): sha(p) for p in sorted(work.rglob('*')) if p.is_file()},
                  reason='four partitions hold exactly the flat logic cells; block files frozen with SHA')
    (work / 'completion.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=record['status'], blocks=per)))


if __name__ == '__main__':
    main()
