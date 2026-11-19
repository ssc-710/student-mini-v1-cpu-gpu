# Read-only assertion on the generated database, not merely configuration text.
read_db $env(STUDENT_MINI_PDN_ODB)
set count 0
set pins 0
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  if {[[$inst getMaster] getName] ne "vortex_sp_32x1024_w4"} {
    error "Unexpected CPU SRAM master"
  }
  incr count
  foreach {pin expected kind} {vccd1 VDD POWER vssd1 VSS GROUND} {
    set terminal [$inst findITerm $pin]
    if {$terminal eq "NULL"} { error "Missing SRAM supply pin" }
    set net [$terminal getNet]
    if {$net eq "NULL" || [$net getName] ne $expected || [$net getSigType] ne $kind} {
      error "Incorrect SRAM power connection: [$inst getName]/$pin"
    }
    incr pins
  }
}
if {$count != 30 || $pins != 60} { error "Missing CPU macro supply connections" }
puts "CPU_MACRO_POWER_CONNECTED macros=30 pins=60"
