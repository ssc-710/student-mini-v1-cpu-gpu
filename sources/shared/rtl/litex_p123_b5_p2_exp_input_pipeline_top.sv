// SPDX-License-Identifier: Apache-2.0
// Unique unified nano top for P2 B5.  The candidate-local exp compatibility
// module inserts exactly one register before the banked exponential ROM while
// preserving the P2 B4 divider-finalization cut and all P1/P3 logic.
module litex_p123_b5_p2_exp_input_pipeline_top #(
  parameter int P1_HEADS = 4,
  parameter int P1_NOPE_DIM = 8,
  parameter int P1_ROPE_DIM = 4,
  parameter int P1_INDEX_DIM = 8,
  parameter int P1_VALUE_DIM = 8,
  parameter int P1_K_MAX = 32,
  parameter bit P1_PIPELINED_SOFTMAX = 1'b0,
  parameter bit P1_PIPELINED_SCORE_SCALE = 1'b0,
  parameter bit P2_PIPELINED_SOFTMAX = 1'b0,
  parameter bit P2_RADIX16_MERGE = 1'b0,
  parameter int P3_MAX_HIDDEN = 256,
  parameter int P3_MAX_INTERMEDIATE = 64,
  parameter bit P3_PIPELINED_SILU = 1'b0,
  parameter bit P3_PIPELINED_SCALE_QUANTIZE = 1'b0
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [2:0] cmd_opcode_i, input logic [31:0] cmd_desc_addr_i,
  output logic mem_req_valid_o, input logic mem_req_ready_i,
  output logic mem_req_write_o, output logic [31:0] mem_req_addr_o,
  output logic [127:0] mem_req_wdata_o, output logic [15:0] mem_req_wstrb_o,
  input logic mem_rsp_valid_i, output logic mem_rsp_ready_o,
  input logic [127:0] mem_rsp_rdata_i, input logic mem_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o,
  output logic p3_tile_start_o, output logic p3_weight_switch_o
);
  litex_p123_b4_p2_divider_finalize_top #(
    .P1_HEADS(P1_HEADS), .P1_NOPE_DIM(P1_NOPE_DIM),
    .P1_ROPE_DIM(P1_ROPE_DIM), .P1_INDEX_DIM(P1_INDEX_DIM),
    .P1_VALUE_DIM(P1_VALUE_DIM), .P1_K_MAX(P1_K_MAX),
    .P1_PIPELINED_SOFTMAX(P1_PIPELINED_SOFTMAX),
    .P1_PIPELINED_SCORE_SCALE(P1_PIPELINED_SCORE_SCALE),
    .P2_PIPELINED_SOFTMAX(P2_PIPELINED_SOFTMAX),
    .P2_RADIX16_MERGE(P2_RADIX16_MERGE),
    .P3_MAX_HIDDEN(P3_MAX_HIDDEN),
    .P3_MAX_INTERMEDIATE(P3_MAX_INTERMEDIATE),
    .P3_PIPELINED_SILU(P3_PIPELINED_SILU),
    .P3_PIPELINED_SCALE_QUANTIZE(P3_PIPELINED_SCALE_QUANTIZE)
  ) u_candidate (.*);
endmodule
