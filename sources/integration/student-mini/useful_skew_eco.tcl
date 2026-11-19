# Useful-skew step of the post-route ECO (sourced by post_route_eco.tcl after the setup/hold repair, inside
# incremental global routing): a flip-flop whose register-to-register setup path still fails but whose own
# outgoing paths have setup margin and whose incoming paths have hold margin is clocked later through a
# clock delay cell inserted between its clock leaf net and its clock pin (the flops of one leaf net share one
# cell).  Typical case: the capture flops of a half-cycle SRAM read (launch on the falling edge) behind a long
# SRAM output wire.  The candidate cells are tried in place in order of increasing delay and timed; the first
# that brings the group's worst setup slack to the target is kept (else the one improving it most), provided
# no outgoing setup slack drops below q_margin and no hold slack below hold_margin (or below its value
# before).  Logic is unchanged (clock buffering only).
# useful_skew {q_margin hold_margin target}: endpoints with setup slack below target (ns) are candidates (the
# global-route estimate reads optimistic against the routed SPEF); returns the number of flops moved.

proc us_worst {pin kind dir} {
  # worst slack of the paths ending at (dir to) or starting at (dir from) a pin
  set p [lindex [find_timing_paths -$dir $pin -path_delay $kind] 0]
  if {$p eq ""} { return 1e9 }
  return [get_property $p slack]
}

proc us_power {block inst} {
  foreach it [$inst getITerms] {
    set type [[$it getMTerm] getSigType]
    if {$type eq "POWER"} { $it connect [$block findNet VDD] } elseif {$type eq "GROUND"} { $it connect [$block findNet VSS] }
  }
}

proc us_place {block master name leaf net use cx cy} {
  set buf [odb::dbInst_create $block $master $name]
  $buf setLocation $cx $cy
  $buf setPlacementStatus PLACED
  us_power $block $buf
  [$buf findITerm A] connect $leaf
  [$buf findITerm X] connect $net
  foreach m $use { set t [lindex $m 1]; $t disconnect; $t connect $net }
  estimate_parasitics -global_routing
  return $buf
}

proc us_group_slacks {use} {
  set s 1e9; set h 1e9; set qmin 1e9
  foreach m $use {
    set name [[lindex $m 0] getName]
    set s [expr {min($s, [us_worst [get_pins $name/D] max to])}]
    set h [expr {min($h, [us_worst [get_pins $name/D] min to])}]
    foreach o [lindex $m 4] { set qmin [expr {min($qmin, [us_worst [get_pins $name/$o] max from])}] }
  }
  return [list $s $h $qmin]
}

