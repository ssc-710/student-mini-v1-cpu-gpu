# Detailed routing of a globally routed platform database in its own process, without the
# liberty/STA that the ORFS route stage loads (detailed routing needs no timing): together with
# jemalloc this keeps a GPU quadrant block of ~90k cells under the 8 GiB task budget, where the
# ORFS stage process does not fit.  Same router arguments as ORFS scripts/detail_route.tcl.
# Environment: STUDENT_MINI_ODB (5_1_grt.odb), STUDENT_MINI_OUT (5_2_route.odb),
#              STUDENT_MINI_DRC (DRC report), STUDENT_MINI_MAZE (maze log),
#              STUDENT_MINI_MAX_LAYER (top signal routing layer), STUDENT_MINI_ANT (antenna report).
read_db $env(STUDENT_MINI_ODB)
if {![grt::have_routes]} { error "no global routing guides in $env(STUDENT_MINI_ODB)" }
set max_layer $env(STUDENT_MINI_MAX_LAYER)
set_routing_layers -signal met1-$max_layer -clock met3-$max_layer
detailed_route -output_drc $env(STUDENT_MINI_DRC) -output_maze $env(STUDENT_MINI_MAZE) \
  -drc_report_iter_step 5 -verbose 1
set ant [check_antennas -report_file $env(STUDENT_MINI_ANT)]
puts "STUDENT_MINI_DRT_ANTENNA_NETS $ant"
write_db $env(STUDENT_MINI_OUT)
puts "STUDENT_MINI_DRT_COMPLETE"
