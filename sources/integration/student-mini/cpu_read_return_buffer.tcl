# One explicitly checked combinational buffer; no sequential or clock changes.
set block [ord::get_db_block]
set driver [$block findInst _095039_]
set sink [$block findInst _095042_]
if {$driver == "NULL" || $sink == "NULL"} {error "observed CPU cell missing"}
if {[[$driver getMaster] getName] ne "sky130_fd_sc_hd__a222oi_1"} {error "CPU critical driver changed"}
if {[[$sink getMaster] getName] ne "sky130_fd_sc_hd__o21ai_0"} {error "CPU critical sink changed"}
set driver_pin [$driver findITerm Y]
set sink_pin [$sink findITerm A2]
set old_net [$driver_pin getNet]
if {$old_net == "NULL" || [$sink_pin getNet] ne $old_net} {error "CPU critical net changed"}
if {[llength [$old_net getITerms]] != 2 || [llength [$old_net getBTerms]] != 0} {error "CPU critical net fanout changed"}
set before [dict create]
foreach inst [$block getInsts] {dict set before [$inst getName] 1}
set xy [$driver getLocation]
set dbu [$block getDbUnitsPerMicron]
set x [expr {double([lindex $xy 0]) / $dbu}]
set y [expr {double([lindex $xy 1]) / $dbu}]
insert_buffer -buffer_cell sky130_fd_sc_hd__buf_4 -net [get_nets [$old_net getName]] \
    -location [list $x $y] -buffer_name mini_cpu_read_buffer -net_name mini_cpu_read_buffer_net
set added [list]
foreach inst [$block getInsts] {
    if {![dict exists $before [$inst getName]]} {lappend added $inst}
}
if {[llength $added] != 1 || [llength [$block getInsts]] != [dict size $before]+1} {error "not exactly one new buffer"}
set buffer [lindex $added 0]
if {[[$buffer getMaster] getName] ne "sky130_fd_sc_hd__buf_4"} {error "wrong inserted buffer"}
set input_net [[$buffer findITerm A] getNet]
set output_net [[$buffer findITerm X] getNet]
if {$input_net ne [$driver_pin getNet] || $output_net ne [$sink_pin getNet] || $input_net eq $output_net} {
    error "buffer does not implement the original direct driver-to-sink function"
}
foreach net [list $input_net $output_net] {
    if {[llength [$net getITerms]] != 2 || [llength [$net getBTerms]] != 0} {error "extra signal connection introduced"}
}
global_connect
puts "CPU_SINGLE_BUFFER_INSERTED driver=_095039_/Y sink=_095042_/A2 cell=sky130_fd_sc_hd__buf_4"
