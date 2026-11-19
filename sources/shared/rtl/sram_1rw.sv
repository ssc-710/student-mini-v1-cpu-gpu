// SPDX-License-Identifier: Apache-2.0
// Simulation model. PPA flow may replace this module with an OpenRAM macro.
module sram_1rw #(
  parameter int WIDTH = 128,
  parameter int DEPTH = 256,
  parameter int ADDR_WIDTH = $clog2(DEPTH),
  parameter string INIT_FILE = ""
) (
  input  logic                  clk_i,
  input  logic                  enable_i,
  input  logic                  write_i,
  input  logic [ADDR_WIDTH-1:0] addr_i,
  input  logic [WIDTH-1:0]      wdata_i,
  input  logic [WIDTH/8-1:0]    wstrb_i,
  output logic [WIDTH-1:0]      rdata_o
);
  logic [WIDTH-1:0] memory [0:DEPTH-1];
  integer byte_index;
  initial begin
    if (INIT_FILE != "") $readmemh(INIT_FILE, memory);
  end
  always_ff @(posedge clk_i) begin
    if (enable_i) begin
      if (write_i) begin
        for (byte_index = 0; byte_index < WIDTH/8; byte_index = byte_index + 1)
          if (wstrb_i[byte_index]) memory[addr_i][byte_index*8 +: 8] <= wdata_i[byte_index*8 +: 8];
      end else begin
        rdata_o <= memory[addr_i];
      end
    end
  end
endmodule
