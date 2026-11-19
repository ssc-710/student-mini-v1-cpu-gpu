# Calibrated wire RC for the parasitic estimates of placement, resizing, CTS and global-route repair
# (PRE_GLOBAL_PLACE / PRE_RESIZE / PRE_CTS / PRE_GLOBAL_ROUTE hook; ORFS sources the platform setRC.tcl
# when it loads each stage, this runs right after and replaces the layer values).
# The sky130hd setRC.tcl layer values read optimistic against the RCX SPEF that ORFS extracts from the
# routed blocks (sign-off parasitics of the full-chip STA): on the routed UL GPU block the global-route
# estimate gave WNS -0.79 / worst reg2reg -0.17 ns where the final SPEF gives -1.09 / -0.55 ns; scaling
# every layer's R and C by 1.1 gives -1.01 / -0.85 ns (slightly pessimistic).  Without the calibration,
# timing repair leaves 0.4-0.55 ns violations that only appear after detailed routing.
# STUDENT_MINI_RC_SCALE: scale factor (default 1.1).
set k [expr {[info exists ::env(STUDENT_MINI_RC_SCALE)] ? $::env(STUDENT_MINI_RC_SCALE) : 1.1}]
foreach {layer c r} {
  li1  1.499e-04   7.176e-02
  met1 1.72375E-04 1.20565E-03
  met2 1.36233E-04 1.22132E-03
  met3 2.14962E-04 1.66281E-04
  met4 1.48128E-04 1.68093E-04
  met5 1.54087E-04 1.83558E-05
} {
  set_layer_rc -layer $layer -capacitance [expr {$c * $k}] -resistance [expr {$r * $k}]
}
set_wire_rc -signal -layer met1
set_wire_rc -clock -layer met3
puts "STUDENT_MINI_RC_SCALE $k"
