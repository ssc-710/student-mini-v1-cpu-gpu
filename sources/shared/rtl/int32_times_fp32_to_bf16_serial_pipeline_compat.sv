// SPDX-License-Identifier: Apache-2.0
// B0 timing-foundation compatibility seam.  Preserve the parallel formatter
// module interface while replacing its 16x24 product cone with the existing
// bit-exact one-bit-per-cycle multiply/normalize implementation.
module int32_times_fp32_to_bf16_pipeline (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [31:0] value_i,
  input logic [31:0] scale_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [15:0] bf16_o,
  output logic invalid_scale_o
);
  int32_times_fp32_to_bf16_serial u_serial (.*);
endmodule
