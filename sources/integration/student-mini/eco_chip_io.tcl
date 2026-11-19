# Constraint overlay of the post-route ECO repair of a GPU quadrant block (sourced by post_route_eco.tcl after the
# block SDC).  The block SDC budgets only the cut ports between quadrants; the block's chip-level ports (rst_ni,
# host and memory ports) are unconstrained there, so the block runs never timed e.g. the reset distribution
# from rst_ni.  For the repair only, they get the GPU constraint (integration/student-mini/gpu_constraint.sdc:
# 0.5 ns external delay against the virtual io_clock, whose latency in the block SDC already accounts for the
# top-level clock tree) plus an allowance for the top-level wire between chip pin and block pin on the late
# (setup) side; the pure feedthroughs of chip inputs that the top level bypasses are not timed (see below).
# This only tightens what the repair aims at; the sign-off is the full-chip STA with the unchanged GPU constraint.
set allowance 0.5
set chip_in [get_ports -quiet -filter "direction == input" *]
set chip_in [lmap p $chip_in { set n [get_name $p]; if {$n eq "clk_i" || [string match part_* $n]} { continue } else { set p } }]
set chip_out [get_ports -quiet -filter "direction == output" *]
set chip_out [lmap p $chip_out { if {[string match part_* [get_name $p]]} { continue } else { set p } }]
if {[llength $chip_in]} {
  set_input_delay -max [expr {0.5 + $allowance}] -clock io_clock $chip_in
  set_input_delay -min 0.5 -clock io_clock $chip_in
}
if {[llength $chip_out]} {
  set_output_delay -max [expr {0.5 + $allowance}] -clock io_clock $chip_out
  set_output_delay -min 0.5 -clock io_clock $chip_out
}
# A cut output that is only a buffer/inverter feedthrough of a chip input is wired to the chip input directly at
# the top (prepare_student_mini_gpu_top.py direct_chip_feedthroughs): that path does not exist in the chip.
set chain_cell {^sky130_fd_sc_hd__(buf|clkbuf|bufbuf|dlygate4sd\d|dlymetal6s\ds|clkdlybuf4s\d+|inv|clkinv|clkinvlp)_\d+$}
set chip_names [lmap p $chip_in { get_name $p }]
set feedthroughs 0
foreach bt [[ord::get_db_block] getBTerms] {
  if {[$bt getIoType] ne "OUTPUT" || ![string match part_* [$bt getName]]} { continue }
  set net [$bt getNet]
  for {set step 0} {$step < 200 && $net ne "NULL"} {incr step} {
    set in [lmap b [$net getBTerms] { if {[$b getIoType] eq "INPUT"} { $b getName } else { continue } }]
    if {[llength $in]} {
      if {[lindex $in 0] in $chip_names} {
        set_false_path -from [get_ports [lindex $in 0]] -to [get_ports [$bt getName]]
        incr feedthroughs
      }
      break
    }
    set drv [lmap it [$net getITerms] { if {[$it isOutputSignal]} { set it } else { continue } }]
    if {[llength $drv] != 1 || ![regexp $chain_cell [[[[lindex $drv 0] getInst] getMaster] getName]]} { break }
    set a [[[lindex $drv 0] getInst] findITerm A]
    if {$a eq "NULL"} { break }
    set net [$a getNet]
  }
}
puts "STUDENT_MINI_ECO_CHIP_IO inputs=[llength $chip_in] outputs=[llength $chip_out] feedthroughs=$feedthroughs"
