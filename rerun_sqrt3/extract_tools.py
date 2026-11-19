"""Extract locked archives on Linux; keep outputs under the rerun directory."""
from pathlib import Path
import tarfile

here=Path(__file__).resolve().parent
tools=here/'tools'
tools.mkdir(exist_ok=True)
for name in ['llvm-vortex','riscv32-gnu-toolchain','chipstar','pocl','libcrt32','libc32','verilator']:
    stamp=tools/(name+'.extracted')
    if stamp.exists(): continue
    print('EXTRACTING', name, flush=True)
    with tarfile.open(here/'downloads'/(name+'.tar.bz2')) as t:
        t.extractall(tools,filter='data')
    stamp.touch()
if not (here/'vortex-source').exists():
    print('EXTRACTING vortex-source',flush=True)
    with tarfile.open(here/'downloads/vortex-b8c5a243.tar.gz') as t:
        t.extractall(here,filter='data')
    (here/'vortex-b8c5a24336026d9d029a67197160eee6b017f262').rename(here/'vortex-source')
print('EXTRACTION_COMPLETE',flush=True)
