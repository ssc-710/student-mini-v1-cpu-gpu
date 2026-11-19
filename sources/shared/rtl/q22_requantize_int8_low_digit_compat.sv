// SPDX-License-Identifier: Apache-2.0
// Candidate-local compatibility wrapper for the B10 low-digit register cut.
module q22_requantize_int8_radix16 (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [47:0] value_q22_i, input logic [31:0] scale_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [7:0] value_i8_o, output logic invalid_scale_o
);
  q22_requantize_int8_finalize_pipeline #(.PIPELINED_LOW_DIGIT(1'b1))
    u_pipeline (.*);
endmodule
