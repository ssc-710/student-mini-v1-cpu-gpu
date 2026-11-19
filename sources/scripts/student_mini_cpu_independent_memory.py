"""Give the mapped CPU its own original SDRAM model, retaining lockstep checks.

This first harness qualification changes no CPU RTL or timing. Model reads are
driven by the actual CPU's DFI requests, never by the reference CPU's responses.
"""
import re
from scripts.export_student_mini_cpu_boundary import DFI_INPUTS, DFI_OUTPUTS, PREFIX
from scripts.student_mini_cpu_replay_sources import wrapper as locked_wrapper


def memory_source(source):
    ports = []
    for suffix, width in {**DFI_OUTPUTS, **DFI_INPUTS}.items():
        name = PREFIX+suffix
        direction = 'input' if suffix in DFI_OUTPUTS else 'output'
        declaration = rf'^wire\s*(?:\[{width-1}:0\]\s*)?{name};\s*$'
        source, count = re.subn(declaration, '', source, flags=re.M)
        if count != 1: raise ValueError('unique actual DFI declaration required: '+name)
        if direction == 'input':
            driver = rf'^assign {name} = build_soc_coursesimsoc_sdram_master_p0_{suffix};\s*$'
            source, count = re.subn(driver, '', source, flags=re.M)
            if count != 1: raise ValueError('unique original controller driver required: '+name)
        span = f'[{width-1}:0] ' if width > 1 else ''
        ports.append(f'    {direction} wire {span}{name},')
    source, count = re.subn(r'^module sim \(\s*$', 'module cpu_memory_environment (\n'+'\n'.join(ports), source, flags=re.M)
    if count != 1: raise ValueError('unique generated top required')
    return source


def wrapper(ports):
    text = locked_wrapper(ports)
    connections = [f'.{PREFIX+suffix}(actual_{PREFIX+suffix})' for suffix in DFI_OUTPUTS]
    for suffix, width in DFI_INPUTS.items():
        name = PREFIX+suffix; signal = 'memory_'+suffix
        old = f'.{name}(reference.{name})'
        if text.count(old) != 1: raise ValueError('mapped return-input seam changed')
        text = text.replace(old, f'.{name}({signal})')
        connections.append(f'.{name}({signal})')
    extra = '''  wire [127:0] memory_rddata;
  wire memory_rddata_valid;
  cpu_memory_environment independent_memory(.sys_clk(sys_clk),
    .serial_sink_data(8'h00), .serial_sink_valid(1'b0), .serial_source_ready(1'b1),
    CONNECTIONS);
'''.replace('CONNECTIONS', ','.join(connections))
    marker = '  cpu_reference_sim reference('
    if text.count(marker) != 1: raise ValueError('reference scope seam changed')
    text = text.replace(marker, extra+marker)
    marker = "    if(cycles>2) begin "
    if text.count(marker) != 1: raise ValueError('existing all-DFI comparison seam changed')
    checks = f'''
      if (memory_rddata_valid !== reference.{PREFIX}rddata_valid)
        $fatal(1,"CPU_INDEPENDENT_MEMORY_VALID cycle=%0d",cycles);
      if (memory_rddata_valid && memory_rddata !== reference.{PREFIX}rddata)
        $fatal(1,"CPU_INDEPENDENT_MEMORY_DATA cycle=%0d",cycles);
'''
    return text.replace(marker, marker+checks)
