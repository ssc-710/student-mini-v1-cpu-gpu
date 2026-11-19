# Full-chip sign-off STA of the hierarchical student-mini GPU: the top netlist linked with the four
# routed quadrant-block netlists (no abstract timing models), each block's extracted parasitics
# annotated at its instance path, the top-level parasitics, the GPU constraint and propagated clocks.
# Every cross-block path is timed through real cells and wires.  Run with OpenSTA (sta): no layout needed.
# Environment: STUDENT_MINI_LIBS (std-cell + SRAM liberty), STUDENT_MINI_TOP_V, STUDENT_MINI_TOP_SPEF,
#              STUDENT_MINI_SDC, STUDENT_MINI_BLOCKS (list of "instance netlist spef" triples),
#              STUDENT_MINI_TOP (top module), STUDENT_MINI_REPORT (report file).
foreach lib $env(STUDENT_MINI_LIBS) { read_liberty $lib }
foreach {inst netlist spef} $env(STUDENT_MINI_BLOCKS) { read_verilog $netlist }
read_verilog $env(STUDENT_MINI_TOP_V)
link_design $env(STUDENT_MINI_TOP)
read_sdc $env(STUDENT_MINI_SDC)
set_propagated_clock [all_clocks]
if {$env(STUDENT_MINI_TOP_SPEF) ne ""} { read_spef $env(STUDENT_MINI_TOP_SPEF) }
foreach {inst netlist spef} $env(STUDENT_MINI_BLOCKS) { read_spef -path $inst $spef }
set rpt $env(STUDENT_MINI_REPORT)
report_checks -path_delay max -group_path_count 5 -format full_clock_expanded -digits 3 > $rpt
report_checks -path_delay min -group_path_count 5 -format full_clock_expanded -digits 3 >> $rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators >> $rpt
puts "STUDENT_MINI_FULLCHIP_SETUP"
report_worst_slack -max -digits 3
report_tns -max -digits 3
puts "STUDENT_MINI_FULLCHIP_HOLD"
report_worst_slack -min -digits 3
report_tns -min -digits 3
puts "STUDENT_MINI_FULLCHIP_COMPLETE"
