// SPDX-License-Identifier: Apache-2.0
// Multi-cycle, bit-exact Q10.22 to INT8 requantizer.  This is the sequential
// timing seam for the post-GEMM path: it preserves the frozen RNE/saturation
// contract without placing an 81-bit combinational divide in one clock cycle.
module q22_requantize_int8_serial (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic               cmd_valid_i,
  output logic               cmd_ready_o,
  input  logic signed [47:0] value_q22_i,
  input  logic        [31:0] scale_i,
  output logic               rsp_valid_o,
  input  logic               rsp_ready_i,
  output logic signed  [7:0] value_i8_o,
  output logic               invalid_scale_o
);
  typedef enum logic [1:0] {IDLE, START_DIVIDE, WAIT_DIVIDE, RESPONSE} state_t;
  state_t state_q;

  logic negative_q;
  logic [80:0] numerator_q;
  logic [23:0] denominator_q;
  logic signed [7:0] result_q;
  logic invalid_q;

  logic [7:0] exponent_w;
  logic [23:0] significand_w;
  logic [47:0] magnitude_w;
  logic [80:0] numerator_w;
  logic scale_valid_w;
  integer shift_w;

  always_comb begin
    exponent_w = scale_i[30:23];
    significand_w = {1'b1, scale_i[22:0]};
    magnitude_w = value_q22_i[47] ? (~value_q22_i + 1'b1) : value_q22_i;
    scale_valid_w = !scale_i[31] && exponent_w != 0 && exponent_w != 8'hff &&
                    scale_i >= 32'h37800000 && scale_i <= 32'h47800000;
    shift_w = 128 - {24'd0, exponent_w};
    numerator_w = {{33{1'b0}}, magnitude_w};
    if (shift_w >= 0) numerator_w = numerator_w << shift_w;
    else numerator_w = numerator_w >> (-shift_w);
  end

  logic divider_cmd_ready, divider_rsp_valid, divider_rsp_ready;
  logic signed [8:0] divider_quotient;
  logic divider_zero, divider_saturated;
  fixed_divider_rne #(
    .NUM_WIDTH(81), .DEN_WIDTH(24), .OUT_WIDTH(9), .FRAC_BITS(0)
  ) u_divider (
    .clk_i, .rst_ni,
    .cmd_valid_i(state_q == START_DIVIDE),
    .cmd_ready_o(divider_cmd_ready),
    .numerator_i($signed(numerator_q)),
    .denominator_i(denominator_q),
    .rsp_valid_o(divider_rsp_valid),
    .rsp_ready_i(divider_rsp_ready),
    .quotient_o(divider_quotient),
    .divide_by_zero_o(divider_zero),
    .saturated_o(divider_saturated)
  );
  assign divider_rsp_ready = state_q == WAIT_DIVIDE;

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign value_i8_o = result_q;
  assign invalid_scale_o = invalid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      negative_q <= 1'b0;
      numerator_q <= '0;
      denominator_q <= '0;
      result_q <= '0;
      invalid_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          result_q <= '0;
          invalid_q <= !scale_valid_w;
          negative_q <= value_q22_i[47];
          numerator_q <= numerator_w;
          denominator_q <= significand_w;
          if (!scale_valid_w || value_q22_i == 0) state_q <= RESPONSE;
          else state_q <= START_DIVIDE;
        end
        START_DIVIDE: if (divider_cmd_ready) state_q <= WAIT_DIVIDE;
        WAIT_DIVIDE: if (divider_rsp_valid) begin
          if (divider_zero) begin
            result_q <= '0;
            invalid_q <= 1'b1;
          end else if (negative_q) begin
            if (divider_saturated || $unsigned(divider_quotient) >= 9'd128)
              result_q <= -8'sd128;
            else result_q <= -$signed(divider_quotient[7:0]);
          end else begin
            if (divider_saturated || $unsigned(divider_quotient) > 9'd127)
              result_q <= 8'sd127;
            else result_q <= $signed(divider_quotient[7:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
