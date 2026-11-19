// SPDX-License-Identifier: Apache-2.0
// Four-stage, bit-exact INT32*FP32 -> Q5.11 converter.  The register after
// the integer/significand product removes the measured dot-result-to-score
// multiplier+barrel-shifter path while adding only three internal cycles.
module int32_scale_to_q5_11_pipeline #(
  parameter bit REQUIRE_PROJECT_SCALE_RANGE = 1'b1
) (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic               cmd_valid_i,
  output logic               cmd_ready_o,
  input  logic signed [31:0] value_i,
  input  logic        [31:0] scale_i,
  output logic               rsp_valid_o,
  input  logic               rsp_ready_i,
  output logic signed [15:0] q5_11_o,
  output logic               scale_valid_o
);
  typedef enum logic [2:0] {IDLE, PRODUCT, ROUND_SHIFT, FORMAT, RESPONSE} state_t;
  state_t state_q;

  logic sign_q, valid_q;
  logic [7:0] exponent_q;
  logic [23:0] significand_q;
  logic [31:0] magnitude_q;
  logic [55:0] product_q;
  logic [95:0] rounded_q;
  logic signed [15:0] result_q;
  logic contract_scale_valid_w, relaxed_scale_valid_w, scale_valid_w;

  logic signed [9:0] shift_w;
  logic [95:0] extended_w, quotient_w, remainder_w, half_w;
  logic [95:0] rounded_w;
  integer right_shift;

  fp32_scale_check u_scale_check (
    .scale_i(scale_i), .valid_o(contract_scale_valid_w));
  assign relaxed_scale_valid_w = !scale_i[31] && scale_i[30:23] != 0 &&
                                 scale_i[30:23] != 8'hff;
  assign scale_valid_w = REQUIRE_PROJECT_SCALE_RANGE ? contract_scale_valid_w :
                         relaxed_scale_valid_w;

  always_comb begin
    shift_w = $signed({2'd0, exponent_q}) - 10'sd139;
    extended_w = {40'd0, product_q};
    quotient_w = '0;
    remainder_w = '0;
    half_w = '0;
    rounded_w = extended_w;
    right_shift = 0;
    if (shift_w >= 0) begin
      rounded_w = extended_w << shift_w;
    end else begin
      right_shift = -$signed({{22{shift_w[9]}}, shift_w});
      quotient_w = extended_w >> right_shift;
      remainder_w = extended_w - (quotient_w << right_shift);
      half_w = 96'd1 << (right_shift - 1);
      rounded_w = quotient_w;
      if ((remainder_w > half_w) ||
          ((remainder_w == half_w) && quotient_w[0]))
        rounded_w = quotient_w + 1'b1;
    end
  end

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign q5_11_o = result_q;
  assign scale_valid_o = valid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      sign_q <= 1'b0;
      valid_q <= 1'b0;
      exponent_q <= '0;
      significand_q <= '0;
      magnitude_q <= '0;
      product_q <= '0;
      rounded_q <= '0;
      result_q <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          sign_q <= value_i[31];
          valid_q <= scale_valid_w;
          exponent_q <= scale_i[30:23];
          significand_q <= {1'b1, scale_i[22:0]};
          magnitude_q <= value_i[31] ? (~value_i + 1'b1) : value_i;
          result_q <= '0;
          if (!scale_valid_w || value_i == 0) state_q <= RESPONSE;
          else state_q <= PRODUCT;
        end
        PRODUCT: begin
          product_q <= magnitude_q * significand_q;
          state_q <= ROUND_SHIFT;
        end
        ROUND_SHIFT: begin
          rounded_q <= rounded_w;
          state_q <= FORMAT;
        end
        FORMAT: begin
          if (sign_q) begin
            if (rounded_q >= 96'd32768) result_q <= -16'sd32768;
            else result_q <= -$signed(rounded_q[15:0]);
          end else begin
            if (rounded_q >= 96'd32767) result_q <= 16'sd32767;
            else result_q <= $signed(rounded_q[15:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
