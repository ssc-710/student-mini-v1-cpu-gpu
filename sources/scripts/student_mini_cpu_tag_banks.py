"""Split only the register tag read mux, preserving the one-cycle interface."""
from scripts.student_mini_cpu_tag_registers import MODULE as ORIGINAL, replace_tag as old_replace, original_wrapper

old = '''  always @(posedge clk)
    if (read_enable) read_data <= {10'bx, words[read_address]};'''
new = '''  reg [21:0] read_banks [0:15];
  reg [4:0] read_bank_q;
  genvar bank;
  generate for (bank=0; bank<16; bank=bank+1) begin : g_read_banks
    always @(posedge clk)
      if (read_enable) read_banks[bank] <= words[bank*32 + read_address[4:0]];
  end endgenerate
  always @(posedge clk)
    if (read_enable) read_bank_q <= read_address[9:5];
  assign read_data = {10'bx, read_banks[read_bank_q]};'''
if ORIGINAL.count(old) != 1 or ORIGINAL.count('output reg [31:0] read_data') != 1:
    raise ValueError('original tag register source seam changed')
MODULE = ORIGINAL.replace(old, new).replace('output reg [31:0] read_data', 'output wire [31:0] read_data')
REGISTER_BITS = 512*22 + 16*22 + 5


def replace_tag(source):
    mapped = old_replace(source)
    if mapped.count(ORIGINAL) != 1:
        raise ValueError('exact original tag module required')
    return mapped.replace(ORIGINAL, MODULE)
