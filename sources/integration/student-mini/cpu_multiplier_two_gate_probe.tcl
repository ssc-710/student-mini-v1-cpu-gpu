# Each successive experiment changes only one gate strength; never writes ODB.
set_thread_count 2
read_liberty $::env(MINI_SC_LIB)
read_liberty $::env(MINI_MACRO_LIB)
read_db $::env(MINI_ODB)
read_sdc $::env(MINI_SDC)
source $::env(MINI_RC)
set block [ord::get_db_block]
set count [llength [$block getInsts]]
set connections [dict create]
foreach {name master} {_074408_ sky130_fd_sc_hd__a21boi_0 _096034_ sky130_fd_sc_hd__nor3_1} {
    set inst [$block findInst $name]
    if {$inst eq "NULL" || [[$inst getMaster] getName] ne $master} {error "observed gate differs"}
    foreach pin [$inst getITerms] {
        set net [$pin getNet]
        dict set connections $name [[$pin getMTerm] getName] [expr {$net eq "NULL" ? "NULL" : [$net getName]}]
    }
}
foreach stage {0 1 2 4} {
    if {$stage == 1} {replace_cell _074408_ sky130_fd_sc_hd__a21boi_4}
    if {$stage == 2 || $stage == 4} {replace_cell _096034_ sky130_fd_sc_hd__nor3_$stage}
    if {[llength [$block getInsts]] != $count} {error "unexpected topology change"}
    foreach name {_074408_ _096034_} {
        set inst [$block findInst $name]
        foreach pin [$inst getITerms] {
            set net [$pin getNet]
            if {[dict get $connections $name [[$pin getMTerm] getName]] ne [expr {$net eq "NULL" ? "NULL" : [$net getName]}]} {error "pin connection changed"}
        }
    }
    set primary [[[$block findInst _074408_] getMaster] getName]
    set secondary [[[$block findInst _096034_] getMaster] getName]
    set expected_primary [expr {$stage == 0 ? 0 : 4}]
    set expected_secondary [expr {$stage <= 1 ? 1 : $stage}]
    if {$primary ne "sky130_fd_sc_hd__a21boi_$expected_primary" || $secondary ne "sky130_fd_sc_hd__nor3_$expected_secondary"} {error "drive experiment differs"}
    estimate_parasitics -placement
    puts "CPU_TWO_GATE_PROBE stage=$stage primary=$primary secondary=$secondary"
    report_worst_slack -max -digits 6
    report_checks -path_delay max -group_path_count 1 -fields {slew cap fanout input} -digits 6
}
puts "CPU_TWO_GATE_PROBE_COMPLETE diagnostic_only=1 no_checkpoint_written=1"
