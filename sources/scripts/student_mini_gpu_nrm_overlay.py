"""Configuration for the independently verified 31-cycle normalization cut."""
from scripts.student_mini_gpu_cut_overlay import create_overlay, checked_config as step_config

CONFIGS = ('-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_WARPS=2 -DVX_CFG_NUM_THREADS=4 '
           '-DVX_CFG_XLEN=32 -DVX_CFG_FPU_TYPE=STD '
           '-DVX_CFG_FDIV_LATENCY=31 -DVX_CFG_FSQRT_LATENCY=31')


def checked_config(text):
    for key in ('VX_CFG_FDIV_LATENCY', 'VX_CFG_FSQRT_LATENCY'):
        old = '#define ' + key + ' 31\n'
        if text.count(old) != 1:
            raise ValueError('normalization candidate must resolve to 31 cycles')
        text = text.replace(old, '#define ' + key + ' 30\n')
    values = step_config(text)
    values.update(VX_CFG_FDIV_LATENCY='31', VX_CFG_FSQRT_LATENCY='31')
    return values
