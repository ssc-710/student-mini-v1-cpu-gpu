"""Private source overlay for an independently tested SRT timing candidate."""
from pathlib import Path
import re
from scripts.student_mini_gpu_physical_replay_sources import overlay_configure

CONFIGS='-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_XLEN=32 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_FDIV_LATENCY=30 -DVX_CFG_FSQRT_LATENCY=30'


def overlay_source_collector(text):
    """Follow only the private overlay's links; preserve upstream checkout."""
    targets={'find "$dir" -maxdepth 1 -type f':2,
             'find "$(realpath "$1")" -maxdepth 1 -type f':1}
    for original,count in targets.items():
        if text.count(original)!=count:raise ValueError('upstream source collector changed')
        text=text.replace(original,original.replace('find ','find -L ',1))
    return text


def checked_config(text):
    pairs=re.findall(r'^#define (VX_CFG_\w+) ([^\n]+)$',text,re.M)
    if len({key for key,_ in pairs})!=len(pairs):raise ValueError('duplicate resolved configuration')
    values=dict(pairs)
    # XLEN is an explicit compiler/configure argument, not an emitted TOML
    # property. The actual resolver emits FLEN; do not invent an XLEN field.
    expected=dict(VX_CFG_NUM_CORES='1',VX_CFG_NUM_WARPS='2',VX_CFG_NUM_THREADS='4',VX_CFG_FLEN='32',
        VX_CFG_L2_ENABLED='0',VX_CFG_ICACHE_ENABLED='1',VX_CFG_DCACHE_ENABLED='1',VX_CFG_LMEM_ENABLED='1',
        VX_CFG_FPU_TYPE='STD',VX_CFG_FDIV_LATENCY='30',VX_CFG_FSQRT_LATENCY='30')
    if any(values.get(key)!=value for key,value in expected.items()):raise ValueError('retimed mini configuration differs')
    return values


def create_overlay(source,destination,cut):
    source=Path(source).resolve();destination=Path(destination)
    if destination.exists():raise FileExistsError('preserve existing source overlay')
    if cut.count('module VX_fdivsqrt_step_cut import')!=1 or 'localparam NR_STAGES = NR_BITS;' not in cut:
        raise ValueError('one-step SRT candidate required')
    replacements={'configure':overlay_configure((source/'configure').read_text()),
        'hw/scripts/gen_sources.sh':overlay_source_collector((source/'hw/scripts/gen_sources.sh').read_text()),
        'hw/rtl/fpu/VX_fdivsqrt_unit.sv':cut.replace('module VX_fdivsqrt_step_cut import','module VX_fdivsqrt_unit import')}
    def fill(relative):
        target=destination/relative;target.mkdir()
        for path in sorted((source/relative).iterdir()):
            if path.name=='.git':continue
            name=(Path(relative)/path.name).as_posix()
            output=destination/name
            if name in replacements:
                output.write_text(replacements[name])
                if name in ('configure','hw/scripts/gen_sources.sh'):output.chmod(0o755)
            elif any(key.startswith(name+'/') for key in replacements):fill(name)
            else:output.symlink_to(path,target_is_directory=path.is_dir())
    fill('')
    return list(replacements)
