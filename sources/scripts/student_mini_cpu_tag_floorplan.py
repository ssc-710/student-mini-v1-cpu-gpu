"""Keep the proven grid, removing only its cache-tag macro slot."""
from scripts.student_mini_cpu_floorplan import geometry as old_geometry, placement_tcl as old_placement, configuration
import re


def geometry(lef,total_area):
    sizes=re.findall(r'\bSIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;',lef)
    if len(sizes)!=1:raise ValueError('one CPU macro view required')
    width,height=map(float,sizes[0]);one=width*height
    # Reuse the same conservative footprint/reserve check, with exact new area.
    result=old_geometry(lef,total_area+one)
    result.update(macro_count=29,macro_area=29*one,standard_cell_area=total_area-29*one)
    return result


def placement_tcl(g):
    text=old_placement(g)
    old='if {[llength $cpu_macros] != 30} { error "CPU must retain all 30 macros" }'
    new='if {[llength $cpu_macros] != 29} { error "CPU cache-tag candidate must retain 29 real macros" }'
    if text.count(old)!=1:raise ValueError('exact macro-count check required')
    return text.replace(old,new)
