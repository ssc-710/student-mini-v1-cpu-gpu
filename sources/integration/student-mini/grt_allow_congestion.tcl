# PRE_GLOBAL_ROUTE hook for the GPU quadrant blocks: every global_route call of the ORFS stage
# (initial route and the incremental re-routes after repair/recover_power) keeps the residual
# local overflow and hands it to detailed routing instead of aborting (GLOBAL_ROUTE_ARGS only
# reaches the initial call).  Sign-off still requires zero DRC after detailed routing.
if {[info commands student_mini_global_route_orig] eq ""} {
  rename global_route student_mini_global_route_orig
  proc global_route {args} {
    if {[lsearch -exact $args -start_incremental] < 0 && [lsearch -exact $args -allow_congestion] < 0} {
      lappend args -allow_congestion
    }
    return [uplevel 1 [list student_mini_global_route_orig {*}$args]]
  }
}
# repair_antennas re-routes the repaired nets incrementally and has its own -allow_congestion
# flag (without it any residual overflow raises GRT-0232 and leaves the stage without routes).
if {[info commands student_mini_repair_antennas_orig] eq ""} {
  rename repair_antennas student_mini_repair_antennas_orig
  proc repair_antennas {args} {
    if {[lsearch -exact $args -allow_congestion] < 0} { lappend args -allow_congestion }
    return [uplevel 1 [list student_mini_repair_antennas_orig {*}$args]]
  }
}
