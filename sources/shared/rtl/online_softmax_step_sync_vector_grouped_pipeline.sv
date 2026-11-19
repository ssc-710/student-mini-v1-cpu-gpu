// SPDX-License-Identifier: Apache-2.0
// Area-bounded vector Online Softmax update.  The full state is retained, but
// the expensive weighted-value rescale datapath is shared by a fixed lane
// group.  Groups are visited from low to high lane order; arithmetic and RNE
// boundaries are identical to the fully parallel B22 implementation.
`ifdef P1_GROUPED_SOFTMAX_COMPARE
module online_softmax_step_sync_vector_grouped_pipeline #(
`else
module online_softmax_step_sync_vector_serial_accum_pipeline #(
`endif
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
`ifdef P1_SOFTMAX_GROUP1
  localparam int GROUP_LANES = 1;
`elsif P1_SOFTMAX_GROUP4
  localparam int GROUP_LANES = VALUE_DIM < 4 ? VALUE_DIM : 4;
`elsif P1_SOFTMAX_GROUP8
  localparam int GROUP_LANES = VALUE_DIM < 8 ? VALUE_DIM : 8;
`elsif P1_SOFTMAX_GROUP16
  localparam int GROUP_LANES = VALUE_DIM < 16 ? VALUE_DIM : 16;
`else
  localparam int GROUP_LANES = VALUE_DIM;
