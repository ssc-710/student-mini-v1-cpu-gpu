"""Strict source projection for a cold-start CPU/DFI differential replay.

The executed original SoC supplies the external SDRAM model. Every meaningful
DFI request and UART handshake is compared before the next active clock edge.
This does not prove arbitrary inputs, warm reset, or physical timing closure.
"""
import re

PREFIX = 'build_soc_coursesimsoc_dfi_p0_'
TOP = 'cpu_student_mini_physical_top_asic'


def reference_source(source):
    result,count=re.subn(r'(?m)^module sim \(', 'module cpu_reference_sim (', source)
    if count!=1: raise ValueError('ambiguous executed CPU top')
    for name in ('rddata','rddata_valid','address','wrdata'):
        if PREFIX+name not in source: raise ValueError('missing original DFI signal')
    if 'build_soc_coursesimsoc_int_rst' not in source: raise ValueError('missing original reset')
    return result


def quiet_macro(source):
    result,count=re.subn(r'parameter VERBOSE\s*=\s*1\s*;', 'parameter VERBOSE = 0 ;', source)
    if count!=1: raise ValueError('unexpected actual macro verbosity definition')
    return result


def wrapper(ports):
    external={'sys_clk':('input',1),'serial_sink_data':('input',8),
        'serial_sink_valid':('input',1),'serial_source_ready':('input',1),
        'serial_sink_ready':('output',1),'serial_source_data':('output',8),
        'serial_source_valid':('output',1),'sim_trace':('output',1),'asic_reset_i':('input',1)}
    dfi={'rddata':('input',128),'rddata_valid':('input',1),
        'address':('output',13),'bank':('output',2),'cas_n':('output',1),
        'cke':('output',1),'cs_n':('output',1),'ras_n':('output',1),'we_n':('output',1),
        'wrdata':('output',128),'wrdata_mask':('output',16),'wrdata_en':('output',1),
        'rddata_en':('output',1),'reset_n':('output',1),'odt':('output',1),'act_n':('output',1)}
    expected={**external,**{PREFIX+k:v for k,v in dfi.items()}}
    if set(ports)!=set(expected): raise ValueError('CPU physical interface changed')
    for name,(direction,width) in expected.items():
        if ports[name]['direction']!=direction or len(ports[name]['bits'])!=width:
            raise ValueError('CPU port geometry differs: '+name)
    declarations=[];connections=[];checks=[]
    inputs={'sys_clk':'sys_clk','serial_sink_data':"8'h00",'serial_sink_valid':"1'b0",
        'serial_source_ready':"1'b1",'asic_reset_i':'reference.build_soc_coursesimsoc_int_rst'}
    for name,(direction,width) in expected.items():
        if direction=='input': value=inputs[name] if name in inputs else 'reference.'+name
        else:
            value='actual_'+name
            declarations.append(f'wire [{width-1}:0] {value};')
        connections.append(f'.{name}({value})')
    def compare(name,guard="1'b1"):
        checks.append(f'if ({guard}) if (actual_{name} !== reference.{name}) $fatal(1,"CPU_BOUNDARY_MISMATCH {name} cycle=%0d",cycles);')
    for name in ('serial_sink_ready','serial_source_valid','sim_trace'): compare(name)
    compare('serial_source_data','reference.serial_source_valid')
    for name in ('cke','cs_n','ras_n','cas_n','we_n','reset_n','odt','act_n','wrdata_en','rddata_en'):
        compare(PREFIX+name)
    active=f'!reference.{PREFIX}cs_n && !(reference.{PREFIX}ras_n && reference.{PREFIX}cas_n && reference.{PREFIX}we_n)'
    for name in ('address','bank'): compare(PREFIX+name,active)
    compare(PREFIX+'wrdata_mask','reference.'+PREFIX+'wrdata_en')
    # Only bytes actually written are semantically constrained.
    for lane in range(16):
        lo=lane*8;hi=lo+7
        checks.append(f'if(reference.{PREFIX}wrdata_en && !reference.{PREFIX}wrdata_mask[{lane}]) '
            f'if(actual_{PREFIX}wrdata[{hi}:{lo}] !== reference.{PREFIX}wrdata[{hi}:{lo}]) '
            f'$fatal(1,"CPU_BOUNDARY_MISMATCH wrdata byte {lane} cycle=%0d",cycles);')
    return f'''`timescale 1ns/1ps
module cpu_boundary_replay(input wire sys_clk,
    output wire [7:0] uart_data, output wire uart_valid);
  {' '.join(declarations)}
  cpu_reference_sim reference(.sys_clk(sys_clk),.serial_sink_data(8'h00),
    .serial_sink_valid(1'b0),.serial_source_ready(1'b1));
  {TOP} actual({','.join(connections)});
  assign uart_data=actual_serial_source_data;
  assign uart_valid=actual_serial_source_valid;
  reg [63:0] cycles=0;
  always @(posedge sys_clk) begin
    cycles <= cycles+1;
    if(cycles>2) begin {' '.join(checks)} end
  end
endmodule
'''


def compare_transcripts(reference,actual):
    from scripts.assemble_student_mini_cpu_results import parse
    # Real firmware records use a SPACE after CPU; metadata uses underscore.
    # Validate record ordinals, complete arrays and counters, not just markers.
    for text in (reference,actual): parse(text,1000)
    def rows(text): return [line for line in text.splitlines() if line.startswith(('STUDENT_CPU ','STUDENT_CPU_','STUDENT_NATIVE_'))]
    before,after=rows(reference),rows(actual)
    if before.count('STUDENT_CPU_COMPLETE count=1000')!=1:
        raise ValueError('reference lacks complete baseline')
    if sum(line.startswith('STUDENT_NATIVE_CPU_COMPLETE ') for line in before)!=1:
        raise ValueError('reference lacks complete Nano')
    terminal=next(line for line in before if line.startswith('STUDENT_NATIVE_CPU_COMPLETE '))
    match=re.fullmatch(r'STUDENT_NATIVE_CPU_COMPLETE count=(\d+) p1=(\d+) p2=(\d+) p3=(\d+)',terminal)
    if not match or not 1<=int(match[1])<=12:raise ValueError('invalid native completion')
    native=[line for line in before if line.startswith('STUDENT_NATIVE_TOKEN ')]
    if len(native)!=int(match[1]):raise ValueError('missing native token/state records')
    for step,line in enumerate(native):
        token=re.fullmatch(r'STUDENT_NATIVE_TOKEN step=(\d+) token=(\d+) elapsed_cycles=\d+:\d+ hidden=([0-9a-f,]+) logits=([0-9a-f,]+)',line)
        if not token or int(token[1])!=step or not 0<=int(token[2])<256 or len(token[3].split(','))!=16 or len(token[4].split(','))!=256:
            raise ValueError('incomplete or reordered native state')
    if before!=after: raise ValueError('mapped CPU result/counter transcript differs from executed ROM')
    return dict(matching_lines=len(before),baseline_records=1000,native_completion=True)
