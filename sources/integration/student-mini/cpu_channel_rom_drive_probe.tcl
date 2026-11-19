# One gate only; diagnostic measurements never write a checkpoint.
set_thread_count 2
read_liberty $::env(MINI_SC_LIB)
read_liberty $::env(MINI_MACRO_LIB)
read_db $::env(MINI_ODB)
read_sdc $::env(MINI_SDC)
source $::env(MINI_RC)
set block [ord::get_db_block]
set count [llength [$block getInsts]]
set inst [$block findInst _125420_]
if {$inst eq "NULL" || [[$inst getMaster] getName] ne "sky130_fd_sc_hd__o21ai_0"} {error "actual ROM gate differs"}
set connections [dict create]
foreach pin [$inst getITerms] {
    set net [$pin getNet]
    dict set connections [[$pin getMTerm] getName] [expr {$net eq "NULL" ? "NULL" : [$net getName]}]
}
foreach strength {0 1 2 4} {
    if {$strength != 0} {replace_cell _125420_ sky130_fd_sc_hd__o21ai_$strength}
    if {[llength [$block getInsts]] != $count} {error "unexpected topology change"}
    set inst [$block findInst _125420_]
    if {[[$inst getMaster] getName] ne "sky130_fd_sc_hd__o21ai_$strength"} {error "drive change failed"}
    foreach pin [$inst getITerms] {
        set net [$pin getNet]
        if {[dict get $connections [[$pin getMTerm] getName]] ne [expr {$net eq "NULL" ? "NULL" : [$net getName]}]} {error "pin net changed"}
    }
    estimate_parasitics -placement
    puts "CPU_ROM_DRIVE_PROBE strength=$strength"
    report_worst_slack -max -digits 6
    report_checks -path_delay max -group_path_count 1 -fields {slew cap fanout input} -digits 6
}
puts "CPU_ROM_DRIVE_COMPLETE gates=1 diagnostic_only=1 no_checkpoint_written=1"
