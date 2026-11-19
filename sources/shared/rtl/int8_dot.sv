// SPDX-License-Identifier: Apache-2.0
module int8_dot #(
  parameter int LANES = 8,
  parameter int ACC_WIDTH = 32
) (
  input  logic signed [LANES*8-1:0] a_i,
  input  logic signed [LANES*8-1:0] b_i,
  output logic signed [ACC_WIDTH-1:0] sum_o
);
  integer lane;
  logic signed [7:0] a_lane;
  logic signed [7:0] b_lane;
  always_comb begin
    sum_o = '0;
    for (lane = 0; lane < LANES; lane = lane + 1) begin
      a_lane = a_i[lane*8 +: 8];
      b_lane = b_i[lane*8 +: 8];
      sum_o = sum_o + a_lane * b_lane;
    end
  end
endmodule
