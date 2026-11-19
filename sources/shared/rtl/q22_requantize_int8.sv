// SPDX-License-Identifier: Apache-2.0
// Convert signed Q10.22 to INT8 using a positive normal FP32 divisor.
// Division is RNE ties-to-even, followed by signed INT8 saturation.
module q22_requantize_int8 (
  input  logic signed [47:0] value_q22_i,
  input  logic        [31:0] scale_i,
  output logic signed  [7:0] value_i8_o,
  output logic               invalid_scale_o
);
  logic [7:0] exponent;
  logic [23:0] significand;
  logic [47:0] magnitude;
  logic [80:0] numerator;
  logic [80:0] quotient, remainder;
  logic [80:0] rounded;
  logic [80:0] significand_wide;
  integer shift;

  always_comb begin
    exponent = scale_i[30:23];
    significand = {1'b1, scale_i[22:0]};
    invalid_scale_o = scale_i[31] || exponent == 0 || exponent == 8'hff ||
                      (scale_i < 32'h37800000) || (scale_i > 32'h47800000);
    magnitude = value_q22_i[47] ? (~value_q22_i + 1'b1) : value_q22_i;
    significand_wide = {{57{1'b0}}, significand};
    numerator = '0; quotient = '0; remainder = '0; rounded = '0;
    value_i8_o = '0;
    shift = 128 - {24'd0, exponent};
    if (!invalid_scale_o) begin
      if (shift >= 0) numerator = {{33{1'b0}}, magnitude} << shift;
      else numerator = {{33{1'b0}}, magnitude} >> (-shift);
      quotient = numerator / significand_wide;
      remainder = numerator % significand_wide;
      rounded = quotient + (((remainder << 1) > significand_wide) ||
                            (((remainder << 1) == significand_wide) && quotient[0]));
      if (!value_q22_i[47]) begin
        if (rounded > 127) value_i8_o = 8'sd127;
        else value_i8_o = $signed(rounded[7:0]);
      end else begin
        if (rounded >= 128) value_i8_o = -8'sd128;
        else value_i8_o = -$signed(rounded[7:0]);
      end
    end
  end
endmodule
