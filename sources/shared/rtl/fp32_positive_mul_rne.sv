// SPDX-License-Identifier: Apache-2.0
// RNE multiplier for finite, non-negative, normal binary32 values.  The
// project scale contract ([2^-16,2^16]) keeps both operands normal; zero is
// additionally accepted for route_weight.
module fp32_positive_mul_rne (
  input  logic [31:0] a_i,
  input  logic [31:0] b_i,
  output logic [31:0] product_o,
  output logic        invalid_o
);
  logic [7:0] a_exp, b_exp;
  logic [22:0] a_frac, b_frac;
  logic [47:0] raw;
  logic [24:0] rounded;
  logic [23:0] kept;
  logic guard, sticky;
  integer exponent;

  always_comb begin
    a_exp = a_i[30:23]; b_exp = b_i[30:23];
    a_frac = a_i[22:0]; b_frac = b_i[22:0];
    product_o = 32'd0;
    invalid_o = a_i[31] || b_i[31] ||
                (a_exp == 8'hff) || (b_exp == 8'hff) ||
                ((a_exp == 0) && (a_frac != 0)) ||
                ((b_exp == 0) && (b_frac != 0));
    raw = 48'd0; rounded = 25'd0; kept = 24'd0;
    guard = 1'b0; sticky = 1'b0; exponent = 0;
    if (!invalid_o && (a_exp != 0) && (b_exp != 0)) begin
      raw = {1'b1, a_frac} * {1'b1, b_frac};
      if (raw[47]) begin
        kept = raw[47:24]; guard = raw[23]; sticky = |raw[22:0];
        exponent = {24'd0, a_exp} + {24'd0, b_exp} - 126;
      end else begin
        kept = raw[46:23]; guard = raw[22]; sticky = |raw[21:0];
        exponent = {24'd0, a_exp} + {24'd0, b_exp} - 127;
      end
      rounded = {1'b0, kept} + (guard && (sticky || kept[0]));
      if (rounded[24]) begin
        kept = rounded[24:1]; exponent = exponent + 1;
      end else kept = rounded[23:0];
      if (exponent >= 255) begin
        product_o = 32'h7f7fffff;
        invalid_o = 1'b1;
      end else if (exponent <= 0) begin
        product_o = 32'd0;
        invalid_o = 1'b1;
      end else product_o = {1'b0, exponent[7:0], kept[22:0]};
    end
  end
endmodule
