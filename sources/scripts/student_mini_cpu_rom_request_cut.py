"""Project only the ROM address and matching classic-bus response boundary."""
from scripts.student_mini_cpu_rom_cut import ADDRESS

ACK = 'build_soc_coursesimsoc_coursesimsoc_ram_bus_ack'
BASE = 'build_soc_coursesimsoc_coursesimsoc_ram_bus_'


def project(source, module):
    changes = {
        f"  reg {ACK} = 1'h0;": f'  wire {ACK};',
        f"  always @(posedge sys_clk)\n    if (asic_reset_i) {ACK} <= 1'h0;\n    else {ACK} <= _0818_;":
        f'''  wire [14:0] mini_rom_request_address;
  student_mini_cpu_rom_request_cut rom_request_boundary (
    .clk(sys_clk), .reset(asic_reset_i), .cyc({BASE}cyc), .stb({BASE}stb),
    .address({ADDRESS}[14:0]), .rom_address(mini_rom_request_address), .ack({ACK})
  );''',
        f'rom[mini_rom_bank*512 + {ADDRESS}[8:0]]':
        'rom[mini_rom_bank*512 + mini_rom_request_address[8:0]]',
        f'always @(posedge sys_clk) mini_rom_bank_q <= {ADDRESS}[14:9];':
        'always @(posedge sys_clk) mini_rom_bank_q <= mini_rom_request_address[14:9];',
    }
    for old, new in changes.items():
        if source.count(old) != 1: raise ValueError('exact ROM request seam changed: '+old)
        source = source.replace(old, new)
    if module.count('module student_mini_cpu_rom_request_cut (') != 1:
        raise ValueError('unique request boundary module required')
    return source+'\n'+module
