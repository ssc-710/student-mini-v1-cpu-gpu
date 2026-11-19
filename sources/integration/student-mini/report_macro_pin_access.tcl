# Read-only post-route probe. No field-only assertion can replace this database.
read_db $env(STUDENT_MINI_ROUTE_ODB)
set count 0
set signals 0
set unused 0
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  incr count
  set inst_hex [binary encode hex [$inst getName]]
  set master_hex [binary encode hex [[$inst getMaster] getName]]
  puts "MINI_ACCESS_MACRO instance=$inst_hex master=$master_hex"
  foreach term [$inst getITerms] {
    set mterm [$term getMTerm]
    if {[$mterm getSigType] in {POWER GROUND}} { continue }
    set pin_hex [binary encode hex [$mterm getName]]
    set net [$term getNet]
    if {$net eq "NULL"} {
      incr unused
      puts "MINI_ACCESS_UNUSED instance=$inst_hex pin=$pin_hex"
      continue
    }
    incr signals
    set ap_count [llength [$term getPrefAccessPoints]]
    set routed [expr {[$net getWire] ne "NULL"}]
    set net_hex [binary encode hex [$net getName]]
    puts "MINI_ACCESS_PIN instance=$inst_hex pin=$pin_hex net=$net_hex access_points=$ap_count routed=$routed"
  }
}
puts "MINI_ACCESS_COMPLETE macros=$count connected_signals=$signals unused_signals=$unused"
