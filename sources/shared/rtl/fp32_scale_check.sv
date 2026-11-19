// SPDX-License-Identifier: Apache-2.0
// Positive, finite FP32 scale validator for the frozen [2^-16, 2^16] contract.
module fp32_scale_check (
  input  logic [31:0] scale_i,
  output logic        valid_o
);
  localparam logic [31:0] SCALE_MIN = 32'h3780_0000; // 2^-16
  localparam logic [31:0] SCALE_MAX = 32'h4780_0000; // 2^16

  always_comb begin
    valid_o = !scale_i[31] &&
              (scale_i[30:23] != 8'hff) &&
              (scale_i >= SCALE_MIN) &&
              (scale_i <= SCALE_MAX);
  end
endmodule
