# Diagnostic only: no ODB or netlist is written; parent checkpoint is immutable.
set_thread_count 2
read_liberty $::env(MINI_SC_LIB)
read_liberty $::env(MINI_MACRO_LIB)
read_db $::env(MINI_ODB)
read_sdc $::env(MINI_SDC)
source $::env(MINI_RC)
estimate_parasitics -placement
set block [ord::get_db_block]
set inst [$block findInst _074408_]
if {$inst eq "NULL" || [[$inst getMaster] getName] ne "sky130_fd_sc_hd__a21boi_0"} {
    error "observed multiplier gate differs"
}
set instance_count [llength [$block getInsts]]
set connections [dict create]
foreach pin [$inst getITerms] {
    set net [$pin getNet]
    dict set connections [[$pin getMTerm] getName] [expr {$net eq "NULL" ? "NULL" : [$net getName]}]
}
foreach strength {0 1 2 4} {
    if {$strength != 0} {
        resize_cell [get_cells _074408_] sky130_fd_sc_hd__a21boi_$strength
        estimate_parasitics -placement
    }
    if {[llength [$block getInsts]] != $instance_count} {error "unexpected topology change"}
    foreach pin [$inst getITerms] {
        set net [$pin getNet]
        set name [expr {$net eq "NULL" ? "NULL" : [$net getName]}]
        if {[dict get $connections [[$pin getMTerm] getName]] ne $name} {error "pin connection changed"}
    }
    puts "CPU_MULT_DRIVE_PROBE strength=$strength"
    report_worst_slack -max -digits 6
    report_checks -path_delay max -group_path_count 1 -fields {slew cap fanout input nets} -digits 6
}
puts "CPU_MULT_DRIVE_PROBE_COMPLETE diagnostic_only=1 no_checkpoint_written=1"
