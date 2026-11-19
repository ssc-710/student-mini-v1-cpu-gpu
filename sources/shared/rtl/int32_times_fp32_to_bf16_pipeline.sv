// SPDX-License-Identifier: Apache-2.0
// Exact integer-times-positive-FP32 to BF16 converter with registered timing
// cuts around the partial products, normalization and RNE formatting.
module int32_times_fp32_to_bf16_pipeline (
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
  typedef enum logic [2:0] {
    IDLE, MULTIPLY, COMBINE, FIND_MSB,
    SHIFT_COARSE, SHIFT_FINE, FORMAT, RESPONSE
  } state_t;
  state_t state_q;

  logic sign_q;
  logic [7:0] scale_exponent_q;
  logic [31:0] magnitude_q;
  logic [23:0] significand_q;
  logic [39:0] low_product_q, high_product_q;
  logic [55:0] product_q, normalized_q;
  logic [5:0] msb_q;
  logic [2:0] fine_shift_q;
  logic [15:0] result_q;
  logic invalid_q;

  logic [6:0] nonzero_byte_w;
  logic [2:0] leading_byte_w, leading_bit_w;
  logic [7:0] selected_byte_w;
  logic [5:0] leading_one_w, shift_amount_w;
  logic [8:0] retained_w, rounded_w;
  logic round_increment_w;
  logic signed [10:0] exponent_w, rounded_exponent_w;

  assign nonzero_byte_w = {
    |product_q[55:48], |product_q[47:40], |product_q[39:32],
    |product_q[31:24], |product_q[23:16], |product_q[15:8],
    |product_q[7:0]
  };
  always_comb begin
    unique casez (nonzero_byte_w)
      7'b1??????: leading_byte_w = 3'd6;
      7'b01?????: leading_byte_w = 3'd5;
      7'b001????: leading_byte_w = 3'd4;
      7'b0001???: leading_byte_w = 3'd3;
      7'b00001??: leading_byte_w = 3'd2;
      7'b000001?: leading_byte_w = 3'd1;
      default:    leading_byte_w = 3'd0;
    endcase
    unique case (leading_byte_w)
      3'd6: selected_byte_w = product_q[55:48];
      3'd5: selected_byte_w = product_q[47:40];
      3'd4: selected_byte_w = product_q[39:32];
      3'd3: selected_byte_w = product_q[31:24];
      3'd2: selected_byte_w = product_q[23:16];
      3'd1: selected_byte_w = product_q[15:8];
      default: selected_byte_w = product_q[7:0];
    endcase
    unique casez (selected_byte_w)
      8'b1???????: leading_bit_w = 3'd7;
      8'b01??????: leading_bit_w = 3'd6;
      8'b001?????: leading_bit_w = 3'd5;
      8'b0001????: leading_bit_w = 3'd4;
      8'b00001???: leading_bit_w = 3'd3;
      8'b000001??: leading_bit_w = 3'd2;
      8'b0000001?: leading_bit_w = 3'd1;
      default:     leading_bit_w = 3'd0;
    endcase
  end
  assign leading_one_w = {leading_byte_w, 3'b000} +
                         {{3{1'b0}}, leading_bit_w};
  assign shift_amount_w = 6'd55 - msb_q;

  assign retained_w = {1'b0, normalized_q[55:48]};
  assign round_increment_w = normalized_q[47] &&
    ((|normalized_q[46:0]) || normalized_q[48]);
  assign rounded_w = retained_w + {8'd0, round_increment_w};
  assign exponent_w = $signed({3'd0, scale_exponent_q}) - 11'sd23 +
                      $signed({5'd0, msb_q});
  assign rounded_exponent_w = exponent_w +
                              (rounded_w[8] ? 11'sd1 : 11'sd0);

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign bf16_o = result_q;
  assign invalid_scale_o = invalid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      sign_q <= 1'b0;
      scale_exponent_q <= '0;
      magnitude_q <= '0;
      significand_q <= '0;
      low_product_q <= '0;
      high_product_q <= '0;
      product_q <= '0;
      normalized_q <= '0;
      msb_q <= '0;
      fine_shift_q <= '0;
      result_q <= '0;
      invalid_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          sign_q <= value_i[31];
          scale_exponent_q <= scale_i[30:23];
          magnitude_q <= value_i[31] ? (~value_i + 1'b1) : value_i;
          significand_q <= {1'b1, scale_i[22:0]};
          result_q <= '0;
          invalid_q <= scale_i[31] || scale_i[30:23] == 0 ||
                       scale_i[30:23] == 8'hff;
          if (scale_i[31] || scale_i[30:23] == 0 ||
              scale_i[30:23] == 8'hff || value_i == 0)
            state_q <= RESPONSE;
          else
            state_q <= MULTIPLY;
        end
        MULTIPLY: begin
          low_product_q <= magnitude_q[15:0] * significand_q;
          high_product_q <= magnitude_q[31:16] * significand_q;
          state_q <= COMBINE;
        end
        COMBINE: begin
          product_q <= {high_product_q, 16'd0} +
                       {{16{1'b0}}, low_product_q};
          state_q <= FIND_MSB;
        end
        FIND_MSB: begin
          msb_q <= leading_one_w;
          state_q <= SHIFT_COARSE;
        end
        SHIFT_COARSE: begin
          normalized_q <= product_q << {shift_amount_w[5:3], 3'b000};
          fine_shift_q <= shift_amount_w[2:0];
          state_q <= SHIFT_FINE;
        end
        SHIFT_FINE: begin
          normalized_q <= normalized_q << fine_shift_q;
          state_q <= FORMAT;
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
