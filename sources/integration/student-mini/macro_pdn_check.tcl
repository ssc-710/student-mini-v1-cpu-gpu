# Floorplan-stage power check of the hard macros: every VDD/VSS pin of every BLOCK instance must be
# touched by a same-net special wire (stripe, via or bridge) of the top-level grid.  Run on the PDN
# stage database before committing hours of place-and-route.  Environment: STUDENT_MINI_ODB.
read_db $env(STUDENT_MINI_ODB)
set block [ord::get_db_block]
set shapes [dict create]
foreach name {VDD VSS} {
  set net [$block findNet $name]
  foreach sw [$net getSWires] {
    foreach box [$sw getWires] {
      if {[$box isVia]} {
        set via [$box getTechVia]
        if {$via eq "NULL"} { set via [$box getBlockVia] }
        set layers [list [[$via getBottomLayer] getName] [[$via getTopLayer] getName]]
      } else {
        set layers [list [[$box getTechLayer] getName]]
      }
      foreach l $layers { dict lappend shapes "$name/$l" [list [$box xMin] [$box yMin] [$box xMax] [$box yMax]] }
    }
  }
}
set bad 0; set ok 0
foreach inst [$block getInsts] {
  if {![[$inst getMaster] isBlock]} { continue }
  foreach it [$inst getITerms] {
    set mt [$it getMTerm]
    set sig [$mt getSigType]
    if {$sig ne "POWER" && $sig ne "GROUND"} { continue }
    set net [$it getNet]
    if {$net eq "NULL"} { incr bad; puts "STUDENT_MINI_MACRO_PDN_UNCONNECTED [$inst getName] [$mt getName] (no net)"; continue }
    # transformed bounding box of the instance pin, tested against same-net shapes on the pin layers
    set r [$it getBBox]
    set pin_layers {}
    foreach mp [$mt getMPins] { foreach g [$mp getGeometry] { lappend pin_layers [[$g getTechLayer] getName] } }
    set touched 0
    foreach l [lsort -unique $pin_layers] {
      set key "[$net getName]/$l"
      if {![dict exists $shapes $key]} { continue }
      foreach s [dict get $shapes $key] {
        lassign $s x0 y0 x1 y1
        if {$x0 <= [$r xMax] && $x1 >= [$r xMin] && $y0 <= [$r yMax] && $y1 >= [$r yMin]} { set touched 1; break }
      }
      if {$touched} { break }
    }
    if {$touched} { incr ok } else { incr bad; puts "STUDENT_MINI_MACRO_PDN_UNCONNECTED [$inst getName] [$mt getName]" }
  }
}
puts "STUDENT_MINI_MACRO_PDN connected=$ok unconnected=$bad"
