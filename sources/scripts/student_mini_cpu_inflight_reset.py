"""Interrupt one observed DFI read, retain RAM, verify a complete reboot."""
import re
from scripts.resume_student_mini_interrupted import replace_once
from scripts.student_mini_cpu_warm_reset import bridge_source as warm_bridge


def bridge_source(source):
    source=warm_bridge(source)
    source=replace_once(source,'input wire force_reset_i,',
        'input wire force_reset_i,output wire observed_read_request,output wire observed_read_response,')
    return replace_once(source,'  assign uart_data=',
        '  assign observed_read_request=actual_build_soc_coursesimsoc_dfi_p0_rddata_en;\n'
        '  assign observed_read_response=actual_build_soc_coursesimsoc_dfi_p0_rddata_valid;\n'
        '  assign uart_data=')


def driver_source(source):
    source=replace_once(source,'\n  device->sys_clk = 0;\n',
        '\n  device->force_reset_i = 0;\n  device->sys_clk = 0;\n')
    source=replace_once(source,'  bool baseline = false, native = false;',
        '  bool baseline = false, native = false;\n'
        '  bool interrupted = false, recovered = false;\n'
        '  uint64_t release_cycle = 0;\n'
        '  std::cout << "INFLIGHT_INITIAL_BEGIN\\n" << std::flush;')
    source=replace_once(source,'    advance(cycle * 10000 + 5000);',
        '    if (interrupted && !recovered && cycle == release_cycle) {\n'
        '      device->force_reset_i = 0; recovered = true;\n'
        '      std::cout << "INFLIGHT_RESET_RELEASE held_cycles=8\\nINFLIGHT_RECOVERY_BEGIN\\n" << std::flush;\n'
        '    }\n    advance(cycle * 10000 + 5000);')
    source=replace_once(source,'    bool valid = device->uart_valid;',
        '    bool request_on_edge = device->observed_read_request;\n'
        '    bool response_on_edge = device->observed_read_response;\n'
        '    if (device->force_reset_i && device->uart_valid) {\n'
        '      std::cerr << "INFLIGHT_RESET_UART_NOT_SILENT\\n"; return 6;\n'
        '    }\n'
        '    bool valid = device->uart_valid && !device->force_reset_i;')
    source=replace_once(source,'    if (context->gotFinish()) return 2;',
        '    if (!interrupted && next_ordinal >= 1 && request_on_edge && !response_on_edge) {\n'
        '      std::cout << "INFLIGHT_READ_ACCEPTED request=1 response=0 cycle=" << cycle << "\\n" << std::flush;\n'
        '      interrupted = true; device->force_reset_i = 1; release_cycle = cycle + 9;\n'
        '      baseline = false; native = false; next_ordinal = 0; line.clear();\n'
        '      std::cout << "INFLIGHT_RESET_ASSERT\\n" << std::flush;\n'
        '    }\n'
        '    if (context->gotFinish()) return 2;')
    source=replace_once(source,'    if (baseline && native) {',
        '    if (baseline && native && recovered) {')
    return replace_once(source,'"CPU_BOUNDARY_REPLAY_COMPLETE cycles="',
        '"INFLIGHT_RECOVERY_COMPLETE cycles="')


def read_phases(path):
    records=[];markers=[];recovering=False
    with path.open() as source:
        for line in source:
            line=line.rstrip('\r\n')
            if line.startswith('INFLIGHT_'):
                markers.append(line)
                if line=='INFLIGHT_RECOVERY_BEGIN':recovering=True
                elif line.startswith('INFLIGHT_RECOVERY_COMPLETE '):recovering=False
            elif recovering and line.startswith(('STUDENT_CPU ','STUDENT_CPU_','STUDENT_NATIVE_')):
                records.append(line)
    patterns=[r'INFLIGHT_INITIAL_BEGIN',r'INFLIGHT_READ_ACCEPTED request=1 response=0 cycle=\d+',
        r'INFLIGHT_RESET_ASSERT',r'INFLIGHT_RESET_RELEASE held_cycles=8',
        r'INFLIGHT_RECOVERY_BEGIN',r'INFLIGHT_RECOVERY_COMPLETE cycles=\d+']
    if len(markers)!=len(patterns) or any(not re.fullmatch(p,m) for p,m in zip(patterns,markers)):
        raise ValueError('missing, duplicated or unobserved in-flight read/reset/recovery')
    return ['\n'.join(records)+'\n']


def producer_source(source):
    changes={
        'from scripts.student_mini_cpu_warm_reset import bridge_source, driver_source, read_phases, compare_baselines':
            'from scripts.student_mini_cpu_inflight_reset import bridge_source, driver_source, read_phases\nfrom scripts.student_mini_cpu_warm_reset import compare_baselines',
        "paths = [Path(__file__),": "paths = [Path(__file__), ROOT/'scripts/run_student_mini_cpu_warm_reset.py', ROOT/'scripts/student_mini_cpu_inflight_reset.py', ROOT/'scripts/run_student_mini_cpu_inflight_reset.py',",
        "ROOT/'build/student-mini/cpu-warm-reset'": "ROOT/'build/student-mini/cpu-inflight-reset'",
        "in_flight_reset_qualified=False, warm_reset_at_quiescent_boundary_complete=False":
            "in_flight_reset_qualified=False, dfi_read_interruption_qualified=False",
        "heartbeat('EXECUTING_COLD_AND_WARM_PHASES')": "heartbeat('EXECUTING_DFI_READ_INTERRUPTION_AND_RECOVERY')",
        "result.update(status='CPU_QUIESCENT_WARM_RESET_STAGE_PASS',\n                          warm_reset_at_quiescent_boundary_complete=True, phase_baseline_records=[1000,1000],":
            "result.update(status='CPU_DFI_READ_RESET_RECOVERY_STAGE_PASS',\n                          dfi_read_interruption_qualified=True, phase_baseline_records=[1000],",
        "reason='Real ASIC reset after a complete workload, retained external RAM, full outputs and model states independently verified; in-flight reset and other protocol gates remain'":
            "reason='Observed DFI read request without returned data interrupted after acceptance; ASIC reset held eight cycles with UART silent, retained external RAM, complete 1000 outputs and model states verified. Scope is one read-abort recovery, not full write/error/Wishbone protocol qualification'",
        "return 0 if result['warm_reset_at_quiescent_boundary_complete'] else 1":
            "return 0 if result['dfi_read_interruption_qualified'] else 1",
    }
    for old,new in changes.items():source=replace_once(source,old,new)
    return source
