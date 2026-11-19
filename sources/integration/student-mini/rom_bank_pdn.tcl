# PDN of a CPU firmware-ROM bank hard block: met1 followpins and met4 stripes only, the met4
# stripes exported as the block's power pins.  The bank routes signals up to met4 as well
# (MAX_ROUTING_LAYER), so met5 stays free over the bank: the CPU top-level met5 straps run
# across it and the top macro grid drops met4-met5 vias onto these pins (the same scheme as the
# SRAM macros).
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDD$} -power
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VPWR}
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {VPB}
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSS$} -ground
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {VGND}
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {VNB}
global_connect
set_voltage_domain -name {CORE} -power {VDD} -ground {VSS}
define_pdn_grid -name {grid} -voltage_domains {CORE} -pins {met4}
add_pdn_stripe -grid {grid} -layer {met1} -width {0.48} -pitch {5.44} -offset {0} -followpins
add_pdn_stripe -grid {grid} -layer {met4} -width {1.600} -pitch {27.140} -offset {13.570}
add_pdn_connect -grid {grid} -layers {met1 met4}
