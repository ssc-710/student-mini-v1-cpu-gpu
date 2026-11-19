# Adopt only the two Liberty-equivalent drive changes measured by the probe.
set_thread_count 2
read_liberty $::env(MINI_SC_LIB)
read_liberty $::env(MINI_MACRO_LIB)
read_db $::env(MINI_ODB)
read_sdc $::env(MINI_SDC)
source $::env(MINI_RC)
set block [ord::get_db_block]
set count [llength [$block getInsts]]
set connections [dict create]
set macros 0
foreach inst [$block getInsts] {if {[[$inst getMaster] isBlock]} {incr macros}}
if {$macros != 29} {error "expected 29 frozen SRAM macros"}
foreach {name master} {_074408_ sky130_fd_sc_hd__a21boi_0 _096034_ sky130_fd_sc_hd__nor3_1} {
    set inst [$block findInst $name]
    if {$inst eq "NULL" || [[$inst getMaster] getName] ne $master} {error "observed gate differs"}
    foreach pin [$inst getITerms] {
        set net [$pin getNet]
        dict set connections $name [[$pin getMTerm] getName] [expr {$net eq "NULL" ? "NULL" : [$net getName]}]
    }
}
estimate_parasitics -placement
puts "CPU_DRIVE_ECO stage=original"
report_worst_slack -max -digits 6
replace_cell _074408_ sky130_fd_sc_hd__a21boi_4
replace_cell _096034_ sky130_fd_sc_hd__nor3_4
detailed_placement
check_placement -verbose
if {[llength [$block getInsts]] != $count} {error "unexpected topology change"}
foreach {name master} {_074408_ sky130_fd_sc_hd__a21boi_4 _096034_ sky130_fd_sc_hd__nor3_4} {
    set inst [$block findInst $name]
    if {[[$inst getMaster] getName] ne $master} {error "ECO master differs"}
    foreach pin [$inst getITerms] {
        set net [$pin getNet]
        if {[dict get $connections $name [[$pin getMTerm] getName]] ne [expr {$net eq "NULL" ? "NULL" : [$net getName]}]} {error "pin connection changed"}
    }
}
estimate_parasitics -placement
puts "CPU_DRIVE_ECO stage=legalized"
report_worst_slack -max -digits 6
report_checks -path_delay max -group_path_count 10 -fields {slew cap fanout input} -digits 6
write_db $::env(MINI_OUTPUT)/3_place.odb
write_verilog $::env(MINI_OUTPUT)/3_place.v
write_sdc $::env(MINI_OUTPUT)/3_place.sdc
puts "CPU_DRIVE_ECO_COMPLETE gates=2 macros=29 topology_preserved=1"
