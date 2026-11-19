"""Deterministic initial floorplan for the replayed 30-macro CPU boundary."""
import math
import re

MACRO = 'vortex_sp_32x1024_w4'


def geometry(lef, total_area):
    sizes = re.findall(r'\bSIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;', lef)
    if len(sizes) != 1 or f'MACRO {MACRO}' not in lef:
        raise ValueError('one exact CPU SRAM master required')
    width, height = map(float, sizes[0])
    if not (600 < width < 800 and 600 < height < 800):
        raise ValueError('macro units or geometry differ')
    macro_area = 30 * width * height
    if not math.isfinite(total_area) or not macro_area < total_area < macro_area * 2:
        raise ValueError('invalid synthesized cell/macro area')
    gap, margin = 80., 100.
    die_width = math.ceil((6 * width + 5 * gap + 2 * margin) / 10) * 10
    die_height = math.ceil((5 * height + 4 * gap + 2 * margin) / 10) * 10
    usable = (die_width - 40) * (die_height - 40) - macro_area
    if (total_area - macro_area) / usable > .45:
        raise ValueError('insufficient standard-cell reserve')
    return dict(width=width, height=height, macro_count=30, columns=6, rows=5,
                gap=gap, margin=margin, die_width=die_width, die_height=die_height,
                macro_area=macro_area, standard_cell_area=total_area-macro_area)


def placement_tcl(g):
    # Query exact DB names instead of interpreting escaped Verilog identifiers.
    return '''set cpu_macros [list]
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  if {[[$inst getMaster] getName] ne "vortex_sp_32x1024_w4"} {
    error "Unexpected CPU macro master"
  }
  lappend cpu_macros [$inst getName]
}
if {[llength $cpu_macros] != 30} { error "CPU must retain all 30 macros" }
set cpu_index 0
foreach name [lsort $cpu_macros] {
''' + f'''  set x [expr {{{g['margin']} + ($cpu_index % 6) * {g['width']+g['gap']}}}]
  set y [expr {{{g['margin']} + ($cpu_index / 6) * {g['height']+g['gap']}}}]
''' + '''  place_macro -macro_name $name -location [list $x $y] -orientation R0
  incr cpu_index
}
'''


def configuration(original, g, placement):
    if 'export NUM_CORES = 2' not in original or 'export SYNTH_MOCK_LARGE_MEMORIES = 0' not in original:
        raise ValueError('not the qualified CPU synthesis configuration')
    lines = [line for line in original.splitlines() if not line.startswith('export CORE_UTILIZATION =')]
    lines += [f"export DIE_AREA = 0 0 {g['die_width']} {g['die_height']}",
              f"export CORE_AREA = 20 20 {g['die_width']-20} {g['die_height']-20}",
              f'export MACRO_PLACEMENT_TCL = {placement}', 'export MACRO_PLACE_HALO = 10 10']
    return '\n'.join(lines) + '\n'
