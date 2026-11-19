# POST_PDN_TCL of the four-quadrant GPU top: pdngen stops the top met5 stripes a few microns
# before the block power pins (it keeps spacing to instance pins), so every met5 VDD/VSS pin of a
# hardened block gets a same-net met5 bridge that covers the pin and reaches past both block-pin
# ends into the abutting top stripe segments (channels and die-edge strips).
set block [ord::get_db_block]
set tech_layer [[ord::get_db_tech] findLayer met5]
set reach [ord::microns_to_dbu 12.0]
set bridged 0
foreach inst [$block getInsts] {
  set master [$inst getMaster]
  if {![$master isBlock]} { continue }
  if {[$inst getOrient] ne "R0"} { error "block [$inst getName] not R0" }
  lassign [$inst getOrigin] ox oy
  foreach mt [$master getMTerms] {
    set sig [$mt getSigType]
    if {$sig ne "POWER" && $sig ne "GROUND"} { continue }
    set net [$block findNet [expr {$sig eq "POWER" ? "VDD" : "VSS"}]]
    set swire [odb::dbSWire_create $net ROUTED]
    foreach mp [$mt getMPins] {
      foreach g [$mp getGeometry] {
        if {[[$g getTechLayer] getName] ne "met5"} { continue }
        odb::dbSBox_create $swire $tech_layer \
          [expr {[$g xMin] + $ox - $reach}] [expr {[$g yMin] + $oy}] \
          [expr {[$g xMax] + $ox + $reach}] [expr {[$g yMax] + $oy}] STRIPE
        incr bridged
      }
    }
  }
}
puts "STUDENT_MINI_TOP_PDN_BRIDGES $bridged"
