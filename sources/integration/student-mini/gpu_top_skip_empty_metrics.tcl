# PRE_RESIZE / PRE_DETAIL_PLACE hook of the four-quadrant GPU top: before CTS the top level holds
# only the four hardened blocks (no standard cell), and ORFS report_metrics then fails on
# sta::max_slew_check_slack_limit (no slew check -> NaN, "domain error").  Skip the metrics report
# of such a stage only; every stage from CTS on (with clock buffers) reports normally.
set student_mini_std_cells 0
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { incr student_mini_std_cells }
}
if {$student_mini_std_cells == 0} {
  puts "STUDENT_MINI_TOP_NO_STD_CELLS: report_metrics skipped in this stage"
  set ::env(SKIP_REPORT_METRICS) 1
}
