"""One-variable B0 floorplan experiment: 160 um SRAM channels instead of 80.

Compare with the original DFI placement recipe from the same synthesis, not
with the later three-cell ECO. No RTL, macro view, density or clock change.
"""
import math
from scripts.student_mini_cpu_tag_floorplan import geometry as prior_geometry
from scripts.student_mini_cpu_tag_floorplan import placement_tcl, configuration


def geometry(lef, total_area):
    value = prior_geometry(lef, total_area)
    if value['gap'] != 80 or value['macro_count'] != 29:
        raise ValueError('expected original 29-macro / 80 um channel comparison')
    value['gap'] = 160.0
    value['die_width'] = math.ceil((value['columns']*value['width'] +
        (value['columns']-1)*value['gap'] + 2*value['margin'])/10)*10
    value['die_height'] = math.ceil((value['rows']*value['height'] +
        (value['rows']-1)*value['gap'] + 2*value['margin'])/10)*10
    return value
