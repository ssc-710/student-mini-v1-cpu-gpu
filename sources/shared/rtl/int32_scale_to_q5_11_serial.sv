// SPDX-License-Identifier: Apache-2.0
// Multi-cycle, bit-exact implementation of the frozen INT32*FP32 -> Q5.11
// contract.  Shift/add multiplication and one-bit shifts replace the B0
// combinational multiplier and variable shifter with a ready/valid seam.
module int32_scale_to_q5_11_serial #(
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
  typedef enum logic [2:0] {
    IDLE, MULTIPLY, SHIFT_LEFT, SHIFT_RIGHT, FORMAT, RESPONSE
  } state_t;
  state_t state_q;

  logic sign_q, valid_q, sticky_q;
  logic [7:0] scale_exponent_q;
  logic [31:0] multiplier_q;
  logic [55:0] multiplicand_q, product_q;
  logic [95:0] work_q;
  logic [5:0] multiply_bit_q, shift_count_q;
  logic signed [15:0] result_q;
  logic contract_scale_valid_w, relaxed_scale_valid_w, scale_valid_w;

  logic [55:0] product_after_step_w;
  logic [95:0] right_quotient_w, right_rounded_w;
  logic right_increment_w;

  fp32_scale_check u_scale_check (
    .scale_i(scale_i), .valid_o(contract_scale_valid_w));
  assign relaxed_scale_valid_w = !scale_i[31] && scale_i[30:23] != 0 &&
                                 scale_i[30:23] != 8'hff;
  assign scale_valid_w = REQUIRE_PROJECT_SCALE_RANGE ? contract_scale_valid_w :
                         relaxed_scale_valid_w;

  assign product_after_step_w = product_q +
    (multiplier_q[0] ? multiplicand_q : 56'd0);
  assign right_quotient_w = work_q >> 1;
  assign right_increment_w = work_q[0] &&
    (sticky_q || right_quotient_w[0]);
  assign right_rounded_w = right_quotient_w +
    {{95{1'b0}}, right_increment_w};

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign q5_11_o = result_q;
  assign scale_valid_o = valid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      sign_q <= 1'b0;
      valid_q <= 1'b0;
      sticky_q <= 1'b0;
      scale_exponent_q <= '0;
      multiplier_q <= '0;
      multiplicand_q <= '0;
      product_q <= '0;
      work_q <= '0;
      multiply_bit_q <= '0;
      shift_count_q <= '0;
      result_q <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          sign_q <= value_i[31];
          valid_q <= scale_valid_w;
          sticky_q <= 1'b0;
          scale_exponent_q <= scale_i[30:23];
          multiplier_q <= value_i[31] ? (~value_i + 1'b1) : value_i;
          multiplicand_q <= {32'd0, 1'b1, scale_i[22:0]};
          product_q <= '0;
          work_q <= '0;
          multiply_bit_q <= '0;
          shift_count_q <= '0;
          result_q <= '0;
          if (!scale_valid_w || value_i == 0) state_q <= RESPONSE;
          else state_q <= MULTIPLY;
        end
        MULTIPLY: begin
          product_q <= product_after_step_w;
          if (multiply_bit_q == 6'd31) begin
            work_q <= {40'd0, product_after_step_w};
            if (scale_exponent_q > 8'd139) begin
              shift_count_q <= 6'(scale_exponent_q - 8'd139);
              state_q <= SHIFT_LEFT;
            end else if (scale_exponent_q < 8'd139) begin
              shift_count_q <= 6'(8'd139 - scale_exponent_q);
              state_q <= SHIFT_RIGHT;
            end else begin
              state_q <= FORMAT;
            end
          end else begin
            multiplier_q <= multiplier_q >> 1;
            multiplicand_q <= multiplicand_q << 1;
            multiply_bit_q <= multiply_bit_q + 1'b1;
          end
        end
        SHIFT_LEFT: begin
          work_q <= work_q << 1;
          if (shift_count_q == 1) state_q <= FORMAT;
          else shift_count_q <= shift_count_q - 1'b1;
        end
        SHIFT_RIGHT: begin
          if (shift_count_q == 1) begin
            work_q <= right_rounded_w;
            state_q <= FORMAT;
          end else begin
            sticky_q <= sticky_q || work_q[0];
            work_q <= right_quotient_w;
            shift_count_q <= shift_count_q - 1'b1;
          end
        end
        FORMAT: begin
          if (sign_q) begin
            if (work_q >= 96'd32768) result_q <= -16'sd32768;
            else result_q <= -$signed(work_q[15:0]);
          end else begin
            if (work_q >= 96'd32767) result_q <= 16'sd32767;
            else result_q <= $signed(work_q[15:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
