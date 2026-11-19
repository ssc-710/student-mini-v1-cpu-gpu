// SPDX-License-Identifier: Apache-2.0
// R1 compatibility seam: retain the B12/B2 serial DMA (and therefore no
// weight beat cache) while replacing only its expert datapath with the
// bit-exact registered down-product implementation.  The module name matches
// the B2 dependency deliberately; configs must compile this file instead of
// p3_expert_row_b2_bf16_pipeline.sv, never both.
module p3_expert_row_b2_bf16_pipeline #(
  parameter int MAX_HIDDEN = 256,
  parameter int MAX_INTERMEDIATE = 64,
  parameter bit PIPELINED_SILU = 1'b0,
  parameter bit PIPELINED_SCALE_QUANTIZE = 1'b0,
  parameter bit PIPELINED_COMBINED_SCALES = 1'b0,
  parameter bit PIPELINED_ACTIVATION_PRODUCT = 1'b0
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [15:0] hidden_i, input logic [15:0] intermediate_i,
  input logic [31:0] input_scale_i, input logic [31:0] gate_scale_i,
  input logic [31:0] up_scale_i, input logic [31:0] intermediate_scale_i,
  input logic [31:0] down_scale_i, input logic [31:0] route_weight_i,
  output logic data_req_valid_o, input logic data_req_ready_i,
  output logic data_req_down_o, output logic [15:0] data_req_hidden_o,
  output logic [15:0] data_req_intermediate_o,
  input logic data_rsp_valid_i, output logic data_rsp_ready_o,
  input logic signed [7:0] data_rsp_activation_i,
  input logic signed [7:0] data_rsp_gate_weight_i,
  input logic signed [7:0] data_rsp_up_weight_i,
  input logic signed [7:0] data_rsp_down_weight_i,
  input logic data_rsp_error_i,
  output logic output_valid_o, input logic output_ready_i,
  output logic [15:0] output_index_o, output logic [15:0] output_bf16_o,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  p3_expert_row_b16_down_product_cut #(
    .MAX_HIDDEN(MAX_HIDDEN),
    .MAX_INTERMEDIATE(MAX_INTERMEDIATE),
    .PIPELINED_SILU(PIPELINED_SILU),
    .PIPELINED_SCALE_QUANTIZE(PIPELINED_SCALE_QUANTIZE),
    .PIPELINED_COMBINED_SCALES(PIPELINED_COMBINED_SCALES),
    .PIPELINED_ACTIVATION_PRODUCT(PIPELINED_ACTIVATION_PRODUCT)
  ) u_down_requant_cuts (.*);
endmodule
