# Split the placed flat GPU into four quadrant partitions (hierarchical implementation).
# Environment:
#   STUDENT_MINI_LIBS      liberty files (space separated)
#   STUDENT_MINI_ODB       placed flat database (quadrant ring floorplan)
#   STUDENT_MINI_SDC       its SDC
#   STUDENT_MINI_OUT       output directory
#   STUDENT_MINI_RC        platform setRC.tcl
# Writes quad.v (top + four partition modules), nets.tsv (every net touching more than one
# partition or a chip port: driver arrival/slack, per-partition pin centroid), ports.tsv
# (chip port pin boxes) and macros.tsv (macro placement per partition).
foreach lib $env(STUDENT_MINI_LIBS) { read_liberty $lib }
read_db $env(STUDENT_MINI_ODB)
read_sdc $env(STUDENT_MINI_SDC)
source $env(STUDENT_MINI_RC)
set out $env(STUDENT_MINI_OUT)
set block [ord::get_db_block]
set dbu [$block getDbUnitsPerMicron]
set die [$block getDieArea]
set cx [expr {([$die xMin] + [$die xMax]) / 2}]
set cy [expr {([$die yMin] + [$die yMax]) / 2}]
proc quadrant {x y} {
  global cx cy
  return [expr {($x >= $cx) + 2 * ($y >= $cy)}]
}
# Standard cells may use a pinwheel of four split lines (STUDENT_MINI_SPLIT = "xb yl xt yr" in
# um: LL/LR line in the lower half, LL/UL line in the left half, UL/UR line in the upper half,
# LR/UR line in the right half) to balance the blocks' cell counts (detailed-routing memory
# grows with the cell count); macros always stay in their geometric quadrant.
set split {}
if {[info exists env(STUDENT_MINI_SPLIT)] && $env(STUDENT_MINI_SPLIT) ne ""} {
  foreach v $env(STUDENT_MINI_SPLIT) { lappend split [expr {$v * [$block getDbUnitsPerMicron]}] }
}
proc cell_region {x y} {
  global split
  if {![llength $split]} { return [quadrant $x $y] }
  lassign $split xb yl xt yr
  if {$y < $yl && $x < $xb} { return 0 }
  if {$x >= $xb && $y < $yr} { return 1 }
  if {$x < $xt} { return 2 }
  return 3
}
# Physical-only cells are re-created by every block flow.
set removed 0
foreach inst [$block getInsts] {
  set m [[$inst getMaster] getName]
  if {[string match *tapvpwrvgnd* $m] || [string match *fill* $m] || [string match *decap* $m]} {
    odb::dbInst_destroy $inst
    incr removed
  }
}
puts "STUDENT_MINI_PHYSICAL_ONLY_REMOVED $removed"
# Macro relocation (STUDENT_MINI_MACRO_MOVES, TSV instance x_um y_um orient, flat coordinates):
# keeps one SRAM array (e.g. all icache data slices) inside one quadrant so its half-cycle read
# paths stay block-internal.  Relocation happens before partitioning and parasitic estimation,
# so the macro's quadrant, its forced cone and the flat timing all follow the new location;
# the block flow re-places every standard cell.  Targets must not overlap any other macro.
if {[info exists env(STUDENT_MINI_MACRO_MOVES)] && $env(STUDENT_MINI_MACRO_MOVES) ne ""} {
  set mf [open $env(STUDENT_MINI_MACRO_MOVES)]
  set relocated {}
  while {[gets $mf line] >= 0} {
    if {$line eq ""} { continue }
    lassign [split $line "\t"] name x y orient
    set inst [$block findInst $name]
    if {$inst eq "NULL"} { set inst [$block findInst [string map {[ \\[ ] \\]} $name]] }
    if {$inst eq "NULL" || [[$inst getMaster] getType] ne "BLOCK"} { error "macro move: unknown macro $name" }
    set status [$inst getPlacementStatus]
    $inst setPlacementStatus PLACED
    $inst setOrient $orient
    $inst setLocation [expr {round($x * $dbu)}] [expr {round($y * $dbu)}]
    $inst setPlacementStatus $status
    lappend relocated $inst
  }
  close $mf
  foreach a $relocated {
    set ba [$a getBBox]
    foreach o [$block getInsts] {
      if {$o eq $a || [[$o getMaster] getType] ne "BLOCK"} { continue }
      set bo [$o getBBox]
      if {[$ba xMin] < [$bo xMax] && [$bo xMin] < [$ba xMax] && [$ba yMin] < [$bo yMax] && [$bo yMin] < [$ba yMax]} {
        error "macro move: [$a getName] overlaps [$o getName]"
      }
    }
  }
  puts "STUDENT_MINI_MACRO_MOVES relocated=[llength $relocated]"
}
set counts {0 0 0 0}
set mf [open $out/macros.tsv w]
foreach inst [$block getInsts] {
  set b [$inst getBBox]
  if {[[$inst getMaster] getType] eq "BLOCK"} {
    set q [quadrant [expr {([$b xMin] + [$b xMax]) / 2}] [expr {([$b yMin] + [$b yMax]) / 2}]]
  } else {
    set q [cell_region [expr {([$b xMin] + [$b xMax]) / 2}] [expr {([$b yMin] + [$b yMax]) / 2}]]
  }
  odb::dbIntProperty_create $inst partition_id $q
  lset counts $q [expr {[lindex $counts $q] + 1}]
  if {[[$inst getMaster] getType] eq "BLOCK"} {
    puts $mf [join [list [$inst getName] [[$inst getMaster] getName] $q [expr {[$b xMin] / double($dbu)}] \
                       [expr {[$b yMin] / double($dbu)}] [$inst getOrient]] "\t"]
  }
}
close $mf
puts "STUDENT_MINI_PARTITION_INSTANCES $counts"
estimate_parasitics -placement
# Timing-driven refinement.  The geometric cut puts near-critical paths across a block
# boundary (channel-edge pins, cross-channel wire); every block re-places its own cells,
# so cells need not stay in their geometric quadrant.  FM-style passes with locking: a
# logic cell on a critical cut net (flat slack < threshold) moves to the quadrant that
# holds most of the criticality-weighted pins of its critical nets; macros never move.
set thr [expr {[info exists env(STUDENT_MINI_CRIT_THR)] ? $env(STUDENT_MINI_CRIT_THR) : 2.5}]
set slack_of [dict create]
proc net_slack {net} {
  global slack_of
  set key [$net getId]
  if {[dict exists $slack_of $key]} { return [dict get $slack_of $key] }
  set s 1e30
  foreach it [$net getITerms] {
    if {[$it isOutputSignal]} {
      set pin [get_pins -quiet [$it getName {/}]]
      if {$pin ne ""} {
        set v [get_property $pin slack_max]
        if {$v ne "" && $v ne "INF"} { set s $v }
      }
      break
    }
  }
  dict set slack_of $key $s
  return $s
}
proc qof {inst} { return [[odb::dbIntProperty_find $inst partition_id] getValue] }
set locked [dict create]
set total_moves 0
# Forced propagation from the SRAM macros: their read data leaves only ~1 ns after the
# long OpenRAM access (flat arrival ~9 ns), so the critical cone downstream of every macro
# output, and upstream of every macro input, follows the macro's quadrant.
proc is_macro {inst} { return [expr {[[$inst getMaster] getType] eq "BLOCK"}] }
# STUDENT_MINI_CONE_THR: separate (smaller) criticality threshold for the macro cones
set cone_thr [expr {[info exists env(STUDENT_MINI_CONE_THR)] ? $env(STUDENT_MINI_CONE_THR) : $thr}]
set queue {}
foreach inst [$block getInsts] {
  if {![is_macro $inst]} { continue }
  set qm [qof $inst]
  foreach it [$inst getITerms] {
    set net [$it getNet]
    if {$net eq "NULL" || [$net isSpecial] || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
    if {[net_slack $net] >= $cone_thr} { continue }
    foreach o [$net getITerms] {
      set c [$o getInst]
      if {[is_macro $c] || [dict exists $locked [$c getId]]} { continue }
      [odb::dbIntProperty_find $c partition_id] setValue $qm
      dict set locked [$c getId] 1
      lappend queue [list $c $qm [expr {[$it isOutputSignal] ? 1 : -1}]]
      incr total_moves
    }
  }
}
set forced 0
while {[llength $queue]} {
  lassign [lindex $queue 0] c qm dir
  set queue [lrange $queue 1 end]
  foreach it [$c getITerms] {
    set net [$it getNet]
    if {$net eq "NULL" || [$net isSpecial] || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
    # downstream from macro outputs: follow this cell's output nets; upstream into macro
    # inputs: follow its input nets (to their drivers)
    if {($dir > 0) != [$it isOutputSignal]} { continue }
    if {[net_slack $net] >= $cone_thr} { continue }
    foreach o [$net getITerms] {
      set n [$o getInst]
      if {[is_macro $n] || [dict exists $locked [$n getId]]} { continue }
      if {$dir < 0 && ![$o isOutputSignal]} { continue }
      [odb::dbIntProperty_find $n partition_id] setValue $qm
      dict set locked [$n getId] 1
      lappend queue [list $n $qm $dir]
      incr forced
    }
  }
}
incr total_moves $forced
puts "STUDENT_MINI_REFINE_MACRO_CONES moved=$total_moves threshold=$cone_thr"
for {set pass 1} {$pass <= 12} {incr pass} {
  set candidates [dict create]
  foreach net [$block getNets] {
    if {[$net isSpecial] || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
    set qs {}
    foreach it [$net getITerms] { lappend qs [qof [$it getInst]] }
    if {[llength [lsort -unique $qs]] < 2} { continue }
    if {[net_slack $net] >= $thr} { continue }
    foreach it [$net getITerms] {
      set inst [$it getInst]
      if {[[$inst getMaster] getType] ne "BLOCK" && ![dict exists $locked [$inst getId]]} {
        dict set candidates [$inst getId] $inst
      }
    }
  }
  set moves 0
  dict for {id inst} $candidates {
    set w {0 0 0 0}
    foreach it [$inst getITerms] {
      set net [$it getNet]
      if {$net eq "NULL" || [$net isSpecial] || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
      set s [net_slack $net]
      if {$s >= $thr} { continue }
      set weight [expr {$thr - $s}]
      foreach o [$net getITerms] {
        if {[[$o getInst] getId] == $id} { continue }
        set q [qof [$o getInst]]
        lset w $q [expr {[lindex $w $q] + $weight}]
      }
      if {[llength [$net getBTerms]]} { lset w 1 [expr {[lindex $w 1] + $weight}] }
    }
    set cur [qof $inst]
    set best $cur
    for {set q 0} {$q < 4} {incr q} { if {[lindex $w $q] > [lindex $w $best]} { set best $q } }
    if {$best != $cur} {
      [odb::dbIntProperty_find $inst partition_id] setValue $best
      dict set locked $id 1
      incr moves
    }
  }
  incr total_moves $moves
  puts "STUDENT_MINI_REFINE pass=$pass candidates=[dict size $candidates] moves=$moves"
  if {$moves == 0} { break }
}
# Forced moves (STUDENT_MINI_MOVES, TSV instance -> quadrant): cells on ping-pong chains that
# cross a block boundary back and forth with negative path slack after a block iteration
# (scripts/student_mini_gpu_pingpong.py), moved to the block the chain comes from.
if {[info exists env(STUDENT_MINI_MOVES)] && $env(STUDENT_MINI_MOVES) ne ""} {
  set mf [open $env(STUDENT_MINI_MOVES)]
  set forced 0; set missing 0
  while {[gets $mf line] >= 0} {
    lassign [split $line "\t"] name target
    set inst [$block findInst $name]
    if {$inst eq "NULL"} { set inst [$block findInst [string map {[ \\[ ] \\]} $name]] }
    if {$inst eq "NULL"} { incr missing; continue }
    if {[[$inst getMaster] getType] eq "BLOCK"} { continue }
    [odb::dbIntProperty_find $inst partition_id] setValue $target
    incr forced
  }
  close $mf
  puts "STUDENT_MINI_FORCED_MOVES moved=$forced missing=$missing"
  if {$missing} { error "forced moves name unknown instances" }
}
# Feedthrough elimination: a logic cell none of whose neighbours is in its own quadrant
# (typically a placement buffer on a net between two other quadrants) makes a block-internal
# input->output path that per-net budgets cannot describe.  Move it to the quadrant holding
# most of its neighbours; repeat until stable (chains of such cells).
for {set pass 1} {$pass <= 20} {incr pass} {
  set moved 0
  foreach inst [$block getInsts] {
    if {[[$inst getMaster] getType] eq "BLOCK"} { continue }
    set own [qof $inst]
    set w {0 0 0 0}
    set any 0
    foreach it [$inst getITerms] {
      set net [$it getNet]
      if {$net eq "NULL" || [$net isSpecial] || [$net getSigType] in {POWER GROUND CLOCK}} { continue }
      foreach o [$net getITerms] {
        if {[[$o getInst] getId] == [$inst getId]} { continue }
        set q [qof [$o getInst]]
        lset w $q [expr {[lindex $w $q] + 1}]
        set any 1
      }
      if {[llength [$net getBTerms]]} {
        foreach bt [$net getBTerms] { foreach bp [$bt getBPins] { set b [$bp getBBox]
          set q [quadrant [expr {([$b xMin] + [$b xMax]) / 2}] [expr {([$b yMin] + [$b yMax]) / 2}]]
          lset w $q [expr {[lindex $w $q] + 1}]; set any 1 } }
      }
    }
    if {!$any || [lindex $w $own] > 0} { continue }
    set best 0
    for {set q 1} {$q < 4} {incr q} { if {[lindex $w $q] > [lindex $w $best]} { set best $q } }
    [odb::dbIntProperty_find $inst partition_id] setValue $best
    incr moved
  }
  puts "STUDENT_MINI_FEEDTHROUGH pass=$pass moved=$moved"
  incr total_moves $moved
  if {$moved == 0} { break }
}
set counts {0 0 0 0}
foreach inst [$block getInsts] { set q [qof $inst]; lset counts $q [expr {[lindex $counts $q] + 1}] }
puts "STUDENT_MINI_REFINED_INSTANCES $counts moves=$total_moves threshold=$thr"
set nf [open $out/nets.tsv w]
set cut 0
foreach net [$block getNets] {
  if {[$net isSpecial] || [$net getSigType] in {POWER GROUND}} { continue }
  set parts [dict create]
  set driver ""
  foreach it [$net getITerms] {
    set inst [$it getInst]
    set q [odb::dbIntProperty_find $inst partition_id]
    set q [$q getValue]
    lassign [$it getAvgXY] ok x y
    if {!$ok} { set b [$inst getBBox]; set x [expr {([$b xMin] + [$b xMax]) / 2}]; set y [expr {([$b yMin] + [$b yMax]) / 2}] }
    dict lappend parts $q [list $x $y]
    if {[$it isOutputSignal]} { set driver $it }
  }
  set ports [llength [$net getBTerms]]
  if {[dict size $parts] < 2 && $ports == 0} { continue }
  incr cut
  set arrival -1; set slack 1e30; set dq -1
  if {$driver ne ""} {
    set dq [[odb::dbIntProperty_find [$driver getInst] partition_id] getValue]
    set pin [get_pins -quiet [$driver getName {/}]]
    if {$pin ne ""} {
      set ar [get_property $pin arrival_max_rise]; set af [get_property $pin arrival_max_fall]
      set arrival [expr {max($ar eq "" ? -1 : $ar, $af eq "" ? -1 : $af)}]
      set s [get_property $pin slack_max]
      if {$s ne "" && $s ne "INF"} { set slack $s }
    }
  }
  set fields [list [$net getName] $dq $arrival $slack $ports]
  dict for {q pts} $parts {
    set sx 0; set sy 0
    foreach p $pts { set sx [expr {$sx + [lindex $p 0]}]; set sy [expr {$sy + [lindex $p 1]}] }
    set n [llength $pts]
    lappend fields "$q:$n:[expr {$sx / $n / double($dbu)}]:[expr {$sy / $n / double($dbu)}]"
  }
  puts $nf [join $fields "\t"]
}
close $nf
puts "STUDENT_MINI_CUT_NETS $cut"
set pf [open $out/ports.tsv w]
foreach bt [$block getBTerms] {
  foreach bp [$bt getBPins] {
    set b [$bp getBBox]
    puts $pf [join [list [$bt getName] [$bt getIoType] [expr {[$b xMin] / double($dbu)}] [expr {[$b yMin] / double($dbu)}] \
                         [expr {[$b xMax] / double($dbu)}] [expr {[$b yMax] / double($dbu)}]] "\t"]
  }
}
close $pf
write_partition_verilog -port_prefix part_ -module_suffix _q $out/quad.v
puts "STUDENT_MINI_PARTITION_COMPLETE"
