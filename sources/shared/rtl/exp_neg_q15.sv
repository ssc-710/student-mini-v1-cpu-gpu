// SPDX-License-Identifier: Apache-2.0
// Bit-exact exp(x) contract: signed Q5.11 input is RNE-reduced to Q5.6,
// then used to address the checked-in 1025-entry unsigned Q1.15 ROM.
module exp_neg_q15 (
  input  logic signed [15:0] x_q11_i,
  output logic [15:0] exp_q15_o
);
`ifndef EXP_Q15_MEM_FILE
`define EXP_Q15_MEM_FILE "shared/rtl/exp_q15_q6.mem"
`endif
  logic [15:0] rom [0:1024];
  logic [15:0] magnitude;
  logic [10:0] quotient;
  logic [4:0] remainder;
  logic [10:0] rounded;
  logic [10:0] address;

  initial $readmemh(`EXP_Q15_MEM_FILE, rom);

  always_comb begin
    magnitude = '0;
    quotient = '0;
    remainder = '0;
    rounded = '0;
    address = 11'd1024;
    if (!x_q11_i[15]) begin
      address = 11'd1024;
    end else begin
      magnitude = (~x_q11_i) + 1'b1;
      quotient = magnitude[15:5];
      remainder = magnitude[4:0];
      rounded = quotient + ((remainder > 5'd16) || ((remainder == 5'd16) && quotient[0]));
      address = rounded >= 11'd1024 ? 11'd0 : 11'd1024 - rounded;
    end
    exp_q15_o = rom[address];
  end
endmodule
