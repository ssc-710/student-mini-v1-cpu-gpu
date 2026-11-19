"""Distribute synchronous ROM output registers without changing bus latency."""
import re

ADDRESS='build_soc_coursesimsoc_coursesimsoc_ram_bus_adr'
DATA='build_soc_coursesimsoc_coursesimsoc_dat_r'


def rom_parts(source):
    pattern=r'  reg \[31:0\] rom \[(\d+):0\];\n  initial begin\n((?:    rom\[\d+\] = 32\'d\d+;\n)+)  end\n'
    matches=list(re.finditer(pattern,source))
    if len(matches)!=1:raise ValueError('one fully initialized frozen ROM required')
    match=matches[0];depth=int(match[1])+1
    words=re.findall(r"rom\[(\d+)\] = 32'd(\d+);",match[2])
    if [int(a) for a,_ in words]!=list(range(depth)) or any(not 0<=int(v)<2**32 for _,v in words):raise ValueError('ROM initialization differs')
    stage=f'''  reg [31:0] _5442_;
  always @(posedge sys_clk) begin
    _5442_ <= rom[{ADDRESS}[14:0]];
  end
  assign {DATA} = _5442_;
'''
    if source.count(stage)!=1:raise ValueError('frozen synchronous ROM read stage changed')
    return match.group(),stage,[int(v) for _,v in words]


def retime_rom(source):
    _,stage,words=rom_parts(source)
    if len(words)!=12558:raise ValueError('only the measured 12558-word program ROM is qualified')
    banks=(len(words)+511)//512
    replacement=f'''  // Timing foundation: one-cycle read, exact original ROM contents.
  // Capture each 512-word bank and its selector at the same clock edge.
  reg [31:0] mini_rom_bank_data [0:{banks-1}];
  reg [5:0] mini_rom_bank_q;
  genvar mini_rom_bank;
  generate for (mini_rom_bank=0; mini_rom_bank<{banks}; mini_rom_bank=mini_rom_bank+1) begin : g_mini_rom_cut
    always @(posedge sys_clk)
      mini_rom_bank_data[mini_rom_bank] <= rom[mini_rom_bank*512 + {ADDRESS}[8:0]];
  end endgenerate
  always @(posedge sys_clk) mini_rom_bank_q <= {ADDRESS}[14:9];
  assign {DATA} = mini_rom_bank_data[mini_rom_bank_q];
'''
    return source.replace(stage,replacement)


def isolated_rom(source,name):
    block,stage,_=rom_parts(source)
    return f'module {name}(input sys_clk,input [29:0] {ADDRESS},output [31:0] {DATA});\n'+block+stage+'endmodule\n'


def check_rom_transcript(text):
    marker='CPU_ROM_CUT_PASS addresses=32768 random_seeds=10 random_rows=5120 latency=1'
    if text.splitlines().count(marker)!=1:raise ValueError('one exact ROM completion required')
    rows=[line for line in text.splitlines() if line.startswith('ROM_ROW ')]
    if len(rows)!=37888:raise ValueError('ROM address coverage incomplete')
    for index,line in enumerate(rows):
        match=re.fullmatch(r'ROM_ROW address=(\d+) golden=([0-9a-fx]{8}) actual=([0-9a-fx]{8})',line)
        if not match or match[2]!=match[3] or not 0<=int(match[1])<32768:
            raise ValueError('ROM full word differs')
        if index<32768 and int(match[1])!=index:raise ValueError('ROM exhaustive addresses reordered/duplicated')
    return dict(exhaustive_addresses=32768,random_rows=5120,records=len(rows),read_latency_cycles=1)
