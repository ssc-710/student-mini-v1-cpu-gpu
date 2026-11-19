// SPDX-License-Identifier: Apache-2.0
// Physical-only bank decomposition for Vortex SRAM shapes that make a
// monolithic OpenRAM compiler explode.  The logical ports, byte write masks,
// synchronous 1W/1R behavior and address order are preserved exactly.

module vortex_dp_256x64_w32 (
`ifdef USE_POWER_PINS
  inout vccd1, inout vssd1,
`endif
  input logic clk0, input logic csb0, input logic [31:0] wmask0,
  input logic [5:0] addr0, input logic [255:0] din0,
  input logic clk1, input logic csb1, input logic [5:0] addr1,
  output logic [255:0] dout1
);
  genvar bank;
  generate for (bank = 0; bank < 4; bank++) begin : g_bank
    vortex_sp_64x128_w8 u_sram (
`ifdef USE_POWER_PINS
      .vccd1, .vssd1,
`endif
      .clk0, .csb0, .wmask0(wmask0[bank*8 +: 8]),
      .addr0({1'b0, addr0}), .din0(din0[bank*64 +: 64]),
      .clk1, .csb1, .addr1({1'b0, addr1}),
      .dout1(dout1[bank*64 +: 64])
    );
  end endgenerate
endmodule

module vortex_sp_512x64_w64 (
`ifdef USE_POWER_PINS
  inout vccd1, inout vssd1,
`endif
  input logic clk0, input logic csb0, input logic [63:0] wmask0,
  input logic [5:0] addr0, input logic [511:0] din0,
  input logic clk1, input logic csb1, input logic [5:0] addr1,
  output logic [511:0] dout1
);
  genvar bank;
  generate for (bank = 0; bank < 4; bank++) begin : g_bank
    vortex_sp_128x128_w16 u_sram (
`ifdef USE_POWER_PINS
      .vccd1, .vssd1,
`endif
      .clk0, .csb0, .wmask0(wmask0[bank*16 +: 16]),
      .addr0({1'b0, addr0}), .din0(din0[bank*128 +: 128]),
      .clk1, .csb1, .addr1({1'b0, addr1}),
      .dout1(dout1[bank*128 +: 128])
    );
  end endgenerate
endmodule

module vortex_sp_512x128_w64 (
`ifdef USE_POWER_PINS
  inout vccd1, inout vssd1,
`endif
  input logic clk0, input logic csb0, input logic [63:0] wmask0,
  input logic [6:0] addr0, input logic [511:0] din0,
  input logic clk1, input logic csb1, input logic [6:0] addr1,
  output logic [511:0] dout1
);
  genvar bank;
  generate for (bank = 0; bank < 4; bank++) begin : g_bank
    vortex_sp_128x128_w16 u_sram (
`ifdef USE_POWER_PINS
      .vccd1, .vssd1,
`endif
      .clk0, .csb0, .wmask0(wmask0[bank*16 +: 16]),
      .addr0, .din0(din0[bank*128 +: 128]),
      .clk1, .csb1, .addr1, .dout1(dout1[bank*128 +: 128])
    );
  end endgenerate
endmodule
