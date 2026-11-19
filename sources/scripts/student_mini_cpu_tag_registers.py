"""Replace only the measured 512x22 cache-tag macro by real standard-cell storage."""
import re

MODULE = '''module student_mini_cpu_cache_tag_registers(
  input clk, input [9:0] write_address, read_address,
  input [31:0] write_data, input [3:0] write_enable,
  input read_enable, output reg [31:0] read_data);
  wire [21:0] words [0:511];
  genvar row;
  generate for (row=0; row<512; row=row+1) begin : g_tag_words
    reg [21:0] stored;
    always @(posedge clk) begin
      if (write_address == row) begin
        if (write_enable[0]) stored[7:0] <= write_data[7:0];
        if (write_enable[1]) stored[15:8] <= write_data[15:8];
        if (write_enable[2]) stored[21:16] <= write_data[21:16];
      end
    end
    assign words[row] = stored;
  end endgenerate
  always @(posedge clk)
    if (read_enable) read_data <= {10'bx, words[read_address]};
endmodule
'''


def replace_tag(source):
    pattern = r'  student_mini_cpu_sram_32x1024 \\tag_mem\.0\.0  \(\n.*?\n  \);'
    found = list(re.finditer(pattern, source, re.S))
    if len(found) != 1:
        raise ValueError('exactly one measured cache-tag instance required')
    instance = found[0].group()
    required = [".read_address({ 1'h0, build_soc_coursesimsoc_coursesimsoc_ram_bus_adr[10:2] })",
                ".write_address({ 1'h0, build_soc_coursesimsoc_coursesimsoc_ram_bus_adr[10:2] })",
                ".read_data({ _1846_[31:22], _1756_ })", ".write_data({ 10'hxxx, _1694_ })",
                ".write_enable({ 1'h0, _1695_[0], _1695_[0], _1695_[0] })", ".read_enable(1'h1)"]
    if any(text not in instance for text in required):
        raise ValueError('cache-tag geometry or interface changed')
    if source.count('  student_mini_cpu_sram_32x1024 \\') != 30 or 'mini_rom_bank_data' not in source:
        raise ValueError('qualified 30-macro ROM-cut parent required')
    return source.replace(instance, instance.replace('student_mini_cpu_sram_32x1024', 'student_mini_cpu_cache_tag_registers', 1)) + '\n' + MODULE


def original_wrapper(source):
    matches = re.findall(r'(?ms)^module student_mini_cpu_sram_32x1024\(.*?^endmodule\n', source)
    if len(matches) != 1: raise ValueError('one real SRAM wrapper required')
    return matches[0]
