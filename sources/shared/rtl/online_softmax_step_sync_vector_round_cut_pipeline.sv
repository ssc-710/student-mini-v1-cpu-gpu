// SPDX-License-Identifier: Apache-2.0
// B22: B21's exact vector pipeline plus a register cut inside signed RNE.
// Product sign, shifted quotient and tie predicate are captured first; the
// following cycle performs the small increment/sign commit.
module online_softmax_step_sync_vector_serial_accum_pipeline #(
  parameter int VALUE_DIM = 8
) (
  input logic clk_i, input logic rst_ni,
  input logic req_valid_i, output logic req_ready_o,
  input logic state_valid_i, input logic signed [15:0] maximum_q11_i,
  input logic [47:0] denominator_q15_i,
  input logic signed [VALUE_DIM*64-1:0] weighted_q15_i,
  input logic signed [15:0] score_q11_i,
  input logic signed [VALUE_DIM*8-1:0] value_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic state_valid_o, output logic signed [15:0] maximum_q11_o,
  output logic [47:0] denominator_q15_o,
  output logic signed [VALUE_DIM*64-1:0] weighted_q15_o
);
  logic exp_busy_q, scale_valid_q, half_valid_q, digit_valid_q;
  logic accum0_valid_q, accum1_valid_q, accum2_valid_q, accum3_valid_q;
  logic product_valid_q, round_valid_q, rescale_valid_q, state_valid_q;
  logic signed [15:0] new_maximum_w, new_maximum_q;
  logic signed [16:0] old_delta_wide, new_delta_wide;
  logic signed [15:0] old_delta_w, new_delta_w;
  logic [47:0] denominator_q;
  logic signed [63:0] weighted_q [0:VALUE_DIM-1];
  logic signed [7:0] value_q [0:VALUE_DIM-1];
  logic old_exp_valid, new_exp_valid;
  logic [15:0] old_scale, new_scale, old_scale_q, new_scale_q;
  logic [51:0] denominator_digit0_q, denominator_digit1_q;
  logic [51:0] denominator_digit2_q, denominator_digit3_q;
  logic [35:0] weighted_low0_q [0:VALUE_DIM-1];
  logic [35:0] weighted_low1_q [0:VALUE_DIM-1];
  logic [35:0] weighted_low2_q [0:VALUE_DIM-1];
  logic [35:0] weighted_low3_q [0:VALUE_DIM-1];
  logic signed [36:0] weighted_high0_q [0:VALUE_DIM-1];
  logic signed [36:0] weighted_high1_q [0:VALUE_DIM-1];
  logic signed [36:0] weighted_high2_q [0:VALUE_DIM-1];
  logic signed [36:0] weighted_high3_q [0:VALUE_DIM-1];
  logic signed [68:0] weighted_digit0_q [0:VALUE_DIM-1];
  logic signed [68:0] weighted_digit1_q [0:VALUE_DIM-1];
  logic signed [68:0] weighted_digit2_q [0:VALUE_DIM-1];
  logic signed [68:0] weighted_digit3_q [0:VALUE_DIM-1];
  logic [63:0] denominator_product_q;
  logic signed [80:0] weighted_product_q [0:VALUE_DIM-1];
  logic signed [23:0] new_weighted_q [0:VALUE_DIM-1];
  logic [63:0] denominator_rescaled_q;
  logic signed [63:0] weighted_rescaled_q [0:VALUE_DIM-1];
  logic weighted_negative_q [0:VALUE_DIM-1];
  logic weighted_round_up_q [0:VALUE_DIM-1];
  logic [63:0] weighted_quotient_q [0:VALUE_DIM-1];

  assign req_ready_o = !exp_busy_q && !scale_valid_q && !half_valid_q &&
      !digit_valid_q && !accum0_valid_q && !accum1_valid_q &&
      !accum2_valid_q && !accum3_valid_q && !product_valid_q &&
      !round_valid_q && !rescale_valid_q && !rsp_valid_o;
  assign new_maximum_w = maximum_q11_i > score_q11_i ? maximum_q11_i : score_q11_i;
  assign old_delta_wide = {maximum_q11_i[15], maximum_q11_i} -
                          {new_maximum_w[15], new_maximum_w};
  assign new_delta_wide = {score_q11_i[15], score_q11_i} -
                          {new_maximum_w[15], new_maximum_w};
  assign old_delta_w = old_delta_wide < -17'sd32768 ? -16'sd32768 : old_delta_wide[15:0];
  assign new_delta_w = new_delta_wide < -17'sd32768 ? -16'sd32768 : new_delta_wide[15:0];

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
        64'((remainder > 15'd16384) || ((remainder == 15'd16384) && quotient[0]));
    end
  endfunction

  function automatic [65:0] rne_prepare_signed(input logic signed [80:0] value);
    logic negative; logic [80:0] magnitude, quotient;
    logic [14:0] remainder; logic round_up;
    begin
      negative = value[80];
      magnitude = negative ? (~value + 1'b1) : value;
      quotient = magnitude >> 15; remainder = magnitude[14:0];
      round_up = (remainder > 15'd16384) ||
                 ((remainder == 15'd16384) && quotient[0]);
      rne_prepare_signed = {negative, round_up, quotient[63:0]};
    end
  endfunction

  function automatic signed [63:0] rne_commit_signed(
      input logic negative, input logic round_up, input logic [63:0] quotient);
    logic [64:0] rounded;
    begin
      rounded = {1'b0, quotient} + 65'(round_up);
      rne_commit_signed = negative ? -$signed(rounded[63:0]) : $signed(rounded[63:0]);
    end
  endfunction

  logic [63:0] denominator_rescaled_w;
  logic [65:0] weighted_round_prep_w [0:VALUE_DIM-1];
  logic signed [63:0] weighted_round_commit_w [0:VALUE_DIM-1];
  assign denominator_rescaled_w = rne_shift15_unsigned(denominator_product_q);
  genvar output_lane;
  generate for (output_lane = 0; output_lane < VALUE_DIM; output_lane++) begin : g_output
    assign weighted_round_prep_w[output_lane] =
        rne_prepare_signed(weighted_product_q[output_lane]);
    assign weighted_round_commit_w[output_lane] = rne_commit_signed(
        weighted_negative_q[output_lane], weighted_round_up_q[output_lane],
        weighted_quotient_q[output_lane]);
  end endgenerate

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      exp_busy_q <= '0; scale_valid_q <= '0; half_valid_q <= '0;
      digit_valid_q <= '0; accum0_valid_q <= '0; accum1_valid_q <= '0;
      accum2_valid_q <= '0; accum3_valid_q <= '0;
      product_valid_q <= '0; round_valid_q <= '0; rescale_valid_q <= '0;
      rsp_valid_o <= '0; state_valid_q <= '0; new_maximum_q <= '0;
      denominator_q <= '0; old_scale_q <= '0; new_scale_q <= '0;
      denominator_digit0_q <= '0; denominator_digit1_q <= '0;
      denominator_digit2_q <= '0; denominator_digit3_q <= '0;
      denominator_product_q <= '0; denominator_rescaled_q <= '0;
      state_valid_o <= '0; maximum_q11_o <= '0; denominator_q15_o <= '0;
      weighted_q15_o <= '0;
      for (int lane = 0; lane < VALUE_DIM; lane++) begin
        weighted_q[lane] <= '0; value_q[lane] <= '0;
        weighted_low0_q[lane] <= '0; weighted_low1_q[lane] <= '0;
        weighted_low2_q[lane] <= '0; weighted_low3_q[lane] <= '0;
        weighted_high0_q[lane] <= '0; weighted_high1_q[lane] <= '0;
        weighted_high2_q[lane] <= '0; weighted_high3_q[lane] <= '0;
        weighted_digit0_q[lane] <= '0; weighted_digit1_q[lane] <= '0;
        weighted_digit2_q[lane] <= '0; weighted_digit3_q[lane] <= '0;
        weighted_product_q[lane] <= '0; weighted_rescaled_q[lane] <= '0;
        weighted_negative_q[lane] <= '0; weighted_round_up_q[lane] <= '0;
        weighted_quotient_q[lane] <= '0; new_weighted_q[lane] <= '0;
      end
    end else begin
      if (rsp_valid_o && rsp_ready_i) rsp_valid_o <= 1'b0;
      if (req_valid_i && req_ready_o) begin
        exp_busy_q <= 1'b1; state_valid_q <= state_valid_i;
        new_maximum_q <= state_valid_i ? new_maximum_w : score_q11_i;
        denominator_q <= denominator_q15_i;
        for (int lane = 0; lane < VALUE_DIM; lane++) begin
          weighted_q[lane] <= weighted_q15_i[lane*64 +: 64];
          value_q[lane] <= value_i[lane*8 +: 8];
        end
      end
      if (exp_busy_q && old_exp_valid && new_exp_valid) begin
        exp_busy_q <= 1'b0; scale_valid_q <= 1'b1;
        old_scale_q <= old_scale; new_scale_q <= new_scale;
      end
      if (scale_valid_q) begin
        scale_valid_q <= 1'b0; half_valid_q <= 1'b1;
        denominator_digit0_q <= denominator_q * old_scale_q[3:0];
        denominator_digit1_q <= denominator_q * old_scale_q[7:4];
        denominator_digit2_q <= denominator_q * old_scale_q[11:8];
        denominator_digit3_q <= denominator_q * old_scale_q[15:12];
        for (int lane = 0; lane < VALUE_DIM; lane++) begin
          weighted_low0_q[lane] <= $unsigned(weighted_q[lane][31:0]) * old_scale_q[3:0];
          weighted_low1_q[lane] <= $unsigned(weighted_q[lane][31:0]) * old_scale_q[7:4];
          weighted_low2_q[lane] <= $unsigned(weighted_q[lane][31:0]) * old_scale_q[11:8];
          weighted_low3_q[lane] <= $unsigned(weighted_q[lane][31:0]) * old_scale_q[15:12];
          weighted_high0_q[lane] <= $signed(weighted_q[lane][63:32]) * $signed({1'b0, old_scale_q[3:0]});
          weighted_high1_q[lane] <= $signed(weighted_q[lane][63:32]) * $signed({1'b0, old_scale_q[7:4]});
          weighted_high2_q[lane] <= $signed(weighted_q[lane][63:32]) * $signed({1'b0, old_scale_q[11:8]});
          weighted_high3_q[lane] <= $signed(weighted_q[lane][63:32]) * $signed({1'b0, old_scale_q[15:12]});
          new_weighted_q[lane] <= value_q[lane] * $signed({1'b0, new_scale_q});
        end
      end
      if (half_valid_q) begin
        half_valid_q <= 1'b0; digit_valid_q <= 1'b1;
        for (int lane = 0; lane < VALUE_DIM; lane++) begin
          weighted_digit0_q[lane] <= ({{32{weighted_high0_q[lane][36]}}, weighted_high0_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low0_q[lane]};
          weighted_digit1_q[lane] <= ({{32{weighted_high1_q[lane][36]}}, weighted_high1_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low1_q[lane]};
          weighted_digit2_q[lane] <= ({{32{weighted_high2_q[lane][36]}}, weighted_high2_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low2_q[lane]};
          weighted_digit3_q[lane] <= ({{32{weighted_high3_q[lane][36]}}, weighted_high3_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low3_q[lane]};
        end
      end
      if (digit_valid_q) begin
        digit_valid_q <= 1'b0; accum0_valid_q <= 1'b1;
        denominator_product_q <= {{12{1'b0}}, denominator_digit0_q};
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_product_q[lane] <= {{12{weighted_digit0_q[lane][68]}}, weighted_digit0_q[lane]};
      end
      if (accum0_valid_q) begin
        accum0_valid_q <= 1'b0; accum1_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit1_q} << 4);
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit1_q[lane][68]}}, weighted_digit1_q[lane]} <<< 4);
      end
      if (accum1_valid_q) begin
        accum1_valid_q <= 1'b0; accum2_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit2_q} << 8);
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit2_q[lane][68]}}, weighted_digit2_q[lane]} <<< 8);
      end
      if (accum2_valid_q) begin
        accum2_valid_q <= 1'b0; accum3_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit3_q} << 12);
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit3_q[lane][68]}}, weighted_digit3_q[lane]} <<< 12);
      end
      if (accum3_valid_q) begin
        accum3_valid_q <= 1'b0; product_valid_q <= 1'b1;
      end
      if (product_valid_q) begin
        product_valid_q <= 1'b0;
        if (state_valid_q) begin
          round_valid_q <= 1'b1; denominator_rescaled_q <= denominator_rescaled_w;
          for (int lane = 0; lane < VALUE_DIM; lane++) begin
            weighted_negative_q[lane] <= weighted_round_prep_w[lane][65];
            weighted_round_up_q[lane] <= weighted_round_prep_w[lane][64];
            weighted_quotient_q[lane] <= weighted_round_prep_w[lane][63:0];
          end
        end else begin
          rsp_valid_o <= 1'b1; state_valid_o <= 1'b1;
          maximum_q11_o <= new_maximum_q; denominator_q15_o <= 48'd32768;
          for (int lane = 0; lane < VALUE_DIM; lane++) weighted_q15_o[lane*64 +: 64] <= value_q[lane] * 17'sd32768;
        end
      end
      if (round_valid_q) begin
        round_valid_q <= 1'b0; rescale_valid_q <= 1'b1;
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_rescaled_q[lane] <= weighted_round_commit_w[lane];
      end
      if (rescale_valid_q) begin
        rescale_valid_q <= 1'b0; rsp_valid_o <= 1'b1; state_valid_o <= 1'b1;
        maximum_q11_o <= new_maximum_q;
        denominator_q15_o <= denominator_rescaled_q[47:0] + {{32{1'b0}}, new_scale_q};
        for (int lane = 0; lane < VALUE_DIM; lane++)
          weighted_q15_o[lane*64 +: 64] <= weighted_rescaled_q[lane] + {{40{new_weighted_q[lane][23]}}, new_weighted_q[lane]};
      end
    end
  end
endmodule
