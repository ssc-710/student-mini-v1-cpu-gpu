"""Actual independent-memory CPU execution with latency-aware output comparison.

This is cold-start functional replay, not cycle/DFI equivalence. Raw hardware
counters are retained separately and must be rebound to the new hardware.
"""
import re
from scripts.student_mini_cpu_replay_sources import TOP, wrapper as checked_wrapper
from scripts.student_mini_cpu_replay_sources import compare_transcripts as strict_compare
from scripts.student_mini_cpu_independent_memory import memory_source
from scripts.export_student_mini_cpu_boundary import PREFIX, DFI_INPUTS, DFI_OUTPUTS
from scripts.assemble_student_mini_cpu_results import parse


def wrapper(ports):
    checked_wrapper(ports)  # Keep the exact frozen interface/width validation.
    wires=[];connections=[];memory=[]
    fixed={'sys_clk':'sys_clk','serial_sink_data':"8'h00",'serial_sink_valid':"1'b0",
           'serial_source_ready':"1'b1",'asic_reset_i':'independent_memory.build_soc_coursesimsoc_int_rst'}
    for name,row in ports.items():
        width=len(row['bits'])
        if name in fixed:value=fixed[name]
        else:
            value='actual_'+name
            wires.append(f'wire [{width-1}:0] {value};')
        connections.append(f'.{name}({value})')
    for suffix in (*DFI_OUTPUTS,*DFI_INPUTS):
        name=PREFIX+suffix;memory.append(f'.{name}(actual_{name})')
    return f'''`timescale 1ns/1ps
module cpu_boundary_replay(input wire sys_clk,output wire [7:0] uart_data,output wire uart_valid);
  {' '.join(wires)}
  cpu_memory_environment independent_memory(.sys_clk(sys_clk),
    .serial_sink_data(8'h00),.serial_sink_valid(1'b0),.serial_source_ready(1'b1),
    {','.join(memory)});
  {TOP} actual({','.join(connections)});
  assign uart_data=actual_serial_source_data;
  assign uart_valid=actual_serial_source_valid;
endmodule
'''


def compare_transcripts(reference,actual):
    # Existing structural checks require every complete output and native state.
    # Comparing each stream to itself validates it without requiring equal time.
    strict_compare(reference,reference);strict_compare(actual,actual)
    before=parse(reference,1000);after=parse(actual,1000)
    fields=('cycles','instructions','ibus_bytes','dbus_bytes','dma_bytes')
    measurements=[]
    for old,new in zip(before,after,strict=True):
        if {k:v for k,v in old.items() if k not in fields}!={k:v for k,v in new.items() if k not in fields}:
            raise ValueError('new-latency CPU full output/status/selection/primitive differs')
        measurements.append(dict(ordinal=new['ordinal'],
            reference={k:old[k] for k in fields},actual={k:new[k] for k in fields},
            delta={k:new[k]-old[k] for k in fields}))
    def invariant_lines(text):
        lines=[]
        for line in text.splitlines():
            if line.startswith('STUDENT_CPU '):
                # Retain sequence, independently of parse()'s keyed join.
                lines.append('CPU_ORDINAL '+str(re.search(r'ordinal=(\d+)',line)[1]))
            elif line.startswith(('STUDENT_CPU_','STUDENT_NATIVE_')):
                lines.append(re.sub(r'elapsed_cycles=\d+:\d+', 'elapsed_cycles=<measured-separately>',line))
        return lines
    if invariant_lines(reference)!=invariant_lines(actual):
        raise ValueError('new-latency CPU sequence, metadata or complete native state differs')
    return dict(baseline_records=1000,native_completion=True,cycle_equivalence=False,
                independent_external_memory=True,raw_counter_comparisons=measurements,
                performance_eligible=False)
