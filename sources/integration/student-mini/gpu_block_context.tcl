# Timing context of the GPU quadrant blocks inside the assembled chip (OpenSTA, same loading as gpu_fullchip_sta.tcl:
# top netlist + the four routed block netlists, every SPEF, the GPU constraint, propagated clocks).
# For every block instance listed in STUDENT_MINI_CONTEXT_BLOCKS this writes <STUDENT_MINI_CONTEXT_OUT>/<instance>.sdc,
# a constraint overlay that puts the block's own STA (block netlist + block SPEF + block SDC) into its real chip
# surroundings, in the block's time frame (t = 0 where the chip's rising clock edge reaches the block's clock input,
# c = that arrival in chip time, cf = the falling edge's):
#   clk_i     set_input_transition = the edge rates at the block's first clock cell; the falling edge's arrival
#             relative to the rising one as -source latency of the falling edge (cf - c - period/2),
#   inputs    the budget delays are removed; per launching edge of the arriving data (chip arrival tags, chip I/O
#             included, in absolute chip time) set_input_delay -max/-min = arrival - c (rising launch, rising
#             reference) or arrival - cf (falling launch, -clock_fall reference),
#   outputs   the budget's setup delays are removed (its hold budgets stay: the chip hold is closed); per launching
#             edge of the departing data, with q_r / q_f the chip setup required times of rising- / falling-launched
#             data: -clock_fall reference cf - q_r (rising launch: capture at the next falling edge reproduces q_r),
#             rising reference period - (q_f - c) (falling launch: capture at the next rising edge reproduces q_f);
#             with both, each launch sees the stricter of its own and the other reference (never optimistic).
# Values are taken at the first cell behind / the driver in front of each port, so they include the block's own port
# wire once more (pessimistic by that wire for setup).  A port without any timed chip path (e.g. a feedthrough that
# the top level bypasses, prepare_student_mini_gpu_top.py direct_chip_feedthroughs) is not timed (set_false_path):
# its budget describes a path that does not exist in the chip.
# Used by the context post-route ECO (run_student_mini_platform_physical_ctx.py --eco-context).
foreach lib $env(STUDENT_MINI_LIBS) { read_liberty $lib }
foreach {inst netlist spef} $env(STUDENT_MINI_BLOCKS) { read_verilog $netlist }
read_verilog $env(STUDENT_MINI_TOP_V)
link_design $env(STUDENT_MINI_TOP)
read_sdc $env(STUDENT_MINI_SDC)
set_propagated_clock [all_clocks]
if {$env(STUDENT_MINI_TOP_SPEF) ne ""} { read_spef $env(STUDENT_MINI_TOP_SPEF) }
foreach {inst netlist spef} $env(STUDENT_MINI_BLOCKS) { read_spef -path $inst $spef }
set period [get_property [get_clocks core_clock] period]
# setup margin of the overlay (STUDENT_MINI_CONTEXT_MARGIN, default 0.1 ns): the block-frame re-timing reproduces the chip
# within a few 10 ps (the clock's own port wire is counted once in the block, not in c); arrivals are made later and
# required times earlier by the margin so that the ECO aims at the chip with that slack.  Hold values are unchanged.
set margin [expr {[info exists env(STUDENT_MINI_CONTEXT_MARGIN)] ? $env(STUDENT_MINI_CONTEXT_MARGIN) : 0.1}]

proc captured {cmd pin} {
  sta::redirect_string_begin
  $cmd -digits 4 $pin
  return [sta::redirect_string_end]
}
# "(clk ^) r a:b f c:d" lines -> dict launch edge (^ or v) -> {min max}: arrivals (strict = 0) keep the earliest min
# and the latest max of both data transitions and every clock; required times (strict = 1) the latest min (hold) and
# the earliest max (setup).  "---" = no path.
proc tagged {text strict} {
  set out [dict create]
  foreach line [split $text \n] {
    if {![regexp {^\(\S+ (\^|v)\) r (\S+):(\S+) f (\S+):(\S+)} $line -> edge a b c d]} { continue }
    lassign [expr {[dict exists $out $edge] ? [dict get $out $edge] : {{} {}}}] lo hi
    foreach {mn mx} [list $a $b $c $d] {
      if {$mn ne "---" && ($lo eq "" || ($strict ? $mn > $lo : $mn < $lo))} { set lo $mn }
      if {$mx ne "---" && ($hi eq "" || ($strict ? $mx < $hi : $mx > $hi))} { set hi $mx }
    }
    if {$hi ne ""} { dict set out $edge [list $lo $hi] }
  }
  return $out
}
proc leaf_pins {inst port dir} {
  set net [get_nets -quiet "$inst/$port"]
  if {![llength $net]} { return {} }
  set out {}
  foreach lp [get_pins -quiet -of_objects $net] {
    set rel [string range [get_full_name $lp] [expr {[string length $inst] + 1}] end]
    if {[string first / $rel] < 0} { continue }
    if {[get_property $lp direction] eq $dir} { lappend out $lp }
  }
  return $out
}
proc fmt {x} { return [format %.4f $x] }

