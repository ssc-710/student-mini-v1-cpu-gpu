// SPDX-License-Identifier: Apache-2.0
// IEEE-754 binary32 to bfloat16, round-to-nearest-even.
module bf16_rne (
  input  logic [31:0] fp32_i,
  output logic [15:0] bf16_o
);
  logic round_up;
  logic [16:0] rounded;

  always_comb begin
    round_up = fp32_i[15] && (|fp32_i[14:0] || fp32_i[16]);
    rounded = {1'b0, fp32_i[31:16]} + round_up;
    bf16_o = rounded[15:0];
  end
endmodule
