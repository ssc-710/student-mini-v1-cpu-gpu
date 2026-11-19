# Read-only actual placed database observation; not pin-access or route signoff.
read_db $env(STUDENT_MINI_GEOMETRY_ODB)
set block [ord::get_db_block]
set units [$block getDbUnitsPerMicron]
puts "MINI_GEOMETRY_UNITS $units"
set cells 0
foreach inst [$block getInsts] {
  set box [$inst getBBox]
  if {[[$inst getMaster] getType] eq "BLOCK"} {
    puts "MINI_GEOMETRY_MACRO [binary encode hex [$inst getName]] [$box xMin] [$box yMin] [$box xMax] [$box yMax]"
  } else {
    incr cells
    set x [expr {int(([$box xMin]+[$box xMax])/2.0/$units/100)}]
    set y [expr {int(([$box yMin]+[$box yMax])/2.0/$units/100)}]
    set key "$x,$y"
    if {![info exists bins($key)]} { set bins($key) 0 }
    incr bins($key) [expr {([$box xMax]-[$box xMin])*([$box yMax]-[$box yMin])}]
  }
}
foreach key [lsort [array names bins]] {
  puts "MINI_GEOMETRY_CELL_BIN $key $bins($key)"
}
set shapes 0
foreach net [$block getNets] {
  if {[$net getSigType] ni {POWER GROUND}} { continue }
  foreach wire [$net getSWires] {
    foreach box [$wire getWires] {
      if {[$box isVia]} { continue }
      incr shapes
      puts "MINI_GEOMETRY_SUPPLY [[$box getTechLayer] getName] [$box xMin] [$box yMin] [$box xMax] [$box yMax]"
    }
  }
}
puts "MINI_GEOMETRY_COMPLETE cells=$cells supply_shapes=$shapes"
