# POST_GLOBAL_PLACE hook for a GPU quadrant block: pull capture flops to the far end of their D-input chain.
# Environment: STUDENT_MINI_PULL_PATTERN (backslash-free instance-name globs of the flops, space separated),
#              STUDENT_MINI_PULL_DEPTH (gates to walk back from D, default 6).
# Used for the UL icache response-queue capture flops: their D input is a half-cycle SRAM read (falling-edge
# launch) through the read-data mux tree next to the SRAM array, while their outputs have ~8 ns of slack.
# Wirelength-driven global placement puts them next to their output loads, ~1.9 mm from the mux tree, and
# timing repair cannot recover the wire.  For every matching flop the hook walks back from D through
# single-fanout gates (at each gate taking the input whose driver is farthest away) and moves the flop and
# the walked gates to the farthest point of that chain; detailed placement legalizes afterwards.
set block [ord::get_db_block]
set patterns $::env(STUDENT_MINI_PULL_PATTERN)
set depth [expr {[info exists ::env(STUDENT_MINI_PULL_DEPTH)] ? $::env(STUDENT_MINI_PULL_DEPTH) : 6}]
proc center {inst} {
  set b [$inst getBBox]
  return [list [expr {([$b xMin] + [$b xMax]) / 2}] [expr {([$b yMin] + [$b yMax]) / 2}]]
}
proc dist {a b} { return [expr {abs([lindex $a 0] - [lindex $b 0]) + abs([lindex $a 1] - [lindex $b 1])}] }
set moved 0
set total 0
foreach inst [$block getInsts] {
  set name [string map [list "\\" ""] [$inst getName]]
  set match 0
  foreach p $patterns { if {[string match $p $name]} { set match 1; break } }
  if {!$match} { continue }
  incr total
  set home [center $inst]
  set chain {}
  set cur $inst
  for {set k 0} {$k < $depth} {incr k} {
    set best "NULL"; set bestd -1
    foreach it [$cur getITerms] {
      if {![$it isInputSignal]} { continue }
      set mt [$it getMTerm]
      if {$cur eq $inst && [$mt getName] ne "D"} { continue }
      set net [$it getNet]
      if {$net eq "NULL" || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
      foreach d [$net getITerms] {
        if {![$d isOutputSignal]} { continue }
        set di [$d getInst]
        set m [$di getMaster]
        if {[$m isSequential] || [$m isBlock]} { continue }
        # only gates private to this chain (driving this net alone, single load)
        if {[llength [$net getITerms]] != 2} { continue }
        set dd [dist $home [center $di]]
        if {$dd > $bestd} { set bestd $dd; set best $di }
      }
    }
    if {$best eq "NULL"} { break }
    lappend chain $best
    set cur $best
  }
  if {![llength $chain]} { continue }
  set far [center [lindex $chain end]]
  if {[dist $home $far] < 50000} { continue }
  foreach c [list $inst {*}[lrange $chain 0 end-1]] {
    if {[$c getPlacementStatus] in {FIRM LOCKED COVER}} { continue }
    $c setLocation [lindex $far 0] [lindex $far 1]
  }
  incr moved
}
puts "STUDENT_MINI_PULL_FLOPS flops=$total moved=$moved depth=$depth"
