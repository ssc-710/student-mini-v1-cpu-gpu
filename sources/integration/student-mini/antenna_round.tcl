# One antenna-repair round on a routed platform database, in its own process.
# ORFS runs repair_antennas + detailed_route repeatedly inside the route stage; the
# second detailed_route there starts on top of the first one's memory (never returned),
# which exceeds the 8 GiB student budget.  Here every round is a fresh process without
# liberty/STA (neither repair_antennas nor detailed_route needs timing).
# Environment: STUDENT_MINI_ODB (input), STUDENT_MINI_OUT (output odb),
#              STUDENT_MINI_DRC (DRC report), STUDENT_MINI_ANT (antenna report),
#              STUDENT_MINI_MAX_LAYER (top signal routing layer of the design, e.g. met4 for hard blocks),
#              STUDENT_MINI_ANTENNA_MODE (optional repair mode, see below).
read_db $env(STUDENT_MINI_ODB)
# dont_touch marks are timing-repair constraints (post-route ECO); diodes and split buffers must connect to any net
foreach net [[ord::get_db_block] getNets] { if {[$net isDoNotTouch]} { $net setDoNotTouch 0 } }
set max_layer $env(STUDENT_MINI_MAX_LAYER)
set_routing_layers -signal met1-$max_layer
set before [check_antennas]
puts "STUDENT_MINI_ANTENNA_BEFORE $before"
if {$before == 0} {
  puts "STUDENT_MINI_ANTENNA_ROUND_SKIPPED"
  exit
}
# -allow_congestion: residual global-route overflow of the incremental re-route of the repaired
# nets is left to detailed routing (otherwise GRT-0232 aborts the round); the round is accepted
# only with zero DRC violations after detailed routing.
# STUDENT_MINI_ANTENNA_MODE: "" (diodes and jumpers), "jumper" or "diode": the runner retries a round
# that left DRC violations from the same input with the other modes.
set mode [expr {[info exists env(STUDENT_MINI_ANTENNA_MODE)] ? $env(STUDENT_MINI_ANTENNA_MODE) : ""}]
# "split": for a long single-layer wire whose violating met1 island the inserted diodes never reach
# (the diode lands on another island of the net), every violating gate pin is moved behind a chain of
# sky130_fd_sc_hd__buf_2 buffers placed along the driver-to-pin line every ~140 um (the sky130 met1
# side-area limit of 400 allows ~165 um of met1 per gate); logic is unchanged (buffers only).  The new
# cells are legalized and the changed nets re-routed incrementally; the round is accepted only with zero DRC.
proc split_long_antenna_wires {report} {
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  set buf [[ord::get_db] findMaster sky130_fd_sc_hd__buf_2]
  set viol {}
  set f [open $report]
  set cur ""; set pin ""
  while {[gets $f line] >= 0} {
    if {[regexp {^Net: (\S+)} $line -> n]} { set cur $n; set pin "" }
    if {[regexp {^\s+Pin:\s+(\S+)} $line -> p]} { set pin $p }
    if {[string match *VIOLATED* $line] && $pin ne ""} { lappend viol [list $cur $pin]; set pin "" }
  }
  close $f
  global_route -start_incremental -allow_congestion
  set added 0
  set tag [clock seconds]
  set k 0
  foreach pr [lsort -unique $viol] {
    lassign $pr nn pin
    set net [$block findNet $nn]
    set slash [string last / $pin]
    set inst [$block findInst [string range $pin 0 [expr {$slash - 1}]]]
    if {$net eq "NULL" || $inst eq "NULL"} { continue }
    set load [$inst findITerm [string range $pin [expr {$slash + 1}] end]]
    set drv ""
    foreach it [$net getITerms] { if {[$it isOutputSignal]} { set drv $it } }
    if {$drv eq "" || $load eq "NULL"} { continue }
    lassign [[$drv getInst] getLocation] dx dy
    lassign [$inst getLocation] lx ly
    set nbuf [expr {max(1, int(ceil((abs($lx - $dx) + abs($ly - $dy)) / (140.0 * $dbu))) - 1)}]
    set target $load
    for {set j 1} {$j <= $nbuf} {incr j} {
      set b [odb::dbInst_create $block $buf "antenna_split_${tag}_${k}_$j"]
      set nnet [odb::dbNet_create $block "antenna_split_net_${tag}_${k}_$j"]
      $target disconnect
      $target connect $nnet
      [$b findITerm X] connect $nnet
      [$b findITerm A] connect $net
      foreach pg {VPWR VPB} { set t [$b findITerm $pg]; if {$t ne "NULL"} { $t connect [$block findNet VDD] } }
      foreach pg {VGND VNB} { set t [$b findITerm $pg]; if {$t ne "NULL"} { $t connect [$block findNet VSS] } }
      $b setLocation [expr {round($lx + ($dx - $lx) * $j / double($nbuf + 1))}] [expr {round($ly + ($dy - $ly) * $j / double($nbuf + 1))}]
      $b setPlacementStatus PLACED
      set target [$b findITerm A]
      incr added
    }
    incr k
  }
  detailed_placement
  check_placement
  global_route -end_incremental -allow_congestion
  puts "STUDENT_MINI_ANTENNA_SPLIT pins=$k buffers=$added"
}
# "upsize": a gate pin that violates the side-area ratio by a modest factor (the diodes land on another
# island of its net) gets the next drive strength of the same cell whose larger input gate area brings the
# ratio under the limit (sky130 gate area scales with the drive suffix: ratio / limit x 1.1 <= new / old
# drive); only the upsized cell is legalized (all other cells stay locked, their routes untouched), its own
# nets lose their detailed route and are re-routed.  Logic is unchanged.
proc upsize_antenna_gates {report} {
  set block [ord::get_db_block]
  set db [ord::get_db]
  # worst violating ratio / required ratio per gate pin
  set need [dict create]
  set f [open $report]
  set pin ""; set partial 0
  while {[gets $f line] >= 0} {
    if {[regexp {^Net: } $line]} { set pin "" }
    if {[regexp {^\s+Pin:\s+(\S+)} $line -> p]} { set pin $p }
    if {[regexp {Partial area ratio:\s+([0-9.]+)} $line -> v]} { set partial $v }
    if {$pin ne "" && [regexp {Required ratio:\s+([0-9.]+) \(Side area\) \(VIOLATED\)} $line -> r] && $r > 0} {
      set q [expr {$partial / $r}]
      if {![dict exists $need $pin] || $q > [dict get $need $pin]} { dict set need $pin $q }
    }
  }
  close $f
  global_route -start_incremental -allow_congestion
  set swapped 0
  set upsized {}
  dict for {pin q} $need {
    set slash [string last / $pin]
    set inst [$block findInst [string range $pin 0 [expr {$slash - 1}]]]
    if {$inst eq "NULL"} { continue }
    set master [[$inst getMaster] getName]
    if {![regexp {^(.*)_(\d+)$} $master -> base size]} { continue }
    set best ""
    foreach cand {1 2 3 4 6 8 12 16} {
      if {$cand <= $size || $cand < $size * $q * 1.1} { continue }
      set m [$db findMaster ${base}_$cand]
      if {$m ne "NULL"} { set best $m; break }
    }
    if {$best eq ""} { puts "STUDENT_MINI_ANTENNA_UPSIZE_NONE $pin $master need=[format %.2f $q]"; continue }
    foreach it [$inst getITerms] {
      set net [$it getNet]
      if {$net ne "NULL" && ![$net isSpecial] && [$net getWire] ne "NULL"} { odb::dbWire_destroy [$net getWire] }
    }
    $inst swapMaster $best
    lappend upsized $inst
    puts "STUDENT_MINI_ANTENNA_UPSIZE $pin $master -> [$best getName] need=[format %.2f $q]"
    incr swapped
  }
  # legalize only the upsized cells: every other cell keeps its place and its routes (a moved neighbour
  # would be re-routed and can pick up new antenna violations)
  set fixed {}
  foreach i [$block getInsts] {
    if {$i in $upsized || [$i getPlacementStatus] ne "PLACED"} { continue }
    $i setPlacementStatus FIRM
    lappend fixed $i
  }
  detailed_placement
  foreach i $fixed { $i setPlacementStatus PLACED }
  check_placement
  global_route -end_incremental -allow_congestion
  puts "STUDENT_MINI_ANTENNA_UPSIZE_COUNT $swapped"
}
switch -- $mode {
  ""       { repair_antennas -allow_congestion }
  "jumper" { repair_antennas -allow_congestion -jumper_only }
  "diode"  { repair_antennas -allow_congestion -diode_only }
  "split"  {
    check_antennas -report_file $env(STUDENT_MINI_ANT).before
    split_long_antenna_wires $env(STUDENT_MINI_ANT).before
  }
  "upsize" {
    check_antennas -report_file $env(STUDENT_MINI_ANT).before
    upsize_antenna_gates $env(STUDENT_MINI_ANT).before
  }
  default  { error "unknown STUDENT_MINI_ANTENNA_MODE $mode" }
}
puts "STUDENT_MINI_ANTENNA_MODE [expr {$mode eq {} ? {default} : $mode}]"
detailed_route -output_drc $env(STUDENT_MINI_DRC) -droute_end_iter 64 -verbose 1
set after [check_antennas -report_file $env(STUDENT_MINI_ANT)]
puts "STUDENT_MINI_ANTENNA_AFTER $after"
write_db $env(STUDENT_MINI_OUT)
puts "STUDENT_MINI_ANTENNA_ROUND_COMPLETE"
