// SPDX-License-Identifier: Apache-2.0
// B0 timing-foundation replacement for p1_dma_operator_b2_bf16_pipeline.
//
// The routed rtl-medium path ran from page_size_q through the page-token and
// byte-address arithmetic into dma_128_adapter.addr_q.  This compatibility
// wrapper retains every earlier B0 cut and enables the already bit-exact B14
// registered page-token boundary.  It does not expose a promotion mechanism.
module p1_dma_operator_b2_bf16_pipeline #(
  parameter int HEADS = 4,
  parameter int NOPE_DIM = 8,
  parameter int ROPE_DIM = 4,
  parameter int INDEX_DIM = 8,
  parameter int VALUE_DIM = 8,
  parameter int K_MAX = 32,
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit PIPELINED_SCORE_SCALE = 1'b0,
  parameter bit PIPELINED_PAGE_VALIDATE = 1'b0,
  parameter bit PIPELINED_META_LENGTH = 1'b0
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic cmd_valid_i,
  output logic cmd_ready_o,
  input  logic [511:0] descriptor_i,
  input  logic [7:0] operator_arg_i,

  output logic dma_req_valid_o,
  input  logic dma_req_ready_i,
  output logic dma_req_write_o,
  output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o,
  output logic [15:0] dma_req_wstrb_o,
  input  logic dma_rsp_valid_i,
  output logic dma_rsp_ready_o,
  input  logic [127:0] dma_rsp_rdata_i,
  input  logic dma_rsp_error_i,

  output logic rsp_valid_o,
  input  logic rsp_ready_i,
  output logic [7:0] rsp_status_o,
  output logic [63:0] rsp_cycles_o
);
  p1_dma_operator_b14_page_token_base_cut #(
    .HEADS(HEADS),
    .NOPE_DIM(NOPE_DIM),
    .ROPE_DIM(ROPE_DIM),
    .INDEX_DIM(INDEX_DIM),
    .VALUE_DIM(VALUE_DIM),
    .K_MAX(K_MAX),
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX),
    .PIPELINED_SCORE_SCALE(PIPELINED_SCORE_SCALE),
    .PIPELINED_PAGE_VALIDATE(1'b1),
    .PIPELINED_META_LENGTH(1'b1),
    .PIPELINED_VISIBLE(1'b1)
  ) u_page_token_base (.*);
endmodule
