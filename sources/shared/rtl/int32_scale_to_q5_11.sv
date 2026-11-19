// SPDX-License-Identifier: Apache-2.0
// Exact integer interpretation of an FP32 scale followed by RNE and Q5.11
// saturation. The input scale is validated against the project contract.
module int32_scale_to_q5_11 #(
  parameter bit REQUIRE_PROJECT_SCALE_RANGE = 1'b1
) (
  input  logic signed [31:0] value_i,
  input  logic        [31:0] scale_i,
  output logic signed [15:0] q5_11_o,
  output logic               scale_valid_o
);
  logic [7:0] exponent;
  logic [23:0] significand;
  logic [31:0] magnitude;
  logic [55:0] product;
  logic [95:0] extended;
  logic [95:0] quotient;
  logic [95:0] remainder;
  logic [95:0] half;
  logic [95:0] rounded_magnitude;
  integer shift;
  integer right_shift;

  logic contract_scale_valid;
  fp32_scale_check u_scale_check (.scale_i(scale_i), .valid_o(contract_scale_valid));
  assign scale_valid_o = REQUIRE_PROJECT_SCALE_RANGE ? contract_scale_valid :
                         (!scale_i[31] && scale_i[30:23] != 0 &&
                          scale_i[30:23] != 8'hff);

  always_comb begin
    exponent = scale_i[30:23];
    significand = {1'b1, scale_i[22:0]};
    magnitude = value_i[31] ? (~value_i + 1'b1) : value_i;
    product = magnitude * significand;
    // value * significand * 2^(exponent-127-23) * 2^11
    shift = {24'd0, exponent};
    shift = shift - 139;
    right_shift = 0;
    extended = {{40{1'b0}}, product};
    quotient = '0;
    remainder = '0;
    half = '0;
    rounded_magnitude = '0;
    q5_11_o = '0;

    if (!scale_valid_o || value_i == 0) begin
      rounded_magnitude = '0;
    end else if (shift >= 0) begin
      rounded_magnitude = extended << shift;
    end else begin
      right_shift = -shift;
      quotient = extended >> right_shift;
      remainder = extended - (quotient << right_shift);
      half = 96'd1 << (right_shift - 1);
      rounded_magnitude = quotient;
      if ((remainder > half) || ((remainder == half) && quotient[0]))
        rounded_magnitude = quotient + 1'b1;
    end

    if (!scale_valid_o) q5_11_o = '0;
    else if (value_i[31]) begin
      if (rounded_magnitude >= 96'd32768) q5_11_o = -16'sd32768;
      else q5_11_o = -$signed(rounded_magnitude[15:0]);
    end else begin
      if (rounded_magnitude >= 96'd32767) q5_11_o = 16'sd32767;
      else q5_11_o = $signed(rounded_magnitude[15:0]);
    end
  end
endmodule