`endif
  localparam int GROUP_COUNT = VALUE_DIM / GROUP_LANES;
  localparam int GROUP_W = GROUP_COUNT <= 1 ? 1 : $clog2(GROUP_COUNT);
  localparam int WEIGHTED_BITS = VALUE_DIM * 64;
  localparam int VALUE_BITS = VALUE_DIM * 8;
  localparam int GROUP_WEIGHTED_BITS = GROUP_LANES * 64;

  initial begin
    if (VALUE_DIM <= 0 || GROUP_LANES <= 0 || VALUE_DIM % GROUP_LANES != 0)
      $fatal(1, "VALUE_DIM must be a positive multiple of GROUP_LANES");
  end

  logic busy_q;
  logic exp_busy_q, scale_valid_q, operand_valid_q, half_valid_q, digit_valid_q;
  logic accum0_valid_q, accum1_valid_q, accum2_valid_q, accum3_valid_q;
  logic product_valid_q, round_valid_q, rescale_valid_q, state_valid_q;
  logic signed [15:0] new_maximum_w, new_maximum_q;
  logic signed [16:0] old_delta_wide, new_delta_wide;
  logic signed [15:0] old_delta_w, new_delta_w;
  logic [47:0] denominator_q;
  logic signed [WEIGHTED_BITS-1:0] weighted_work_q, weighted_result_q;
  logic signed [VALUE_BITS-1:0] value_work_q, value_original_q;
  logic [GROUP_W-1:0] group_q;
  logic old_exp_valid, new_exp_valid;
  logic [15:0] old_scale, new_scale, old_scale_q, new_scale_q;
  logic [47:0] denominator_operand0_q, denominator_operand1_q;
  logic [47:0] denominator_operand2_q, denominator_operand3_q;
  logic [3:0] denominator_scale0_q, denominator_scale1_q;
  logic [3:0] denominator_scale2_q, denominator_scale3_q;
  logic [31:0] weighted_low_operand0_q [0:GROUP_LANES-1];
  logic [31:0] weighted_low_operand1_q [0:GROUP_LANES-1];
  logic [31:0] weighted_low_operand2_q [0:GROUP_LANES-1];
  logic [31:0] weighted_low_operand3_q [0:GROUP_LANES-1];
  logic signed [31:0] weighted_high_operand0_q [0:GROUP_LANES-1];
  logic signed [31:0] weighted_high_operand1_q [0:GROUP_LANES-1];
  logic signed [31:0] weighted_high_operand2_q [0:GROUP_LANES-1];
  logic signed [31:0] weighted_high_operand3_q [0:GROUP_LANES-1];
  logic [3:0] weighted_scale0_q [0:GROUP_LANES-1];
  logic [3:0] weighted_scale1_q [0:GROUP_LANES-1];
  logic [3:0] weighted_scale2_q [0:GROUP_LANES-1];
  logic [3:0] weighted_scale3_q [0:GROUP_LANES-1];
  logic signed [7:0] value_operand_q [0:GROUP_LANES-1];
  logic [15:0] new_scale_operand_q [0:GROUP_LANES-1];
  logic [27:0] denominator_low0_q, denominator_low1_q;
  logic [27:0] denominator_low2_q, denominator_low3_q;
  logic [27:0] denominator_high0_q, denominator_high1_q;
  logic [27:0] denominator_high2_q, denominator_high3_q;
  logic [51:0] denominator_digit0_q, denominator_digit1_q;
  logic [51:0] denominator_digit2_q, denominator_digit3_q;
  logic [63:0] denominator_product_q, denominator_rescaled_q;
  logic [35:0] weighted_low0_q [0:GROUP_LANES-1];
  logic [35:0] weighted_low1_q [0:GROUP_LANES-1];
  logic [35:0] weighted_low2_q [0:GROUP_LANES-1];
  logic [35:0] weighted_low3_q [0:GROUP_LANES-1];
  logic signed [36:0] weighted_high0_q [0:GROUP_LANES-1];
  logic signed [36:0] weighted_high1_q [0:GROUP_LANES-1];
  logic signed [36:0] weighted_high2_q [0:GROUP_LANES-1];
  logic signed [36:0] weighted_high3_q [0:GROUP_LANES-1];
  logic signed [68:0] weighted_digit0_q [0:GROUP_LANES-1];
  logic signed [68:0] weighted_digit1_q [0:GROUP_LANES-1];
  logic signed [68:0] weighted_digit2_q [0:GROUP_LANES-1];
  logic signed [68:0] weighted_digit3_q [0:GROUP_LANES-1];
  logic signed [80:0] weighted_product_q [0:GROUP_LANES-1];
  logic signed [23:0] new_weighted_q [0:GROUP_LANES-1];
  logic weighted_negative_q [0:GROUP_LANES-1];
  logic weighted_round_up_q [0:GROUP_LANES-1];
  logic [63:0] weighted_quotient_q [0:GROUP_LANES-1];
  logic signed [63:0] weighted_rescaled_q [0:GROUP_LANES-1];

  // All pipeline stages belong to exactly one in-flight request.  Tracking
  // that transaction explicitly avoids feeding a wide OR of every stage
  // valid into the clock-enable mux of the full weighted state register.
  assign req_ready_o = !busy_q && !rsp_valid_o;
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
  logic [65:0] weighted_round_prep_w [0:GROUP_LANES-1];
  logic signed [63:0] weighted_round_commit_w [0:GROUP_LANES-1];
  logic signed [GROUP_WEIGHTED_BITS-1:0] group_commit_w;
  logic signed [WEIGHTED_BITS-1:0] weighted_result_next_w;
  assign denominator_rescaled_w = rne_shift15_unsigned(denominator_product_q);

  genvar output_lane;
  generate for (output_lane = 0; output_lane < GROUP_LANES; output_lane++) begin : g_output
    assign weighted_round_prep_w[output_lane] =
        rne_prepare_signed(weighted_product_q[output_lane]);
    assign weighted_round_commit_w[output_lane] = rne_commit_signed(
        weighted_negative_q[output_lane], weighted_round_up_q[output_lane],
        weighted_quotient_q[output_lane]);
    assign group_commit_w[output_lane*64 +: 64] =
        weighted_rescaled_q[output_lane] +
        {{40{new_weighted_q[output_lane][23]}}, new_weighted_q[output_lane]};
  end endgenerate
  generate
    if (GROUP_COUNT == 1) begin : g_single_group_result
      assign weighted_result_next_w = group_commit_w;
    end else begin : g_multi_group_result
      assign weighted_result_next_w = {
        group_commit_w, weighted_result_q[WEIGHTED_BITS-1:GROUP_WEIGHTED_BITS]};
    end
  endgenerate

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy_q <= '0;
      exp_busy_q <= '0; scale_valid_q <= '0; operand_valid_q <= '0; half_valid_q <= '0;
      digit_valid_q <= '0; accum0_valid_q <= '0; accum1_valid_q <= '0;
      accum2_valid_q <= '0; accum3_valid_q <= '0; product_valid_q <= '0;
      round_valid_q <= '0; rescale_valid_q <= '0; rsp_valid_o <= '0;
      state_valid_q <= '0; new_maximum_q <= '0; denominator_q <= '0;
      weighted_work_q <= '0; weighted_result_q <= '0;
      value_work_q <= '0; value_original_q <= '0; group_q <= '0;
      old_scale_q <= '0; new_scale_q <= '0;
      denominator_operand0_q <= '0; denominator_operand1_q <= '0;
      denominator_operand2_q <= '0; denominator_operand3_q <= '0;
      denominator_scale0_q <= '0; denominator_scale1_q <= '0;
      denominator_scale2_q <= '0; denominator_scale3_q <= '0;
      denominator_low0_q <= '0; denominator_low1_q <= '0;
      denominator_low2_q <= '0; denominator_low3_q <= '0;
      denominator_high0_q <= '0; denominator_high1_q <= '0;
      denominator_high2_q <= '0; denominator_high3_q <= '0;
      denominator_digit0_q <= '0; denominator_digit1_q <= '0;
      denominator_digit2_q <= '0; denominator_digit3_q <= '0;
      denominator_product_q <= '0; denominator_rescaled_q <= '0;
      state_valid_o <= '0; maximum_q11_o <= '0; denominator_q15_o <= '0;
      weighted_q15_o <= '0;
      for (int lane = 0; lane < GROUP_LANES; lane++) begin
        weighted_low0_q[lane] <= '0; weighted_low1_q[lane] <= '0;
        weighted_low2_q[lane] <= '0; weighted_low3_q[lane] <= '0;
        weighted_high0_q[lane] <= '0; weighted_high1_q[lane] <= '0;
        weighted_high2_q[lane] <= '0; weighted_high3_q[lane] <= '0;
        weighted_low_operand0_q[lane] <= '0; weighted_low_operand1_q[lane] <= '0;
        weighted_low_operand2_q[lane] <= '0; weighted_low_operand3_q[lane] <= '0;
        weighted_high_operand0_q[lane] <= '0; weighted_high_operand1_q[lane] <= '0;
        weighted_high_operand2_q[lane] <= '0; weighted_high_operand3_q[lane] <= '0;
        weighted_scale0_q[lane] <= '0; weighted_scale1_q[lane] <= '0;
        weighted_scale2_q[lane] <= '0; weighted_scale3_q[lane] <= '0;
        value_operand_q[lane] <= '0; new_scale_operand_q[lane] <= '0;
        weighted_digit0_q[lane] <= '0; weighted_digit1_q[lane] <= '0;
        weighted_digit2_q[lane] <= '0; weighted_digit3_q[lane] <= '0;
        weighted_product_q[lane] <= '0; new_weighted_q[lane] <= '0;
        weighted_negative_q[lane] <= '0; weighted_round_up_q[lane] <= '0;
        weighted_quotient_q[lane] <= '0; weighted_rescaled_q[lane] <= '0;
      end
    end else begin
      if (rsp_valid_o && rsp_ready_i) begin
        rsp_valid_o <= 1'b0;
        busy_q <= 1'b0;
      end
      if (req_valid_i && req_ready_o) begin
        busy_q <= 1'b1;
        exp_busy_q <= 1'b1; state_valid_q <= state_valid_i;
        new_maximum_q <= state_valid_i ? new_maximum_w : score_q11_i;
        denominator_q <= denominator_q15_i;
        weighted_work_q <= weighted_q15_i; weighted_result_q <= '0;
        value_work_q <= value_i; value_original_q <= value_i; group_q <= '0;
      end
      if (exp_busy_q && old_exp_valid && new_exp_valid) begin
        exp_busy_q <= 1'b0; scale_valid_q <= 1'b1;
        old_scale_q <= old_scale; new_scale_q <= new_scale;
      end
      if (scale_valid_q) begin
        scale_valid_q <= 1'b0; operand_valid_q <= 1'b1;
        denominator_operand0_q <= denominator_q;
        denominator_operand1_q <= denominator_q;
        denominator_operand2_q <= denominator_q;
        denominator_operand3_q <= denominator_q;
        denominator_scale0_q <= old_scale_q[3:0];
        denominator_scale1_q <= old_scale_q[7:4];
        denominator_scale2_q <= old_scale_q[11:8];
        denominator_scale3_q <= old_scale_q[15:12];
        for (int lane = 0; lane < GROUP_LANES; lane++) begin
          weighted_low_operand0_q[lane] <= weighted_work_q[lane*64 +: 32];
          weighted_low_operand1_q[lane] <= weighted_work_q[lane*64 +: 32];
          weighted_low_operand2_q[lane] <= weighted_work_q[lane*64 +: 32];
          weighted_low_operand3_q[lane] <= weighted_work_q[lane*64 +: 32];
          weighted_high_operand0_q[lane] <= weighted_work_q[lane*64+32 +: 32];
          weighted_high_operand1_q[lane] <= weighted_work_q[lane*64+32 +: 32];
          weighted_high_operand2_q[lane] <= weighted_work_q[lane*64+32 +: 32];
          weighted_high_operand3_q[lane] <= weighted_work_q[lane*64+32 +: 32];
          weighted_scale0_q[lane] <= old_scale_q[3:0];
          weighted_scale1_q[lane] <= old_scale_q[7:4];
          weighted_scale2_q[lane] <= old_scale_q[11:8];
          weighted_scale3_q[lane] <= old_scale_q[15:12];
          value_operand_q[lane] <= value_work_q[lane*8 +: 8];
          new_scale_operand_q[lane] <= new_scale_q;
        end
      end
      if (operand_valid_q) begin
        operand_valid_q <= 1'b0; half_valid_q <= 1'b1;
        // A direct 48x4 digit multiply remained the measured 10 ns path even
        // after the operand register cut.  Form exact 24x4 halves here and
        // use the already-present half_valid stage to recompose the 52-bit
        // product; no externally visible latency or arithmetic changes.
        denominator_low0_q <= denominator_operand0_q[23:0] * denominator_scale0_q;
        denominator_low1_q <= denominator_operand1_q[23:0] * denominator_scale1_q;
        denominator_low2_q <= denominator_operand2_q[23:0] * denominator_scale2_q;
        denominator_low3_q <= denominator_operand3_q[23:0] * denominator_scale3_q;
        denominator_high0_q <= denominator_operand0_q[47:24] * denominator_scale0_q;
        denominator_high1_q <= denominator_operand1_q[47:24] * denominator_scale1_q;
        denominator_high2_q <= denominator_operand2_q[47:24] * denominator_scale2_q;
        denominator_high3_q <= denominator_operand3_q[47:24] * denominator_scale3_q;
        for (int lane = 0; lane < GROUP_LANES; lane++) begin
          weighted_low0_q[lane] <= $unsigned(weighted_low_operand0_q[lane]) * weighted_scale0_q[lane];
          weighted_low1_q[lane] <= $unsigned(weighted_low_operand1_q[lane]) * weighted_scale1_q[lane];
          weighted_low2_q[lane] <= $unsigned(weighted_low_operand2_q[lane]) * weighted_scale2_q[lane];
          weighted_low3_q[lane] <= $unsigned(weighted_low_operand3_q[lane]) * weighted_scale3_q[lane];
          weighted_high0_q[lane] <= $signed(weighted_high_operand0_q[lane]) * $signed({1'b0, weighted_scale0_q[lane]});
          weighted_high1_q[lane] <= $signed(weighted_high_operand1_q[lane]) * $signed({1'b0, weighted_scale1_q[lane]});
          weighted_high2_q[lane] <= $signed(weighted_high_operand2_q[lane]) * $signed({1'b0, weighted_scale2_q[lane]});
          weighted_high3_q[lane] <= $signed(weighted_high_operand3_q[lane]) * $signed({1'b0, weighted_scale3_q[lane]});
          new_weighted_q[lane] <= $signed(value_operand_q[lane]) * $signed({1'b0, new_scale_operand_q[lane]});
        end
      end
      if (half_valid_q) begin
        half_valid_q <= 1'b0; digit_valid_q <= 1'b1;
        denominator_digit0_q <= ({24'b0, denominator_high0_q} << 24) +
                                {{24{1'b0}}, denominator_low0_q};
        denominator_digit1_q <= ({24'b0, denominator_high1_q} << 24) +
                                {{24{1'b0}}, denominator_low1_q};
        denominator_digit2_q <= ({24'b0, denominator_high2_q} << 24) +
                                {{24{1'b0}}, denominator_low2_q};
        denominator_digit3_q <= ({24'b0, denominator_high3_q} << 24) +
                                {{24{1'b0}}, denominator_low3_q};
        for (int lane = 0; lane < GROUP_LANES; lane++) begin
          weighted_digit0_q[lane] <= ({{32{weighted_high0_q[lane][36]}}, weighted_high0_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low0_q[lane]};
          weighted_digit1_q[lane] <= ({{32{weighted_high1_q[lane][36]}}, weighted_high1_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low1_q[lane]};
          weighted_digit2_q[lane] <= ({{32{weighted_high2_q[lane][36]}}, weighted_high2_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low2_q[lane]};
          weighted_digit3_q[lane] <= ({{32{weighted_high3_q[lane][36]}}, weighted_high3_q[lane]} <<< 32) + {{33{1'b0}}, weighted_low3_q[lane]};
        end
      end
      if (digit_valid_q) begin
        digit_valid_q <= 1'b0; accum0_valid_q <= 1'b1;
        denominator_product_q <= {{12{1'b0}}, denominator_digit0_q};
        for (int lane = 0; lane < GROUP_LANES; lane++)
          weighted_product_q[lane] <= {{12{weighted_digit0_q[lane][68]}}, weighted_digit0_q[lane]};
      end
      if (accum0_valid_q) begin
        accum0_valid_q <= 1'b0; accum1_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit1_q} << 4);
        for (int lane = 0; lane < GROUP_LANES; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit1_q[lane][68]}}, weighted_digit1_q[lane]} <<< 4);
      end
      if (accum1_valid_q) begin
        accum1_valid_q <= 1'b0; accum2_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit2_q} << 8);
        for (int lane = 0; lane < GROUP_LANES; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit2_q[lane][68]}}, weighted_digit2_q[lane]} <<< 8);
      end
      if (accum2_valid_q) begin
        accum2_valid_q <= 1'b0; accum3_valid_q <= 1'b1;
        denominator_product_q <= denominator_product_q + ({{12{1'b0}}, denominator_digit3_q} << 12);
        for (int lane = 0; lane < GROUP_LANES; lane++)
          weighted_product_q[lane] <= weighted_product_q[lane] + ({{12{weighted_digit3_q[lane][68]}}, weighted_digit3_q[lane]} <<< 12);
      end
      if (accum3_valid_q) begin
        accum3_valid_q <= 1'b0; product_valid_q <= 1'b1;
      end
      if (product_valid_q) begin
        product_valid_q <= 1'b0;
        if (state_valid_q) begin
          round_valid_q <= 1'b1; denominator_rescaled_q <= denominator_rescaled_w;
          for (int lane = 0; lane < GROUP_LANES; lane++) begin
            weighted_negative_q[lane] <= weighted_round_prep_w[lane][65];
            weighted_round_up_q[lane] <= weighted_round_prep_w[lane][64];
            weighted_quotient_q[lane] <= weighted_round_prep_w[lane][63:0];
          end
        end else begin
          rsp_valid_o <= 1'b1; state_valid_o <= 1'b1;
          maximum_q11_o <= new_maximum_q; denominator_q15_o <= 48'd32768;
          for (int lane = 0; lane < VALUE_DIM; lane++)
            weighted_q15_o[lane*64 +: 64] <= $signed(value_original_q[lane*8 +: 8]) * 17'sd32768;
        end
      end
      if (round_valid_q) begin
        round_valid_q <= 1'b0; rescale_valid_q <= 1'b1;
        for (int lane = 0; lane < GROUP_LANES; lane++)
          weighted_rescaled_q[lane] <= weighted_round_commit_w[lane];
      end
      if (rescale_valid_q) begin
        rescale_valid_q <= 1'b0;
        if (group_q == GROUP_COUNT-1) begin
          rsp_valid_o <= 1'b1; state_valid_o <= 1'b1;
          maximum_q11_o <= new_maximum_q;
          denominator_q15_o <= denominator_rescaled_q[47:0] + {{32{1'b0}}, new_scale_q};
          weighted_q15_o <= weighted_result_next_w;
        end else begin
          group_q <= group_q + 1'b1;
          weighted_result_q <= weighted_result_next_w;
          weighted_work_q <= weighted_work_q >> GROUP_WEIGHTED_BITS;
          value_work_q <= value_work_q >> (GROUP_LANES * 8);
          scale_valid_q <= 1'b1;
        end
      end
    end
  end
endmodule
