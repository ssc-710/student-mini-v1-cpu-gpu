// SPDX-License-Identifier: Apache-2.0
// Stable SRAM seam.  Default uses the behavioral model; defining
// COURSE_USE_OPENRAM binds the generated 128x256 one-port macro.  The
// rtl-small physical profile may define COURSE_USE_OPENRAM_SMALL instead and
// bind the profile-sized 128x16 macro; both retain the identical seam.
module sram_1rw_seam #(
  parameter int WIDTH = 128,
  parameter int DEPTH = 256,
  parameter int ADDR_WIDTH = $clog2(DEPTH),
  // Keep this parameter untyped for the pinned Yosys frontend used by ORFS;
  // its SystemVerilog parser rejects `parameter string` even though the
  // simulation toolchain accepts it.
  parameter INIT_FILE = ""
) (
  input logic clk_i, input logic enable_i, input logic write_i,
  input logic [ADDR_WIDTH-1:0] addr_i,
  input logic [WIDTH-1:0] wdata_i, input logic [WIDTH/8-1:0] wstrb_i,
  output logic [WIDTH-1:0] rdata_o
);
`ifdef COURSE_USE_OPENRAM_COMPACT
  logic [40:0] macro_dout;
  initial begin
    if (WIDTH != 40 || DEPTH != 16)
      $fatal(1, "compact OpenRAM backend is frozen at 40x16");
    if (INIT_FILE != "")
      $display("OpenRAM INIT_FILE is supplied by the simulation macro/image loader: %s", INIT_FILE);
  end
  openram_40x16 u_macro (
    .clk0(clk_i), .csb0(~enable_i), .web0(~write_i),
    .wmask0(wstrb_i), .spare_wen0(1'b0),
    .addr0({1'b0, addr_i}), .din0({1'b0, wdata_i}), .dout0(macro_dout)
  );
  assign rdata_o = macro_dout[39:0];
`elsif COURSE_USE_OPENRAM_SMALL
  logic [128:0] macro_dout;
  initial begin
    if (WIDTH != 128 || DEPTH != 16)
      $fatal(1, "small OpenRAM backend is frozen at 128x16");
    if (INIT_FILE != "")
      $display("OpenRAM INIT_FILE is supplied by the simulation macro/image loader: %s", INIT_FILE);
  end
  openram_128x16 u_macro (
    .clk0(clk_i), .csb0(~enable_i), .web0(~write_i),
    .wmask0(wstrb_i), .spare_wen0(1'b0),
    .addr0({1'b0, addr_i}), .din0({1'b0, wdata_i}), .dout0(macro_dout)
  );
  assign rdata_o = macro_dout[127:0];
`elsif COURSE_USE_OPENRAM
  logic [128:0] macro_dout;
  initial begin
    if (WIDTH != 128 || DEPTH != 256)
      $fatal(1, "OpenRAM backend is frozen at 128x256");
    if (INIT_FILE != "")
      $display("OpenRAM INIT_FILE is supplied by the simulation macro/image loader: %s", INIT_FILE);
  end
  openram_128x256 u_macro (
    .clk0(clk_i), .csb0(~enable_i), .web0(~write_i),
    .wmask0(wstrb_i), .spare_wen0(1'b0),
    .addr0({1'b0, addr_i}), .din0({1'b0, wdata_i}), .dout0(macro_dout)
  );
  assign rdata_o = macro_dout[127:0];
`else
  sram_1rw #(.WIDTH(WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH), .INIT_FILE(INIT_FILE))
    u_behavioral (.*);
`endif
endmodule
