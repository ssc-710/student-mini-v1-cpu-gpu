# Assert real OpenDB connectivity after PDN generation, without changing it.
read_db $env(STUDENT_MINI_PDN_ODB)
set count 0
set pins 0
set allowed {vortex_dp_80x64_w4 vortex_sp_32x256_w1 vortex_sp_32x512_w4 vortex_sp_32x1024_w4 vortex_sp_64x128_w8 vortex_sp_128x128_w16}
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  if {[lsearch -exact $allowed [[$inst getMaster] getName]] < 0} {
    error "Unexpected GPU SRAM master"
  }
  incr count
  foreach {pin expected kind} {vccd1 VDD POWER vssd1 VSS GROUND} {
    set terminal [$inst findITerm $pin]
    if {$terminal eq "NULL"} { error "Missing GPU SRAM supply pin" }
    set net [$terminal getNet]
    if {$net eq "NULL" || [$net getName] ne $expected || [$net getSigType] ne $kind} {
      error "Incorrect GPU SRAM power connection: [$inst getName]/$pin"
    }
    incr pins
  }
}
if {$count != 37 || $pins != 74} { error "Missing GPU macro supply connections" }
puts "GPU_MACRO_POWER_CONNECTED macros=37 pins=74"