proc useful_skew {q_margin hold_margin target} {
  set block [ord::get_db_block]
  set groups [dict create]
  set seen 0; set internal 0
  # the path objects of one search are freed by the next search: collect the endpoints first
  set ends [lmap p [find_timing_paths -path_delay max -group_path_count 5000 -endpoint_path_count 1 -slack_max $target] {
    list [get_full_name [get_property $p startpoint]] [get_property $p endpoint] [get_property $p slack]
  }]
  foreach e $ends {
    lassign $e sp ep_pin slack
    # internal violating endpoints only: a register or macro startpoint (I/O-port paths are boundary budgets)
    set ep [get_full_name $ep_pin]
    set cut [string last / $ep]
    incr seen
    if {[string last / $sp] < 0 || $cut < 0 || [string range $ep [expr {$cut + 1}] end] ne "D"} { continue }
    incr internal
    set db_inst [sta::sta_to_db_inst [get_cells -of_objects $ep_pin]]
    if {$db_inst eq "NULL"} { puts "STUDENT_MINI_ECO_USEFUL_SKEW_NOINST $ep"; continue }
    set ck_iterm [$db_inst findITerm CLK]
    if {$ck_iterm eq "NULL" || [$ck_iterm getNet] eq "NULL"} { puts "STUDENT_MINI_ECO_USEFUL_SKEW_NOCLK $ep"; continue }
    set outs [lmap it [$db_inst getITerms] { if {[$it isOutputSignal]} { [$it getMTerm] getName } else { continue } }]
    set name [$db_inst getName]
    set qs 1e9
    foreach o $outs { set qs [expr {min($qs, [us_worst [get_pins $name/$o] max from])}] }
    set hs [us_worst [get_pins $name/D] min to]
    set need [expr {$target - $slack}]
    set allow [expr {min($qs - $q_margin, $hs - $hold_margin)}]
    if {$allow < 0.05} { puts "STUDENT_MINI_ECO_USEFUL_SKEW_SKIP $name need=[format %.3f $need] q=[format %.3f $qs] hold=[format %.3f $hs]"; continue }
    dict lappend groups [[$ck_iterm getNet] getName] [list $db_inst $ck_iterm $need $allow $outs]
  }
  puts "STUDENT_MINI_ECO_USEFUL_SKEW_CANDIDATES violating=$seen internal=$internal groups=[dict size $groups]"
  # candidate clock delay cells, roughly increasing delay
  set cells {sky130_fd_sc_hd__clkbuf_1 sky130_fd_sc_hd__clkdlybuf4s15_1 sky130_fd_sc_hd__clkdlybuf4s18_1
             sky130_fd_sc_hd__clkdlybuf4s25_1 sky130_fd_sc_hd__clkdlybuf4s50_1 sky130_fd_sc_hd__dlygate4sd2_1
             sky130_fd_sc_hd__dlygate4sd3_1}
  set moved 0
  set k 0
  dict for {leaf_name members} $groups {
    set leaf [$block findNet $leaf_name]
    set allow [tcl::mathfunc::min {*}[lmap m $members { lindex $m 3 }]]
    set need [tcl::mathfunc::max {*}[lmap m $members { lindex $m 2 }]]
    set use $members
    if {$need > $allow} {
      # flops whose allowance cannot cover the group's largest need stay on the leaf
      set use [lmap m $members { if {[lindex $m 3] >= $need} { set m } else { continue } }]
      if {![llength $use]} { set use $members }
    }
    set sx 0; set sy 0
    foreach m $use { lassign [[lindex $m 0] getLocation] x y; incr sx $x; incr sy $y }
    set cx [expr {$sx / [llength $use]}]; set cy [expr {$sy / [llength $use]}]
    lassign [us_group_slacks $use] before_setup before_hold before_q
    # names unused by an earlier ECO pass
    incr k
    while {[$block findNet "useful_skew_net_$k"] ne "NULL" || [$block findInst "useful_skew_$k"] ne "NULL"} { incr k }
    set net [odb::dbNet_create $block "useful_skew_net_$k"]
    $net setSigType CLOCK
    set kept ""
    foreach master_name $cells {
      set master [[ord::get_db] findMaster $master_name]
      if {$master eq "NULL"} { continue }
      set buf [us_place $block $master "useful_skew_$k" $leaf $net $use $cx $cy]
      lassign [us_group_slacks $use] s h q
      set ok [expr {$s > $before_setup + 0.01 && $h >= min($hold_margin, $before_hold) && $q >= min($q_margin, $before_q)}]
      if {$ok && ($kept eq "" || $s > [lindex $kept 1])} { set kept [list $master_name $s $h $q] }
      foreach m $use { set t [lindex $m 1]; $t disconnect; $t connect $leaf }
      odb::dbInst_destroy $buf
      estimate_parasitics -global_routing
      # the smallest delay that reaches the target keeps the most hold margin
      if {$ok && $s >= $target} { break }
    }
    if {$kept eq ""} {
      puts "STUDENT_MINI_ECO_USEFUL_SKEW_NONE leaf=$leaf_name flops=[llength $use] setup=[format %.3f $before_setup]"
      odb::dbNet_destroy $net
      continue
    }
    us_place $block [[ord::get_db] findMaster [lindex $kept 0]] "useful_skew_$k" $leaf $net $use $cx $cy
    incr moved [llength $use]
    puts "STUDENT_MINI_ECO_USEFUL_SKEW leaf=$leaf_name flops=[llength $use] cell=[lindex $kept 0] setup=[format %.3f $before_setup]->[format %.3f [lindex $kept 1]] hold=[format %.3f [lindex $kept 2]] q=[format %.3f [lindex $kept 3]]"
  }
  return $moved
}
