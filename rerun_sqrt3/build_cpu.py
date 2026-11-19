"""Build the released native firmware on the released LiteX SoC, isolated outputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent/'sources'
sys.path.insert(0, str(ROOT))
os.cpu_count = lambda: 2
os.environ.update(COURSE_ROOT=str(ROOT), COURSE_NATIVE_IMAGE_DIR=str(HERE/'image'),
                  MAKEFLAGS='', PYTHONUNBUFFERED='1')
os.environ['PATH'] = str(Path(sys.executable).absolute().parent)+':'+os.environ['PATH']
# LiteX's generated BIOS Makefile invokes /usr/bin/python3 explicitly. Export
# the isolated site-packages so that helper modules (crcfbigen) resolve there.
site = Path(sys.prefix)/'lib/python3.12/site-packages'
os.environ['PYTHONPATH'] = str(site) + ':' + os.environ.get('PYTHONPATH','')
# LiteX's VexRiscv profile is RV32IMF.  Force the locked prebuilt RV32
# toolchain and its gcc-ar wrapper; using the host riscv64 binutils produces
# archives that the RV32 linker rejects.
tc = HERE/'tools/riscv32-gnu-toolchain/bin'
os.environ['PATH'] = str(tc)+':'+os.environ['PATH']
os.environ['TRIPLE'] = 'riscv32-unknown-elf'
# Use the system launcher on the ASCII rerun path; the prebuilt binary's
# resolved symlink points back through the Chinese workspace path, which makes
# Verilator's generated absolute include path invalid to GNU make.
os.environ['COURSE_VERILATOR_BIN'] = '/usr/bin/verilator'
core = HERE/'VexRiscv_Full_4k.v'
expected = '1ee38dc4b0f3a2ce08de9df1f8e2bb8fceb628a89adb7f624f38ae44cebe9fcc'
assert hashlib.sha256(core.read_bytes()).hexdigest() == expected, 'CPU RTL must match released hash'
destination = ROOT/'build/vexriscv-profiles/VexRiscv_Full_4k.v'
destination.parent.mkdir(parents=True, exist_ok=True)
if not destination.exists(): shutil.copy2(core, destination)
assert hashlib.sha256(destination.read_bytes()).hexdigest() == expected
from litex.soc.integration.builder import Builder
from integration.litex.soc import build_soc
original = Builder.add_software_package
def add_package(self, name, *args, **kwargs):
    if name == 'bios':
        return original(self, name, str(ROOT/'integration/litex/native_nano_bios'))
    return original(self, name, *args, **kwargs)
Builder.add_software_package = add_package
work = HERE/'cpu'
work.mkdir(exist_ok=True)
blob = (HERE/'image/image.bin').read_bytes()
loader = work/'loader.bin'
loader.write_bytes(blob + bytes((-len(blob))%1936))
build_soc(output_dir=work/'soc', run=False, cpu_b0=True, control_smoke=True,
          cpu_variant='full', student_mini_image=loader,
          student_mini_count=loader.stat().st_size//1936)
print('CPU_BUILD_COMPLETE', flush=True)
