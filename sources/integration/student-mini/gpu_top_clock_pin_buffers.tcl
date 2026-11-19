# POST_CTS_TCL of the GPU top level: one clock buffer next to the clock pin of every hardened quadrant block.
# The top-level tree is built in the cross channel (the only rows besides the narrow chip-edge strips), so without
# this the last tree buffer reaches a block's clk_i over ~1-1.4 mm of top wire, shared by up to three blocks.  The
# slow, rise/fall-asymmetric edge at the block pin then costs ~0.3 ns on the blocks' half-cycle (falling-edge SRAM)
# paths and skews the blocks against each other (full-chip STA of 2026-10-14, NOTES.md).  Each block pin gets its own
# buffer on the nearest row the cell fits (clkbuf_16, or the largest clkbuf that fits a narrow edge-strip row); the
# new cells are legalized here and the tree is re-timed by the later stages.  Logic is unchanged (buffers only).
set block [ord::get_db_block]
set db [ord::get_db]
set dbu [$block getDbUnitsPerMicron]
set masters {}
foreach m {clkbuf_16 clkbuf_8 clkbuf_4 clkbuf_2} { lappend masters [$db findMaster sky130_fd_sc_hd__$m] }
set vdd [$block findNet VDD]
set vss [$block findNet VSS]
set rows [$block getRows]
set added 0
foreach inst [$block getInsts] {
  if {![[$inst getMaster] isBlock]} { continue }
  set it [$inst findITerm clk_i]
  if {$it eq "NULL" || [$it getNet] eq "NULL"} { continue }
  set net [$it getNet]
  set pb [$it getBBox]
  set px [expr {([$pb xMin] + [$pb xMax]) / 2}]
  set py [expr {([$pb yMin] + [$pb yMax]) / 2}]
  # nearest row (distance from the pin to the row rectangle) that holds at least one of the buffers
  set best ""; set bestd 0
  foreach row $rows {
    set rb [$row getBBox]
    set w [expr {[$rb xMax] - [$rb xMin]}]
    if {$w < [[lindex $masters end] getWidth]} { continue }
    set dx [expr {$px < [$rb xMin] ? [$rb xMin] - $px : ($px > [$rb xMax] ? $px - [$rb xMax] : 0)}]
    set dy [expr {$py < [$rb yMin] ? [$rb yMin] - $py : ($py > [$rb yMax] ? $py - [$rb yMax] : 0)}]
    set d [expr {$dx + $dy}]
    if {$best eq "" || $d < $bestd} { set best $row; set bestd $d }
  }
  if {$best eq ""} { puts "STUDENT_MINI_TOP_CLOCK_PIN_BUFFER_NONE [$inst getName]"; continue }
  set rb [$best getBBox]
  set master ""
  foreach m $masters { if {[$m getWidth] <= [$rb xMax] - [$rb xMin]} { set master $m; break } }
  set site [[$best getSite] getWidth]
  set x [expr {min(max($px - [$master getWidth] / 2, [$rb xMin]), [$rb xMax] - [$master getWidth])}]
  set x [expr {[$rb xMin] + (($x - [$rb xMin]) / $site) * $site}]
  set name [$inst getName]
  set b [odb::dbInst_create $block $master "clkpin_buf_$name"]
  set nb [odb::dbNet_create $block "clkpin_net_$name"]
  $nb setSigType CLOCK
  $it disconnect
  $it connect $nb
  [$b findITerm X] connect $nb
  [$b findITerm A] connect $net
  foreach pg {VPWR VPB} { set t [$b findITerm $pg]; if {$t ne "NULL"} { $t connect $vdd } }
  foreach pg {VGND VNB} { set t [$b findITerm $pg]; if {$t ne "NULL"} { $t connect $vss } }
  $b setOrient [$best getOrient]
  $b setLocation $x [$rb yMin]
  $b setPlacementStatus PLACED
  incr added
  puts "STUDENT_MINI_TOP_CLOCK_PIN_BUFFER $name [$master getName] at [expr {double($x)/$dbu}] [expr {double([$rb yMin])/$dbu}] pin_distance_um [expr {double($bestd)/$dbu}]"
}
detailed_placement
check_placement
estimate_parasitics -placement
puts "STUDENT_MINI_TOP_CLOCK_PIN_BUFFERS $added"
