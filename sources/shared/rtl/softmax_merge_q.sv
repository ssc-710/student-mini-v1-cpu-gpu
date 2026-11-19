// SPDX-License-Identifier: Apache-2.0
// Stable Split-KV merge for scalar values. States use Q5.11 maxima,
// 48-bit Q1.15 denominators and signed 64-bit weighted accumulators.
module softmax_merge_q (
  input  logic signed [15:0] left_max_i,
  input  logic        [47:0] left_sum_i,
  input  logic signed [63:0] left_weighted_i,
  input  logic signed [15:0] right_max_i,
  input  logic        [47:0] right_sum_i,
  input  logic signed [63:0] right_weighted_i,
  output logic signed [15:0] merged_max_o,
  output logic        [47:0] merged_sum_o,
  output logic signed [63:0] merged_weighted_o
);
  logic signed [16:0] left_delta_wide, right_delta_wide;
  logic signed [15:0] left_delta, right_delta;
  logic [15:0] left_scale, right_scale;
  logic [63:0] left_sum_product, right_sum_product;
  logic [63:0] left_sum_rescaled, right_sum_rescaled;
  logic signed [80:0] left_weighted_product, right_weighted_product;

  function automatic [63:0] rne_shift15_unsigned(input logic [63:0] value);
    logic [63:0] quotient;
    logic [14:0] remainder;
    begin
      quotient = value >> 15;
      remainder = value[14:0];
      rne_shift15_unsigned = quotient +
        ((remainder > 15'd16384) || ((remainder == 15'd16384) && quotient[0]));
    end
  endfunction

  function automatic signed [63:0] rne_shift15_signed(input logic signed [80:0] value);
    logic negative;
    logic [80:0] magnitude, quotient, rounded;
    logic [14:0] remainder;
    begin
      negative = value[80];
      magnitude = negative ? (~value + 1'b1) : value;
      quotient = magnitude >> 15;
      remainder = magnitude[14:0];
      rounded = quotient +
        ((remainder > 15'd16384) || ((remainder == 15'd16384) && quotient[0]));
      rne_shift15_signed = negative ? -$signed(rounded[63:0]) : $signed(rounded[63:0]);
    end
  endfunction

  assign merged_max_o = left_max_i > right_max_i ? left_max_i : right_max_i;
  assign left_delta_wide = {left_max_i[15], left_max_i} - {merged_max_o[15], merged_max_o};
  assign right_delta_wide = {right_max_i[15], right_max_i} - {merged_max_o[15], merged_max_o};
  assign left_delta = (left_delta_wide < -17'sd32768) ? -16'sd32768 : left_delta_wide[15:0];
  assign right_delta = (right_delta_wide < -17'sd32768) ? -16'sd32768 : right_delta_wide[15:0];
  exp_neg_q15 u_exp_left (.x_q11_i(left_delta), .exp_q15_o(left_scale));
  exp_neg_q15 u_exp_right (.x_q11_i(right_delta), .exp_q15_o(right_scale));
  assign left_sum_product = left_sum_i * left_scale;
  assign right_sum_product = right_sum_i * right_scale;
  assign left_sum_rescaled = rne_shift15_unsigned(left_sum_product);
  assign right_sum_rescaled = rne_shift15_unsigned(right_sum_product);
  assign left_weighted_product = left_weighted_i * $signed({1'b0, left_scale});
  assign right_weighted_product = right_weighted_i * $signed({1'b0, right_scale});

  always_comb begin
    merged_sum_o = left_sum_rescaled[47:0] + right_sum_rescaled[47:0];
    merged_weighted_o = rne_shift15_signed(left_weighted_product) +
                        rne_shift15_signed(right_weighted_product);
  end
endmodule
