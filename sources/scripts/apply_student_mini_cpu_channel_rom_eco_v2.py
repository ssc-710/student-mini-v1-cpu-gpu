"""Bind the wider-channel placement's actual producer, not the historical one."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import apply_student_mini_cpu_channel_rom_eco as base
from scripts.resume_student_mini_interrupted import replace_once
from scripts.continue_student_mini_cpu_request_route import bound_checker


def channel_checker(parent,checker):
    candidates=[Path(name) for name in parent['bindings'] if Path(name).name=='producer.py'
                and Path(name).parent.parent.name=='cpu-channel-continuation']
    if len(candidates)!=1:raise ValueError('unique actual wider-channel placement producer required')
    return bound_checker(parent,checker,candidates[0],'cpu',29)


def sources(producer,hook,root,hook_path):
    body,tcl=original_sources(producer,hook,root,hook_path)
    body=replace_once(body,"bound_checker(parent, checker, checker.parent/'placement-producer.py', 'cpu', 29)",
                      'channel_checker(parent, checker)')
    body=replace_once(body,'from scripts.apply_student_mini_cpu_channel_rom_eco import parse_single',
                      'from scripts.apply_student_mini_cpu_channel_rom_eco import parse_single\nfrom scripts.apply_student_mini_cpu_channel_rom_eco_v2 import channel_checker')
    body=replace_once(body,'paths = [Path(__file__),',"paths = [Path(__file__), ROOT/'scripts/apply_student_mini_cpu_channel_rom_eco_v2.py',")
    return body,tcl


original_sources=base.sources
if __name__=='__main__':
    base.sources=sources
    base.__file__=__file__
    raise SystemExit(base.main())
