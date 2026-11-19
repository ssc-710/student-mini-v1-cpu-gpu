// SPDX-License-Identifier: Apache-2.0
module online_softmax_step_sync_product_pipeline (
  input logic clk_i, input logic rst_ni,
  input logic req_valid_i, output logic req_ready_o,
  input logic state_valid_i, input logic signed [15:0] maximum_q11_i,
  input logic [47:0] denominator_q15_i,
  input logic signed [63:0] weighted_q15_i,
  input logic signed [15:0] score_q11_i, input logic signed [7:0] value_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic state_valid_o, output logic signed [15:0] maximum_q11_o,
  output logic [47:0] denominator_q15_o,
  output logic signed [63:0] weighted_q15_o
);
  online_softmax_step_sync_radix4_serial_accum_pipeline u_pipeline (.*);
endmodule
