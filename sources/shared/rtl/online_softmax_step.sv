// SPDX-License-Identifier: Apache-2.0
// One scalar-value Online Softmax update using the frozen Q5.11/Q1.15 rules.
module online_softmax_step (
  input  logic                    state_valid_i,
  input  logic signed [15:0]      maximum_q11_i,
  input  logic        [47:0]      denominator_q15_i,
  input  logic signed [63:0]      weighted_q15_i,
  input  logic signed [15:0]      score_q11_i,
  input  logic signed [7:0]       value_i,
  output logic                    state_valid_o,
  output logic signed [15:0]      maximum_q11_o,
  output logic        [47:0]      denominator_q15_o,
  output logic signed [63:0]      weighted_q15_o
);
  logic signed [15:0] new_maximum;
  logic signed [15:0] old_delta, new_delta;
  logic signed [16:0] old_delta_wide, new_delta_wide;
  logic [15:0] old_scale, new_scale;
  logic [63:0] denominator_product;
  logic signed [80:0] weighted_product;
  logic signed [23:0] new_weighted;
  logic [63:0] denominator_rescaled;
  logic signed [63:0] weighted_rescaled;

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
    logic [80:0] magnitude;
    logic [80:0] quotient;
    logic [14:0] remainder;
    logic [80:0] rounded;
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

  assign new_maximum = maximum_q11_i > score_q11_i ? maximum_q11_i : score_q11_i;
  assign old_delta_wide = {maximum_q11_i[15], maximum_q11_i} -
                          {new_maximum[15], new_maximum};
  assign new_delta_wide = {score_q11_i[15], score_q11_i} -
                          {new_maximum[15], new_maximum};
  assign old_delta = (old_delta_wide < -17'sd32768) ? -16'sd32768 : old_delta_wide[15:0];
  assign new_delta = (new_delta_wide < -17'sd32768) ? -16'sd32768 : new_delta_wide[15:0];
  exp_neg_q15 u_old_exp (.x_q11_i(old_delta), .exp_q15_o(old_scale));
  exp_neg_q15 u_new_exp (.x_q11_i(new_delta), .exp_q15_o(new_scale));
  assign denominator_product = denominator_q15_i * old_scale;
  assign weighted_product = weighted_q15_i * $signed({1'b0, old_scale});
  assign new_weighted = value_i * $signed({1'b0, new_scale});
  assign denominator_rescaled = rne_shift15_unsigned(denominator_product);
  assign weighted_rescaled = rne_shift15_signed(weighted_product);

  always_comb begin
    state_valid_o = 1'b1;
    if (!state_valid_i) begin
      maximum_q11_o = score_q11_i;
      denominator_q15_o = 48'd32768;
      weighted_q15_o = value_i * 17'sd32768;
    end else begin
      maximum_q11_o = new_maximum;
      denominator_q15_o = denominator_rescaled[47:0] +
                          {{32{1'b0}}, new_scale};
      weighted_q15_o = weighted_rescaled +
                       {{40{new_weighted[23]}}, new_weighted};
    end
  end
endmodule
