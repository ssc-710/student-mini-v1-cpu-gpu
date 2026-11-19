"""Frozen mini geometry with the separately proved 57-cycle timing foundation."""
from scripts.student_mini_gpu_nrm_overlay import CONFIGS as NRM_CONFIGS, checked_config as nrm_config
from scripts.student_mini_gpu_cut_overlay import create_overlay

CONFIGS = NRM_CONFIGS.replace('LATENCY=31', 'LATENCY=57')


def checked_config(text):
    for key in ('VX_CFG_FDIV_LATENCY', 'VX_CFG_FSQRT_LATENCY'):
        old = '#define '+key+' 57\n'
        if text.count(old) != 1: raise ValueError('sign/update candidate must resolve to 57 cycles')
        text = text.replace(old, '#define '+key+' 31\n')
    result = nrm_config(text)
    result.update(VX_CFG_FDIV_LATENCY='57', VX_CFG_FSQRT_LATENCY='57')
    return result
