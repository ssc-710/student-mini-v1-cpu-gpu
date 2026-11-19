# Read-only post-route audit of a platform (CPU/GPU) database.
# Prints machine-readable lines; the caller decides acceptance.
read_db $env(STUDENT_MINI_ROUTE_ODB)
set block [ord::get_db_block]
set macros 0
set supply_ok 0
set supply_bad 0
set signals 0
set unrouted 0
foreach inst [$block getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  incr macros
  foreach term [$inst getITerms] {
    set mterm [$term getMTerm]
    set net [$term getNet]
    set kind [$mterm getSigType]
    if {$kind in {POWER GROUND}} {
      set expected [expr {$kind eq "POWER" ? "VDD" : "VSS"}]
      if {$net ne "NULL" && [$net getName] eq $expected && [$net getSigType] eq $kind} {
        incr supply_ok
      } else {
        incr supply_bad
        puts "PLATFORM_AUDIT_SUPPLY_BAD [$inst getName]/[$mterm getName]"
      }
      continue
    }
    if {$net eq "NULL"} { continue }
    incr signals
    # pin access/reach is checked geometrically by audit_macro_pins.py; a net without another
    # terminal (output without loads) needs no wire
    if {[llength [$net getITerms]] + [llength [$net getBTerms]] < 2} { continue }
    if {[$net getWire] eq "NULL"} {
      incr unrouted
      puts "PLATFORM_AUDIT_UNROUTED [$inst getName]/[$mterm getName]"
    }
  }
}
puts "PLATFORM_AUDIT_MACROS macros=$macros supply_ok=$supply_ok supply_bad=$supply_bad signals=$signals unrouted=$unrouted"
# Physical power-grid connectivity (shapes, vias and instance pins), not just netlist.
foreach net {VDD VSS} {
  if {[catch {check_power_grid -net $net} err]} {
    puts "PLATFORM_AUDIT_PDN net=$net status=FAIL detail=[string map {"\n" " "} $err]"
  } else {
    puts "PLATFORM_AUDIT_PDN net=$net status=PASS"
  }
}
# Antenna check of the final database (after all repair rounds and fill).
puts "PLATFORM_AUDIT_ANTENNA nets=[check_antennas]"
puts "PLATFORM_AUDIT_COMPLETE"
