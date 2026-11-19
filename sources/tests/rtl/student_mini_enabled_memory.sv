// Minimal copy of the enabled synchronous read/write pattern in VexRiscv.
// Separate addresses and enables; storage geometry is reduced only for this
// synthesis-front-end regression, not for the platform hardware specification.
module enabled_memory (
    input wire clk, read_enable, write_enable,
    input wire [3:0] read_address, write_address,
    input wire [7:0] write_data,
    output reg [7:0] read_data
);
  (* no_rw_check, ram_style = "block" *) reg [7:0] words [0:15];
  always @(posedge clk)
    if (write_enable) words[write_address] <= write_data;
  always @(posedge clk)
    if (read_enable) read_data <= words[read_address];
endmodule
