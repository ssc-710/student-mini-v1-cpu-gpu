// SPDX-License-Identifier: Apache-2.0
// Multi-cycle exact integer-times-FP32 to BF16 converter.
//
// The B0 combinational converter is deliberately transparent, but its 32x24
// multiplier and variable normalization form a long post-route path.  This
// implementation preserves the same finite-positive-scale and BF16-RNE
// contract while using a one-bit-per-cycle shift/add multiply followed by a
// one-bit-per-cycle normalization.  Every state transition is registered, so
// the surrounding operator can treat this as a ready/valid timing seam.
module int32_times_fp32_to_bf16_serial (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic               cmd_valid_i,
  output logic               cmd_ready_o,
  input  logic signed [31:0] value_i,
  input  logic        [31:0] scale_i,
  output logic               rsp_valid_o,
  input  logic               rsp_ready_i,
  output logic        [15:0] bf16_o,
  output logic               invalid_scale_o
);
  typedef enum logic [2:0] {IDLE, MULTIPLY, NORMALIZE, FORMAT, RESPONSE} state_t;
  state_t state_q;

  logic sign_q;
  logic [7:0] scale_exponent_q;
  logic [31:0] multiplier_q;
  logic [55:0] multiplicand_q, product_q, normalized_q;
  logic [5:0] multiply_bit_q, msb_q;
  logic [15:0] result_q;
  logic invalid_q;

  logic [55:0] product_after_step_w;
  logic [8:0] retained_w, rounded_w;
  logic round_increment_w;
  logic signed [10:0] exponent_w, rounded_exponent_w;

  assign product_after_step_w = product_q +
    (multiplier_q[0] ? multiplicand_q : 56'd0);
  assign retained_w = {1'b0, normalized_q[55:48]};
  assign round_increment_w = normalized_q[47] &&
    ((|normalized_q[46:0]) || normalized_q[48]);
  assign rounded_w = retained_w + {8'd0, round_increment_w};
  assign exponent_w = $signed({3'd0, scale_exponent_q}) - 11'sd23 +
                      $signed({5'd0, msb_q});
  assign rounded_exponent_w = exponent_w + (rounded_w[8] ? 11'sd1 : 11'sd0);

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign bf16_o = result_q;
  assign invalid_scale_o = invalid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      sign_q <= 1'b0;
      scale_exponent_q <= '0;
      multiplier_q <= '0;
      multiplicand_q <= '0;
      product_q <= '0;
      normalized_q <= '0;
      multiply_bit_q <= '0;
      msb_q <= '0;
      result_q <= '0;
      invalid_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          sign_q <= value_i[31];
          scale_exponent_q <= scale_i[30:23];
          multiplier_q <= value_i[31] ? (~value_i + 1'b1) : value_i;
          multiplicand_q <= {32'd0, 1'b1, scale_i[22:0]};
          product_q <= '0;
          multiply_bit_q <= '0;
          result_q <= '0;
          invalid_q <= scale_i[31] || scale_i[30:23] == 0 ||
                       scale_i[30:23] == 8'hff;
          if (scale_i[31] || scale_i[30:23] == 0 ||
              scale_i[30:23] == 8'hff || value_i == 0) begin
            state_q <= RESPONSE;
          end else begin
            state_q <= MULTIPLY;
          end
        end
        MULTIPLY: begin
          product_q <= product_after_step_w;
          if (multiply_bit_q == 6'd31) begin
            normalized_q <= product_after_step_w;
            msb_q <= 6'd55;
            state_q <= NORMALIZE;
          end else begin
            multiplier_q <= multiplier_q >> 1;
            multiplicand_q <= multiplicand_q << 1;
            multiply_bit_q <= multiply_bit_q + 1'b1;
          end
        end
        NORMALIZE: begin
          if (normalized_q[55]) begin
            state_q <= FORMAT;
          end else begin
            normalized_q <= normalized_q << 1;
            msb_q <= msb_q - 1'b1;
          end
        end
        FORMAT: begin
          if (rounded_exponent_w <= 0 || rounded_exponent_w >= 255) begin
            result_q <= {sign_q, 8'hfe, 7'h7f};
            invalid_q <= 1'b1;
          end else if (rounded_w[8]) begin
            result_q <= {sign_q, rounded_exponent_w[7:0], rounded_w[7:1]};
          end else begin
            result_q <= {sign_q, rounded_exponent_w[7:0], rounded_w[6:0]};
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
