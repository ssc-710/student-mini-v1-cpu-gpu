"""Bus-fault variant of prepare_student_mini_gpu.py (status-6 records load the unmapped window)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def prepare(input_dir):
    inputs=json.loads((input_dir/'manifest.json').read_text())
    for name,digest in inputs['bindings'].items():
        if sha(ROOT/name)!=digest:raise ValueError('stale input/kernel source')
    paths=[Path(__file__),ROOT/'integration/vortex/platform_full.cu',ROOT/'integration/vortex/student_mini_host_fault.inc',ROOT/'integration/vortex/device_compat.cc',ROOT/'software/student_mini_scalar.c',ROOT/'software/include/student_mini_scalar.h',ROOT/'software/include/numeric_luts.h',input_dir/'inputs.bin']
    bindings={str(p):sha(p) for p in paths};identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/gpu-fault'/identity;work.mkdir(parents=True,exist_ok=False)
    prefix=(ROOT/'integration/vortex/platform_full.cu').read_text().split('#include "../../software/include/platform_case_runtime.h"')[0]
    prefix=prefix.replace('../../software/include/numeric_luts.h',str(ROOT/'software/include/numeric_luts.h'))
    header=(ROOT/'software/include/student_mini_scalar.h').read_text().replace('void student_mini_execute','__device__ void student_mini_execute')
    body=(ROOT/'software/student_mini_scalar.c').read_text()
    body=re.sub(r'^#include .*\n','',body,flags=re.M)
    body=re.sub(r'^static ', '__device__ static ',body,flags=re.M)
    body=body.replace('void student_mini_execute','__device__ void student_mini_execute')
    # Keep sign/magnitude opaque to the locked SPIR-V optimizer, exactly as
    # the existing device numeric primitives do. Otherwise it emits s_abs
    # imports before the freestanding RV32 compatibility archive is linked.
    body=body.replace('n<0 ? (uint64_t)(-(n+1))+1u : (uint64_t)n',
                      'gpu_signed_magnitude_i64(n)')
    body=body.replace('memset(r,0,sizeof(*r));','for(unsigned zero=0;zero<sizeof(*r);++zero)((uint8_t *)r)[zero]=0;')
    (work/'student_mini.cu').write_text(prefix+'\n'+header+'\n'+body+'\n'+(ROOT/'integration/vortex/student_mini_host_fault.inc').read_text())
    (work/'device_compat.cc').write_bytes((ROOT/'integration/vortex/device_compat.cc').read_bytes())
    (work/'common.h').write_text('// No host oracle or expected output in this target.\n')
    # Existing build products remain untouched. configure and make run only in
    # this new tree, with the frozen source/toolchain paths passed explicitly.
    make=f'''VORTEX_BUILD := {work}/vortex-build
include $(VORTEX_BUILD)/config.mk
ROOT_DIR := $(VORTEX_BUILD)
VORTEX_RT_SRC := $(VORTEX_BUILD)/sw/runtime
VORTEX_RT_LIB := $(VORTEX_BUILD)/sw/runtime
VORTEX_KN_PATH := $(CURDIR)/kernel_compat
PROJECT := student_mini
SRCS := $(CURDIR)/student_mini.cu
HIPCC := $(TOOLDIR)/chipstar/bin/cucc
CONFIGS := -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4
HIPCC_FLAGS += -O2 -ffp-contract=off -fno-builtin -fno-builtin-abs -fno-builtin-labs
VX_CFLAGS += -O2 -ffp-contract=off -I$(VORTEX_BUILD)/sw
VX_LDFLAGS += $(CURDIR)/device_compat.o
include $(VORTEX_HOME)/tests/hip/common.mk
device_compat.o: device_compat.cc
\t$(RISCV_TOOLCHAIN_PATH)/bin/$(RISCV_PREFIX)-g++ -march=rv32imaf -mabi=ilp32f -O2 -ffreestanding -fno-builtin -fno-exceptions -fno-rtti -c $< -o $@
$(CURDIR)/kernel_compat/libvortex2.a: $(VORTEX_BUILD)/sw/kernel/libvortex2.a device_compat.o
\tmkdir -p $(CURDIR)/kernel_compat
\tcp $< $@
\t$(RISCV_TOOLCHAIN_PATH)/bin/$(RISCV_PREFIX)-gcc-ar rcs $@ device_compat.o
$(PROJECT): device_compat.o
'''
    (work/'Makefile').write_text(make)
    report=dict(status='HOLD',input_sha256=identity,bindings=bindings,input_directory=str(input_dir),config=dict(cores=1,warps=2,threads=4,l2=False),source_only=True)
    (work/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status='PREPARED_NOT_EXECUTED')))
    return work

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input-dir',type=Path,required=True);args=parser.parse_args();prepare(args.input_dir.resolve())
