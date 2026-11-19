"""Project the portable native C runtime into the locked Vortex device compiler.

Changes are limited to device annotations, existing integer helper aliases and
static scalar dispatch (SPIR-V does not accept C function-pointer callbacks).
The host launcher contains no inference or expected result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.preflight_student_mini_native_nano import TENSORS


def replace_once(source, old, new):
    if source.count(old)!=1:
        raise ValueError('native projection seam changed: '+old)
    return source.replace(old,new)


def project(header, body):
    header=re.sub(r'^int (mini_native_)',r'__device__ int \1',header,flags=re.M)
    body=re.sub(r'^#include .*\n','',body,flags=re.M)
    body=re.sub(r'^static ', '__device__ static ',body,flags=re.M)
    body=re.sub(r'^int (mini_native_)',r'__device__ int \1',body,flags=re.M)
    body=replace_once(body,'n<0 ? (uint64_t)(-(n+1))+1u : (uint64_t)n','gpu_signed_magnitude_i64(n)')
    body=replace_once(body,'memset(result,0,sizeof(*result));',
        'for(unsigned i=0;i<sizeof(*result);++i)((uint8_t *)result)[i]=0;')
    body=replace_once(body,'if(backend && (!backend->attention || !backend->expert)) return -1;',
        'if(backend) return -1; // This device projection has static scalar dispatch only.')
    body=replace_once(body,'mini_attention_fn attention=backend ? backend->attention : mini_native_scalar_attention;','')
    body=replace_once(body,'mini_expert_fn expert_fn=backend ? backend->expert : mini_native_scalar_expert;','')
    body=replace_once(body,'void *user=backend ? backend->user : 0;','void *user=0;')
    body=replace_once(body,'if(attention(user,','if(mini_native_scalar_attention(user,')
    body=replace_once(body,'if(expert_fn(user,expert,','if(mini_native_scalar_expert(user,expert,')
    body=replace_once(body,'|| expert_fn(user,2,','|| mini_native_scalar_expert(user,2,')
    body=replace_once(body,'if(backend && backend->step_complete) backend->step_complete(user,step,best);','')
    return header+'\n'+body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-dir',type=Path,required=True)
    args=parser.parse_args();image_dir=args.image_dir.resolve()
    manifest=json.loads((image_dir/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('contains_expected_tokens') is not False or sha(image_dir/'image.bin')!=manifest['image_sha256']:
        raise ValueError('unbound input-only image')
    paths=[Path(__file__),ROOT/'scripts/preflight_student_mini_native_nano.py',
        ROOT/'software/student_mini_native_nano.c',ROOT/'software/include/student_mini_native_nano.h',
        ROOT/'software/include/numeric_luts.h',ROOT/'integration/vortex/platform_full.cu',
        ROOT/'integration/vortex/student_mini_native_host.inc',ROOT/'integration/vortex/device_compat.cc',
        image_dir/'manifest.json',image_dir/'image.bin',image_dir/'student_mini_native_image.h']
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/native-gpu'/identity;work.mkdir(parents=True,exist_ok=False)
    prefix=(ROOT/'integration/vortex/platform_full.cu').read_text().split('#include "../../software/include/platform_case_runtime.h"')[0]
    prefix=prefix.replace('../../software/include/numeric_luts.h',str(ROOT/'software/include/numeric_luts.h'))
    device=project((ROOT/'software/include/student_mini_native_nano.h').read_text(),
                   (ROOT/'software/student_mini_native_nano.c').read_text())
    assigns=[]
    for i,name in enumerate(TENSORS):
        assigns.append(f'model.weight[{i}]=(const int8_t *)(image+{manifest["segments"]["weight."+name]["offset"]}); model.scale[{i}]=scales[{manifest["scale_index"][name]}];')
    host=(ROOT/'integration/vortex/student_mini_native_host.inc').read_text()
    host=replace_once(host,'// __NATIVE_MODEL_BINDINGS__','\n    '.join(assigns))
    image_header=(image_dir/'student_mini_native_image.h').read_text()
    (work/'native_nano.cu').write_text(prefix+'\n'+device+'\n'+image_header+
        f'\n#define COURSE_NATIVE_IMAGE_BYTES {manifest["size_bytes"]}\n'+host)
    (work/'device_compat.cc').write_bytes((ROOT/'integration/vortex/device_compat.cc').read_bytes())
    (work/'common.h').write_text('// Input-only native model, no expected answer.\n')
    make=f'''VORTEX_BUILD := {work}/vortex-build
include $(VORTEX_BUILD)/config.mk
ROOT_DIR := $(VORTEX_BUILD)
VORTEX_RT_SRC := $(VORTEX_BUILD)/sw/runtime
VORTEX_RT_LIB := $(VORTEX_BUILD)/sw/runtime
VORTEX_KN_PATH := $(CURDIR)/kernel_compat
PROJECT := native_nano
SRCS := $(CURDIR)/native_nano.cu
HIPCC := $(TOOLDIR)/chipstar/bin/cucc
CONFIGS := -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_FPU_TYPE=STD
HIPCC_FLAGS += -O2 -ffp-contract=off -fno-fast-math -fno-builtin -fno-builtin-abs -fno-builtin-labs
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
    artifacts={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'manifest.json').write_text(json.dumps(dict(status='HOLD',target_execution=False,
        bindings=bindings,artifacts=artifacts,image_directory=str(image_dir),
        input_only=True,config=dict(cores=1,warps=2,threads=4,l2=False,fpu='STD')),indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status='PREPARED_NOT_EXECUTED')))


if __name__=='__main__':main()
