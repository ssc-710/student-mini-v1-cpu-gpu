// SPDX-License-Identifier: Apache-2.0
// Adds an explicit input register before the two-stage banked exp ROM.  This
// separates score/max delta arithmetic from ROM address generation without
// changing the LUT image, address rounding, or output bits.
module exp_neg_q15_sync_input_pipeline (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic               valid_i,
  input  logic signed [15:0] x_q11_i,
  output logic               valid_o,
  output logic        [15:0] exp_q15_o
);
  logic input_valid_q;
  logic signed [15:0] input_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      input_valid_q <= 1'b0;
      input_q <= '0;
    end else begin
      input_valid_q <= valid_i;
      if (valid_i) input_q <= x_q11_i;
    end
  end

  exp_neg_q15_sync_banked u_banked_rom (
    .clk_i, .rst_ni, .valid_i(input_valid_q), .x_q11_i(input_q),
    .valid_o, .exp_q15_o
  );
endmodule
