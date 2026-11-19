// SPDX-License-Identifier: Apache-2.0
// Signed Q5.11 -> RNE Q5.6 -> 2049-entry signed Q5.11 SiLU ROM.
module silu_q11 (
  input  logic signed [15:0] x_q11_i,
  output logic signed [15:0] silu_q11_o
);
`ifndef SILU_Q11_MEM_FILE
`define SILU_Q11_MEM_FILE "shared/rtl/silu_q11_q6.mem"
`endif
  logic signed [15:0] rom [0:2048];
  logic negative;
  logic [15:0] magnitude;
  logic [10:0] quotient;
  logic [4:0] remainder;
  logic [10:0] rounded_magnitude;
  logic signed [11:0] index_q6;
  logic [11:0] address;

  initial $readmemh(`SILU_Q11_MEM_FILE, rom);
  always_comb begin
    negative = x_q11_i[15];
    magnitude = negative ? (~x_q11_i + 1'b1) : x_q11_i;
    quotient = magnitude[15:5];
    remainder = magnitude[4:0];
    rounded_magnitude = quotient +
      ((remainder > 5'd16) || ((remainder == 5'd16) && quotient[0]));
    index_q6 = negative ? -$signed({1'b0, rounded_magnitude}) :
                          $signed({1'b0, rounded_magnitude});
    if (index_q6 < -12'sd1024) address = 12'd0;
    else if (index_q6 > 12'sd1024) address = 12'd2048;
    else address = index_q6 + 12'sd1024;
    silu_q11_o = rom[address];
  end
endmodule
