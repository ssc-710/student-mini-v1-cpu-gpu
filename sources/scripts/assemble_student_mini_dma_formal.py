"""Bind bounded DMA proof and reachable success/error witnesses, not a SoC PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha


def assemble(prefix):
    roots = {task: Path(str(prefix) + '_' + task) for task in ('bmc', 'cover')}
    sources = [ROOT / 'shared/rtl/litex_native_dma_bridge.sv',
               ROOT / 'shared/rtl/student_mini_native_dma_bridge.sv',
               ROOT / 'shared/formal/student_mini_native_dma_protocol_harness.sv']
    for task, folder in roots.items():
        status = (folder / 'status').read_text().split()
        if not status or status[0] != 'PASS':
            raise ValueError(f'{task} did not pass')
        for source in sources:
            if sha(source) != sha(folder / 'src' / source.name):
                raise ValueError(f'{task} source changed: {source.name}')
        log = (folder / 'logfile.txt').read_text()
        if 'DONE (PASS' not in log:
            raise ValueError('incomplete formal transcript')
    covers = (roots['cover'] / 'logfile.txt').read_text()
    if covers.count('reached cover statement ') != 2:
        raise ValueError('both successful and error responses must be reachable')
    files = sources + [Path(__file__), ROOT / 'shared/formal/student_mini_native_dma_protocol.sby']
    for folder in roots.values():
        files += [p for p in folder.rglob('*') if p.is_file()]
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    identity = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    report = dict(schema_version=1, status='PASS', kind='bounded-rtl-protocol',
                  scope='student_mini_native_dma_bridge only; not full Wishbone/LiteDRAM/CPU protocol qualification',
                  depth=32, engine='smtbmc boolector', reachable_response_kinds=2,
                  formal_baseline=False, mutation_qualified=False,
                  assumptions=['initial reset', 'request stable while stalled',
                               'native read response presented only when ready'],
                  bindings=bindings)
    output = ROOT / 'grading/evidence/student-mini-v1/protocol' / identity
    output.mkdir(parents=True, exist_ok=False)
    path = output / 'dma-bounded.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(path=str(path), sha256=sha(path), status=report['status'], formal_baseline=False)))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    assemble(args.prefix.resolve())
