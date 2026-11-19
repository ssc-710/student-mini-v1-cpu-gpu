// SPDX-License-Identifier: Apache-2.0
// Exact integer times positive normal FP32, rounded directly to BF16 RNE.
module int32_times_fp32_to_bf16 (
  input  logic signed [31:0] value_i,
  input  logic        [31:0] scale_i,
  output logic        [15:0] bf16_o,
  output logic               invalid_scale_o
);
  logic [31:0] magnitude;
  logic [23:0] significand;
  logic [55:0] product;
  logic [8:0] retained;
  logic guard, sticky;
  integer msb, index, shift, exponent;

  always_comb begin
    invalid_scale_o = scale_i[31] || scale_i[30:23] == 0 ||
                      scale_i[30:23] == 8'hff;
    magnitude = value_i[31] ? (~value_i + 1'b1) : value_i;
    significand = {1'b1, scale_i[22:0]};
    product = magnitude * significand;
    bf16_o = 16'd0; retained = '0; guard = 1'b0; sticky = 1'b0;
    msb = -1; shift = 0; exponent = 0;
    for (index = 55; index >= 0; index = index - 1)
      if ((msb < 0) && product[index]) msb = index;
    if (!invalid_scale_o && (magnitude != 0)) begin
      shift = msb - 7;
      if (shift >= 0) retained = {1'b0, 8'(product >> shift)};
      else retained = {1'b0, 8'(product << (-shift))};
      if (shift > 0) begin
        guard = product[shift-1];
        // Constant loop bound keeps synthesis/formal frontends happy; the
        // runtime condition selects only bits below the guard bit.
        for (index = 0; index < 55; index = index + 1)
          if (index < shift-1) sticky = sticky | product[index];
      end
      retained = retained + (guard && (sticky || retained[0]));
      exponent = {24'd0, scale_i[30:23]} - 23 + msb;
      if (retained[8]) begin
        retained = retained >> 1;
        exponent = exponent + 1;
      end
      if (exponent <= 0 || exponent >= 255) begin
        invalid_scale_o = 1'b1;
        bf16_o = {value_i[31], 8'hfe, 7'h7f};
      end else bf16_o = {value_i[31], exponent[7:0], retained[6:0]};
    end
  end
endmodule
