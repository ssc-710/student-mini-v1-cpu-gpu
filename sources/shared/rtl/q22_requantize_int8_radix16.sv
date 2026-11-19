// SPDX-License-Identifier: Apache-2.0
// Three-cycle, bit-exact Q10.22 to INT8 requantizer.
//
// The numerical contract only needs a saturated 8-bit quotient.  Computing an
// 81-bit general-purpose divide (the B0 implementation) therefore creates a
// very long path for bits that can never reach the observable result.  This
// implementation first handles the saturation interval, then finds the two
// hexadecimal quotient digits in two registered stages.  RNE and signed
// saturation are identical to q22_requantize_int8.
module q22_requantize_int8_radix16 (
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
  typedef enum logic [2:0] {IDLE, HIGH_DIGIT, LOW_DIGIT, RESPONSE} state_t;
  state_t state_q;

  logic negative_q;
  logic [48:0] numerator_q;
  logic [23:0] denominator_q;
  logic [3:0] high_digit_q;
  logic signed [7:0] result_q;
  logic invalid_q;

  logic [7:0] exponent_w;
  logic [23:0] significand_w;
  logic [47:0] magnitude_w;
  logic [48:0] numerator_w;
  logic scale_valid_w;
  logic input_overflow_w;
  integer shift_w;

  // p3_expert_row_b0 forms value_q22_i by sign-extending a signed 32-bit
  // Q10.22 product.  Preserve a defensive overflow check at this seam: an
  // out-of-contract wider magnitude can only map to the corresponding INT8
  // saturation endpoint.
  always_comb begin
    exponent_w = scale_i[30:23];
    significand_w = {1'b1, scale_i[22:0]};
    magnitude_w = value_q22_i[47] ? (~value_q22_i + 1'b1) : value_q22_i;
    input_overflow_w = |magnitude_w[47:32];
    scale_valid_w = !scale_i[31] && exponent_w != 0 && exponent_w != 8'hff &&
                    scale_i >= 32'h37800000 && scale_i <= 32'h47800000;
    shift_w = 128 - {24'd0, exponent_w};
    numerator_w = {17'd0, magnitude_w[31:0]};
    if (shift_w >= 0) numerator_w = numerator_w << shift_w;
    else numerator_w = numerator_w >> (-shift_w);
  end

  logic [3:0] high_digit_w, low_digit_w;
  logic [7:0] quotient_w;
  logic [32:0] high_product_w [0:7];
  logic [32:0] low_product_w [0:15];
  logic [32:0] quotient_product_w;
  logic [48:0] remainder_w;
  logic round_increment_w;
  logic [8:0] rounded_w;
  integer high_index;
  integer low_index;

  always_comb begin
    high_digit_w = 4'd0;
    for (high_index = 0; high_index < 8; high_index = high_index + 1) begin
      high_product_w[high_index] = denominator_q * 33'(high_index << 4);
      if (numerator_q >= {{16{1'b0}}, high_product_w[high_index]})
        high_digit_w = 4'(high_index);
    end
  end

  always_comb begin
    low_digit_w = 4'd0;
    for (low_index = 0; low_index < 16; low_index = low_index + 1) begin
      low_product_w[low_index] = denominator_q *
        (33'({high_digit_q, 4'd0}) + 33'(low_index));
      if (numerator_q >= {{16{1'b0}}, low_product_w[low_index]})
        low_digit_w = 4'(low_index);
    end
    quotient_w = {high_digit_q, low_digit_w};
    quotient_product_w = denominator_q * {1'b0, quotient_w};
    remainder_w = numerator_q - {{16{1'b0}}, quotient_product_w};
    round_increment_w = ((remainder_w << 1) > {25'd0, denominator_q}) ||
      (((remainder_w << 1) == {25'd0, denominator_q}) && quotient_w[0]);
    rounded_w = {1'b0, quotient_w} + {8'd0, round_increment_w};
  end

  logic [32:0] positive_cap_w, negative_cap_w;
  assign positive_cap_w = significand_w * 8'd127;
  assign negative_cap_w = significand_w * 9'd128;

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
      high_digit_q <= '0;
      result_q <= '0;
      invalid_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          negative_q <= value_q22_i[47];
          numerator_q <= numerator_w;
          denominator_q <= significand_w;
          result_q <= '0;
          invalid_q <= !scale_valid_w;
          if (!scale_valid_w || value_q22_i == 0) begin
            state_q <= RESPONSE;
          end else if (input_overflow_w) begin
            result_q <= value_q22_i[47] ? -8'sd128 : 8'sd127;
            state_q <= RESPONSE;
          end else if ((!value_q22_i[47] &&
                        numerator_w >= {{16{1'b0}}, positive_cap_w}) ||
                       (value_q22_i[47] &&
                        numerator_w >= {{16{1'b0}}, negative_cap_w})) begin
            result_q <= value_q22_i[47] ? -8'sd128 : 8'sd127;
            state_q <= RESPONSE;
          end else begin
            state_q <= HIGH_DIGIT;
          end
        end
        HIGH_DIGIT: begin
          high_digit_q <= high_digit_w;
          state_q <= LOW_DIGIT;
        end
        LOW_DIGIT: begin
          if (negative_q) begin
            if (rounded_w >= 9'd128) result_q <= -8'sd128;
            else result_q <= -$signed(rounded_w[7:0]);
          end else begin
            if (rounded_w > 9'd127) result_q <= 8'sd127;
            else result_q <= $signed(rounded_w[7:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
