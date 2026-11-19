// SPDX-License-Identifier: Apache-2.0
// Bit-exact Online Softmax step with registers on both sides of the wide
// products: exp ROM results are captured first, products on the next cycle,
// then RNE/accumulation.  Only one request may be in flight.
module online_softmax_step_sync_exp_output_pipeline #(
  parameter bit ACCUMULATE_CUT = 1'b0
) (
  input logic clk_i, input logic rst_ni,
  input logic req_valid_i, output logic req_ready_o,
  input logic state_valid_i,
  input logic signed [15:0] maximum_q11_i,
  input logic [47:0] denominator_q15_i,
  input logic signed [63:0] weighted_q15_i,
  input logic signed [15:0] score_q11_i,
  input logic signed [7:0] value_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic state_valid_o,
  output logic signed [15:0] maximum_q11_o,
  output logic [47:0] denominator_q15_o,
  output logic signed [63:0] weighted_q15_o
);
  logic exp_busy_q, scale_valid_q, product_valid_q, rescale_valid_q, state_valid_q;
  logic signed [15:0] new_maximum_w, new_maximum_q;
  logic signed [16:0] old_delta_wide, new_delta_wide;
  logic signed [15:0] old_delta_w, new_delta_w;
  logic [47:0] denominator_q;
  logic signed [63:0] weighted_q;
  logic signed [7:0] value_q;
  logic old_exp_valid, new_exp_valid;
  logic [15:0] old_scale, new_scale, old_scale_q, new_scale_q;
  logic [63:0] denominator_product_q;
  logic signed [80:0] weighted_product_q;
  logic signed [23:0] new_weighted_q;
  logic [63:0] denominator_rescaled_q;
  logic signed [63:0] weighted_rescaled_q;

  assign req_ready_o = !exp_busy_q && !scale_valid_q &&
                       !product_valid_q && !rescale_valid_q && !rsp_valid_o;
  assign new_maximum_w = maximum_q11_i > score_q11_i ?
                         maximum_q11_i : score_q11_i;
  assign old_delta_wide = {maximum_q11_i[15], maximum_q11_i} -
                          {new_maximum_w[15], new_maximum_w};
  assign new_delta_wide = {score_q11_i[15], score_q11_i} -
                          {new_maximum_w[15], new_maximum_w};
  assign old_delta_w = old_delta_wide < -17'sd32768 ?
                       -16'sd32768 : old_delta_wide[15:0];
  assign new_delta_w = new_delta_wide < -17'sd32768 ?
                       -16'sd32768 : new_delta_wide[15:0];

  exp_neg_q15_sync u_old_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(old_delta_w), .valid_o(old_exp_valid), .exp_q15_o(old_scale));
  exp_neg_q15_sync u_new_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(new_delta_w), .valid_o(new_exp_valid), .exp_q15_o(new_scale));

  function automatic [63:0] rne_shift15_unsigned(input logic [63:0] value);
    logic [63:0] quotient; logic [14:0] remainder;
    begin
      quotient = value >> 15; remainder = value[14:0];
      rne_shift15_unsigned = quotient +
        64'((remainder > 15'd16384) ||
            ((remainder == 15'd16384) && quotient[0]));
    end
  endfunction

  function automatic signed [63:0] rne_shift15_signed(
    input logic signed [80:0] value
  );
    logic negative; logic [80:0] magnitude, quotient, rounded;
    logic [14:0] remainder;
    begin
      negative = value[80];
      magnitude = negative ? (~value + 1'b1) : value;
      quotient = magnitude >> 15; remainder = magnitude[14:0];
      rounded = quotient +
        81'((remainder > 15'd16384) ||
            ((remainder == 15'd16384) && quotient[0]));
      rne_shift15_signed = negative ?
        -$signed(rounded[63:0]) : $signed(rounded[63:0]);
    end
  endfunction

  logic [63:0] denominator_rescaled_w;
  logic signed [63:0] weighted_rescaled_w;
  assign denominator_rescaled_w = rne_shift15_unsigned(denominator_product_q);
  assign weighted_rescaled_w = rne_shift15_signed(weighted_product_q);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      exp_busy_q <= '0; scale_valid_q <= '0; product_valid_q <= '0;
      rescale_valid_q <= '0;
      rsp_valid_o <= '0; state_valid_q <= '0; new_maximum_q <= '0;
      denominator_q <= '0; weighted_q <= '0; value_q <= '0;
      old_scale_q <= '0; new_scale_q <= '0;
      denominator_product_q <= '0; weighted_product_q <= '0;
      denominator_rescaled_q <= '0; weighted_rescaled_q <= '0;
      new_weighted_q <= '0; state_valid_o <= '0; maximum_q11_o <= '0;
      denominator_q15_o <= '0; weighted_q15_o <= '0;
    end else begin
      if (rsp_valid_o && rsp_ready_i) rsp_valid_o <= 1'b0;
      if (req_valid_i && req_ready_o) begin
        exp_busy_q <= 1'b1;
        state_valid_q <= state_valid_i;
        new_maximum_q <= state_valid_i ? new_maximum_w : score_q11_i;
        denominator_q <= denominator_q15_i;
        weighted_q <= weighted_q15_i;
        value_q <= value_i;
      end
      if (exp_busy_q && old_exp_valid && new_exp_valid) begin
        exp_busy_q <= 1'b0;
        scale_valid_q <= 1'b1;
        old_scale_q <= old_scale;
        new_scale_q <= new_scale;
      end
      if (scale_valid_q) begin
        scale_valid_q <= 1'b0;
        product_valid_q <= 1'b1;
        denominator_product_q <= denominator_q * old_scale_q;
        weighted_product_q <= weighted_q * $signed({1'b0, old_scale_q});
        new_weighted_q <= value_q * $signed({1'b0, new_scale_q});
      end
      if (product_valid_q) begin
        product_valid_q <= 1'b0;
        if (ACCUMULATE_CUT && state_valid_q) begin
          rescale_valid_q <= 1'b1;
          denominator_rescaled_q <= denominator_rescaled_w;
          weighted_rescaled_q <= weighted_rescaled_w;
        end else begin
          rsp_valid_o <= 1'b1;
          state_valid_o <= 1'b1;
          maximum_q11_o <= new_maximum_q;
          if (!state_valid_q) begin
            denominator_q15_o <= 48'd32768;
            weighted_q15_o <= value_q * 17'sd32768;
          end else begin
            denominator_q15_o <= denominator_rescaled_w[47:0] +
                                 {{32{1'b0}}, new_scale_q};
            weighted_q15_o <= weighted_rescaled_w +
                              {{40{new_weighted_q[23]}}, new_weighted_q};
          end
        end
      end
      if (rescale_valid_q) begin
        rescale_valid_q <= 1'b0;
        rsp_valid_o <= 1'b1;
        state_valid_o <= 1'b1;
        maximum_q11_o <= new_maximum_q;
        denominator_q15_o <= denominator_rescaled_q[47:0] +
                             {{32{1'b0}}, new_scale_q};
        weighted_q15_o <= weighted_rescaled_q +
                          {{40{new_weighted_q[23]}}, new_weighted_q};
      end
    end
  end
endmodule
