# Timing of a detail-routed platform database on its own OpenRCX extraction (sky130hd rcx_patterns.rules,
# the extraction ORFS uses for 6_final.spef), own process: decides whether another post-route ECO pass
# (post_route_eco.tcl) runs.  The database is not written back (extraction reorders its wires).
# Environment: STUDENT_MINI_ODB, STUDENT_MINI_LIBS, STUDENT_MINI_SDC, STUDENT_MINI_PLATFORM_DIR, STUDENT_MINI_SPEF (output),
#              STUDENT_MINI_ECO_CHIP_IO (1: the chip-level ports get the GPU I/O constraint as in post_route_eco.tcl).
foreach lib $env(STUDENT_MINI_LIBS) { read_liberty $lib }
read_db $env(STUDENT_MINI_ODB)
read_sdc $env(STUDENT_MINI_SDC)
if {[info exists env(STUDENT_MINI_ECO_CHIP_IO)] && $env(STUDENT_MINI_ECO_CHIP_IO)} {
  source [file join [file dirname [info script]] eco_chip_io.tcl]
}
# chip timing context of the block (gpu_block_context.tcl): replaces the budgets of its ports by the chip
# arrival / required times and models the chip clock edge at clk_i (run_student_mini_platform_physical_ctx.py)
if {[info exists env(STUDENT_MINI_ECO_CONTEXT)] && $env(STUDENT_MINI_ECO_CONTEXT) ne ""} {
  read_sdc $env(STUDENT_MINI_ECO_CONTEXT)
  puts "STUDENT_MINI_ECO_CONTEXT $env(STUDENT_MINI_ECO_CONTEXT)"
}
source $env(STUDENT_MINI_PLATFORM_DIR)/setRC.tcl
set_propagated_clock [all_clocks]
# same sequence as ORFS scripts/final_outputs.tcl (6_final.spef): extract, write the SPEF, time on the read-back SPEF
define_process_corner -ext_model_index 0 X
set_extraction_rules_file $env(STUDENT_MINI_PLATFORM_DIR)/rcx_patterns.rules
extract_parasitics
write_spef $env(STUDENT_MINI_SPEF)
read_spef $env(STUDENT_MINI_SPEF)
puts "STUDENT_MINI_RCX_TIMING wns=[sta::worst_slack -max] tns=[sta::total_negative_slack -max] hold=[sta::worst_slack -min]"
# register-to-register (incl. macro) setup: the paths inside the block; I/O paths are timed against boundary budgets
set r2r [lindex [find_timing_paths -from [all_registers -clock_pins] -to [all_registers -data_pins] -path_delay max] 0]
puts "STUDENT_MINI_RCX_R2R wns=[get_property $r2r slack]"
report_checks -path_delay max -format end -group_path_count 10
