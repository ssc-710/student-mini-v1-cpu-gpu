"""Observation-only port recorder appended to the CPU replay bridge.

At every rising edge of sys_clk the ports of the `actual` mapped CPU instance
are written when they change ("I cycle hex" / "O cycle hex", concatenated MSB
first in header order).  Per-record measurement windows come from the CPU's
own traffic-counter CSRs: "W cycle B" when build_soc_cpu_traffic_reset_storage
falls (counters released) and "W cycle E" when
build_soc_cpu_traffic_capture_storage rises (counters captured).  "E cycle"
closes the trace at the end of simulation.  Nothing is driven.
"""
CLOCK = 'sys_clk'
RESET = 'build_soc_cpu_traffic_reset_storage'
CAPTURE = 'build_soc_cpu_traffic_capture_storage'
MARK = '  // ---- Port-activity recorder (gate-level power stimulus; observation only) ----\n'


def recorder(ports: dict) -> str:
    inputs = [(n, len(p['bits'])) for n, p in ports.items() if p['direction'] == 'input' and n != CLOCK]
    outputs = [(n, len(p['bits'])) for n, p in ports.items() if p['direction'] == 'output']
    wi, wo = sum(w for _, w in inputs), sum(w for _, w in outputs)
    nl = chr(92) + 'n'
    header = [f'L C {CLOCK} 1'] + [f'L I {n} {w}' for n, w in inputs] + [f'L O {n} {w}' for n, w in outputs]
    lines = [MARK,
             f'  wire [{wi - 1}:0] trace_in = {{' + ', '.join(f'actual.{n}' for n, _ in inputs) + '};\n',
             f'  wire [{wo - 1}:0] trace_out = {{' + ', '.join(f'actual.{n}' for n, _ in outputs) + '};\n',
             '  integer trace_fd;\n  longint trace_cycle;\n',
             f'  reg [{wi - 1}:0] trace_in_q;\n  reg [{wo - 1}:0] trace_out_q;\n  reg trace_started, trace_reset_q, trace_capture_q;\n',
             '  initial begin\n    trace_fd = $fopen("port-trace.txt", "w");\n']
    lines += [f'    $fwrite(trace_fd, "{h}{nl}");\n' for h in header]
    lines += ['    trace_cycle = 0;\n    trace_started = 1\'b0;\n  end\n',
              f'  always @(posedge {CLOCK}) begin\n',
              f'    if (trace_started && trace_reset_q && !actual.{RESET}) $fwrite(trace_fd, "W %0d B{nl}", trace_cycle);\n',
              f'    if (trace_started && !trace_capture_q && actual.{CAPTURE}) $fwrite(trace_fd, "W %0d E{nl}", trace_cycle);\n',
              f'    if (!trace_started || trace_in != trace_in_q) $fwrite(trace_fd, "I %0d %h{nl}", trace_cycle, trace_in);\n',
              f'    if (!trace_started || trace_out != trace_out_q) $fwrite(trace_fd, "O %0d %h{nl}", trace_cycle, trace_out);\n',
              '    trace_in_q <= trace_in;\n    trace_out_q <= trace_out;\n',
              f'    trace_reset_q <= actual.{RESET};\n    trace_capture_q <= actual.{CAPTURE};\n',
              "    trace_started <= 1'b1;\n    trace_cycle <= trace_cycle + 1;\n  end\n",
              f'  final begin\n    $fwrite(trace_fd, "E %0d{nl}", trace_cycle);\n    $fclose(trace_fd);\n  end\n']
    return ''.join(lines)


def traced(bridge: str, ports: dict) -> str:
    body = bridge.rstrip()
    if not body.endswith('endmodule') or body.count('endmodule') != 1:
        raise ValueError('unexpected CPU replay bridge layout')
    return body[:-len('endmodule')] + recorder(ports) + 'endmodule\n'