foreach inst $env(STUDENT_MINI_CONTEXT_BLOCKS) {
  set f [open [file join $env(STUDENT_MINI_CONTEXT_OUT) $inst.sdc] w]
  puts $f "# chip timing context of $inst (gpu_block_context.tcl); block time frame: t = 0 at the rising edge at clk_i; setup margin $margin ns"
  set clk [lindex [leaf_pins $inst clk_i input] 0]
  set ct [tagged [captured report_arrival $clk] 0]
  set c [lindex [dict get $ct ^] 1]
  set cf [lindex [dict get $ct v] 1]
  regexp {\^ (\S+):(\S+) v (\S+):(\S+)} [captured report_slews $clk] -> srmin srmax sfmin sfmax
  puts $f "set_input_transition -rise [fmt $srmax] \[get_ports clk_i\]"
  puts $f "set_input_transition -fall [fmt $sfmax] \[get_ports clk_i\]"
  puts $f "set_clock_latency -source -fall [fmt [expr {$cf - $period / 2.0 - $c}]] \[get_clocks core_clock\]"
  puts "STUDENT_MINI_CONTEXT_CLOCK $inst margin=$margin rise=$c fall=$cf slew_rise=$srmax slew_fall=$sfmax"
  set nin 0; set nout 0; set nskip 0
  foreach hp [get_pins $inst/*] {
    set port [string range [get_full_name $hp] [expr {[string length $inst] + 1}] end]
    if {$port eq "clk_i"} { continue }
    set dir [get_property $hp direction]
    set ref "\[get_ports {$port}\]"
    if {$dir eq "input"} {
      set tags [dict create]
      foreach lp [leaf_pins $inst $port input] {
        dict for {edge v} [tagged [captured report_arrival $lp] 0] {
          lassign $v lo hi
          if {[dict exists $tags $edge]} {
            lassign [dict get $tags $edge] olo ohi
            if {$olo ne "" && ($lo eq "" || $olo < $lo)} { set lo $olo }
            if {$ohi > $hi} { set hi $ohi }
          }
          dict set tags $edge [list $lo $hi]
        }
      }
      if {![dict size $tags]} { puts $f "set_false_path -from $ref"; incr nskip; continue }
      puts $f "unset_input_delay -clock core_clock $ref"
      puts $f "unset_input_delay -clock core_clock -clock_fall $ref"
      dict for {edge v} $tags {
        lassign $v lo hi
        set base [expr {$edge eq "^" ? $c : $cf}]
        set cf_opt [expr {$edge eq "^" ? "" : " -clock_fall"}]
        puts $f "set_input_delay -max [fmt [expr {$hi - $base + $margin}]] -clock core_clock$cf_opt -add_delay $ref"
        if {$lo ne ""} { puts $f "set_input_delay -min [fmt [expr {$lo - $base}]] -clock core_clock$cf_opt -add_delay $ref" }
      }
      incr nin
    } elseif {$dir eq "output"} {
      set drv [lindex [leaf_pins $inst $port output] 0]
      set tags [expr {$drv eq "" ? [dict create] : [tagged [captured report_required $drv] 1]}]
      if {![dict size $tags]} { puts $f "set_false_path -to $ref"; incr nskip; continue }
      puts $f "unset_output_delay -max -clock core_clock $ref"
      puts $f "unset_output_delay -max -clock core_clock -clock_fall $ref"
      if {[dict exists $tags ^]} {
        puts $f "set_output_delay -max [fmt [expr {$cf - [lindex [dict get $tags ^] 1] + $margin}]] -clock core_clock -clock_fall -add_delay $ref"
      }
      if {[dict exists $tags v]} {
        puts $f "set_output_delay -max [fmt [expr {$period - ([lindex [dict get $tags v] 1] - $c) + $margin}]] -clock core_clock -add_delay $ref"
      }
      incr nout
    }
  }
  close $f
  puts "STUDENT_MINI_CONTEXT_BLOCK $inst inputs=$nin outputs=$nout untimed=$nskip"
}
puts "STUDENT_MINI_CONTEXT_COMPLETE"
