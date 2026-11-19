foreach lib $::env(GATE_POWER_LIBS) { read_liberty $lib }
read_db $::env(GATE_POWER_ODB)
read_sdc $::env(GATE_POWER_SDC)
read_spef $::env(GATE_POWER_SPEF)
# One session, every workload: each SAIF re-annotates every pin it lists.
foreach {saif out} $::env(GATE_POWER_ITEMS) {
  read_saif -scope $::env(GATE_POWER_SCOPE) $saif
  report_activity_annotation -report_unannotated > $out/annotation.rpt
  report_power -format json -digits 15 > $out/power.json
  report_power > $out/power.rpt
}
