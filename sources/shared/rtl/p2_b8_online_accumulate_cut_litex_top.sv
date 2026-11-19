// SPDX-License-Identifier: Apache-2.0
module p2_b8_online_accumulate_cut_litex_top #(
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit RADIX16_MERGE = 1'b0,
  parameter bit PPA_SRAM_GUARD = 1'b0,
  parameter bit TRACE_ONLY = 1'b0
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
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  p2_b6_merge_product_pipeline_litex_top #(
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX), .RADIX16_MERGE(RADIX16_MERGE),
    .PPA_SRAM_GUARD(PPA_SRAM_GUARD), .TRACE_ONLY(TRACE_ONLY)
  ) u_candidate (.*);
endmodule
