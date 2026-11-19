# SPDX-License-Identifier: Apache-2.0
# OpenRAM SKY130 uses vccd1/vssd1 while ORFS's sky130hd platform defaults to
# VDD/VSS, VPWR/VGND and well pins.  Bind the generated macro pins before the
# platform defines macro PDN grids so the physical SRAM is never left floating.
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^vccd1$} -power
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^vssd1$} -ground
global_connect
