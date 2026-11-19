// SPDX-License-Identifier: Apache-2.0
// Candidate-local name-compatible replacement for int8_dot_serial.
module int8_dot_serial (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [15:0] length_i,
  input logic in_valid_i, output logic in_ready_o,
  input logic signed [7:0] lhs_i, input logic signed [7:0] rhs_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [31:0] result_o, output logic length_error_o
);
  int8_dot_serial_operand_product_pipeline u_pipeline (.*);
endmodule
