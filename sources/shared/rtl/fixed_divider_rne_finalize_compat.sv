// SPDX-License-Identifier: Apache-2.0
// Candidate-local replacement for fixed_divider_rne.  Compile this file with
// fixed_divider_rne_finalize_pipeline.sv and omit fixed_divider_rne.sv.
module fixed_divider_rne #(
  parameter int NUM_WIDTH = 64,
  parameter int DEN_WIDTH = 48,
  parameter int OUT_WIDTH = 32,
  parameter int FRAC_BITS = 16
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [NUM_WIDTH-1:0] numerator_i,
  input logic [DEN_WIDTH-1:0] denominator_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [OUT_WIDTH-1:0] quotient_o,
  output logic divide_by_zero_o, output logic saturated_o
);
  fixed_divider_rne_finalize_pipeline #(
    .NUM_WIDTH(NUM_WIDTH), .DEN_WIDTH(DEN_WIDTH),
    .OUT_WIDTH(OUT_WIDTH), .FRAC_BITS(FRAC_BITS)
  ) u_pipeline (.*);
endmodule
