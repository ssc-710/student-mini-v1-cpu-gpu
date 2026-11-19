// SPDX-License-Identifier: Apache-2.0
// Candidate-local compatibility name for the unchanged P1/P2/P3 unified top.
// Compile this file instead of p2_dma_operator_b3_product_pipeline.sv.
module p2_dma_operator_b3_product_pipeline #(
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit RADIX16_MERGE = 1'b0
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [511:0] descriptor_i,
  output logic dma_req_valid_o, input logic dma_req_ready_i,
  output logic dma_req_write_o, output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o, output logic [15:0] dma_req_wstrb_o,
  input logic dma_rsp_valid_i, output logic dma_rsp_ready_o,
  input logic [127:0] dma_rsp_rdata_i, input logic dma_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  p2_dma_operator_b4_divider_finalize #(
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX), .RADIX16_MERGE(RADIX16_MERGE)
  ) u_candidate (.*);
endmodule
