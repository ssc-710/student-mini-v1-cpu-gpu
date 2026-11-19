# In-memory diagnostic only. The original clock-tree database is immutable.
set_thread_count 2
read_liberty $::env(MINI_SC_LIB)
read_liberty $::env(MINI_MACRO_LIB)
read_db $::env(MINI_ODB)
read_sdc $::env(MINI_SDC)
source $::env(MINI_RC)
set block [ord::get_db_block]
set target delaybuf_3_core_clock
set inst [$block findInst $target]
if {$inst eq "NULL" || [[$inst getMaster] getName] ne "sky130_fd_sc_hd__clkbuf_16"} {
    error "exact observed non-inverting clock buffer required"
}
set cells [get_cells $target]
if {[llength $cells] != 1} {error "one exact buffer required; refuse broad removal"}
set count [llength [$block getInsts]]
set macros 0
foreach candidate [$block getInsts] {if {[[$candidate getMaster] isBlock]} {incr macros}}
if {$macros != 29} {error "29 macros required"}
set input_net [[$inst findITerm A] getNet]
set output_net [[$inst findITerm X] getNet]
if {$input_net eq "NULL" || $output_net eq "NULL" || $input_net eq $output_net} {
    error "invalid clock buffer connectivity"
}
set downstream {}
foreach pin [$output_net getITerms] {
    if {[$pin getInst] ne $inst} {lappend downstream $pin}
}
if {[llength $downstream] != 1 || [[lindex $downstream 0] getIoType] ne "INPUT"} {
    error "observed single-load clock branch differs"
}
estimate_parasitics -placement
puts "CPU_CTS_BUFFER_PROBE stage=original"
report_worst_slack -max -digits 6
report_worst_slack -min -digits 6
remove_buffers $cells
if {[$block findInst $target] ne "NULL" || [llength [$block getInsts]] != $count-1} {
    error "expected exactly one clock buffer removal"
}
if {[[lindex $downstream 0] getNet] ne $input_net} {error "buffer bypass disconnected load"}
estimate_parasitics -placement
puts "CPU_CTS_BUFFER_PROBE stage=single_buffer_bypassed"
report_worst_slack -max -digits 6
report_worst_slack -min -digits 6
report_checks -path_delay max -group_path_count 5 -fields {slew cap fanout input nets} -digits 6
report_checks -path_delay min -group_path_count 5 -fields {slew cap fanout input nets} -digits 6
puts "CPU_CTS_BUFFER_PROBE_COMPLETE macros=29 removed=1 diagnostic_only=1 no_checkpoint_written=1"
