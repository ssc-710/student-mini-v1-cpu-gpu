// SPDX-License-Identifier: Apache-2.0
// Bit-exact restoring divider with distinct RNE and saturation stages.
module fixed_divider_rne_round_pipeline #(
  parameter int NUM_WIDTH = 64,
  parameter int DEN_WIDTH = 48,
  parameter int OUT_WIDTH = 32,
  parameter int FRAC_BITS = 16,
  localparam int TOTAL_WIDTH = NUM_WIDTH + FRAC_BITS,
  localparam int INDEX_WIDTH = $clog2(TOTAL_WIDTH + 1)
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [NUM_WIDTH-1:0] numerator_i,
  input logic [DEN_WIDTH-1:0] denominator_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [OUT_WIDTH-1:0] quotient_o,
  output logic divide_by_zero_o, output logic saturated_o
);
  typedef enum logic [2:0] {IDLE, DIVIDE, ROUND, SATURATE, RESPONSE} state_t;
  state_t state_q;
  logic negative_q;
  logic [DEN_WIDTH-1:0] denominator_q;
  logic [TOTAL_WIDTH-1:0] dividend_q, quotient_work_q;
  logic [DEN_WIDTH:0] remainder_q;
  logic [INDEX_WIDTH-1:0] bit_q;
  logic [TOTAL_WIDTH:0] rounded_q;
  logic signed [OUT_WIDTH-1:0] result_q;
  logic divide_by_zero_q, saturated_q;

  logic [DEN_WIDTH:0] shifted_remainder, remainder_after_step;
  logic [TOTAL_WIDTH-1:0] quotient_after_step;
  logic [TOTAL_WIDTH:0] rounded_magnitude;
  logic round_increment;
  logic [OUT_WIDTH-1:0] positive_limit, negative_limit;
  logic [NUM_WIDTH-1:0] numerator_magnitude;

  assign numerator_magnitude = numerator_i[NUM_WIDTH-1] ?
                               (~numerator_i + 1'b1) : numerator_i;
  assign shifted_remainder = {remainder_q[DEN_WIDTH-1:0], dividend_q[bit_q]};
  always_comb begin
    quotient_after_step = quotient_work_q;
    remainder_after_step = shifted_remainder;
    if (shifted_remainder >= {1'b0, denominator_q}) begin
      remainder_after_step = shifted_remainder - {1'b0, denominator_q};
      quotient_after_step[bit_q] = 1'b1;
    end
  end

  assign round_increment = ({remainder_q, 1'b0} > {2'b00, denominator_q}) ||
                           (({remainder_q, 1'b0} == {2'b00, denominator_q}) &&
                            quotient_work_q[0]);
  assign rounded_magnitude = {1'b0, quotient_work_q} +
                             {{TOTAL_WIDTH{1'b0}}, round_increment};
  assign positive_limit = {1'b0, {(OUT_WIDTH-1){1'b1}}};
  assign negative_limit = {1'b1, {(OUT_WIDTH-1){1'b0}}};

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign quotient_o = result_q;
  assign divide_by_zero_o = divide_by_zero_q;
  assign saturated_o = saturated_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      negative_q <= 1'b0;
      denominator_q <= '0;
      dividend_q <= '0;
      quotient_work_q <= '0;
      remainder_q <= '0;
      bit_q <= '0;
      rounded_q <= '0;
      result_q <= '0;
      divide_by_zero_q <= 1'b0;
      saturated_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          result_q <= '0;
          divide_by_zero_q <= denominator_i == 0;
          saturated_q <= 1'b0;
          if (denominator_i == 0) state_q <= RESPONSE;
          else begin
            negative_q <= numerator_i[NUM_WIDTH-1];
            denominator_q <= denominator_i;
            dividend_q <= {numerator_magnitude, {FRAC_BITS{1'b0}}};
            quotient_work_q <= '0;
            remainder_q <= '0;
            bit_q <= INDEX_WIDTH'(TOTAL_WIDTH - 1);
            state_q <= DIVIDE;
          end
        end
        DIVIDE: begin
          quotient_work_q <= quotient_after_step;
          remainder_q <= remainder_after_step;
          if (bit_q == 0) state_q <= ROUND;
          else bit_q <= bit_q - 1'b1;
        end
        ROUND: begin
          rounded_q <= rounded_magnitude;
          state_q <= SATURATE;
        end
        SATURATE: begin
          if (!negative_q) begin
            if (rounded_q > {{(TOTAL_WIDTH + 1 - OUT_WIDTH){1'b0}}, positive_limit}) begin
              result_q <= $signed(positive_limit);
              saturated_q <= 1'b1;
            end else result_q <= $signed(rounded_q[OUT_WIDTH-1:0]);
          end else begin
            if (rounded_q > {{(TOTAL_WIDTH + 1 - OUT_WIDTH){1'b0}}, negative_limit}) begin
              result_q <= $signed(negative_limit);
              saturated_q <= 1'b1;
            end else result_q <= -$signed(rounded_q[OUT_WIDTH-1:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
