// SPDX-License-Identifier: Apache-2.0
// P1 B6 retains B5's score, divider, BF16 and exp-input cuts.  The
// candidate-local online-softmax compatibility module adds only the
// measured product-to-RNE accumulator register cut.
module p1_b6_online_accumulate_cut_litex_top #(
  parameter int HEADS = 4,
  parameter int NOPE_DIM = 8,
  parameter int ROPE_DIM = 4,
  parameter int INDEX_DIM = 8,
  parameter int VALUE_DIM = 8,
  parameter int K_MAX = 32,
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit PIPELINED_SCORE_SCALE = 1'b0,
  parameter bit PIPELINED_PAGE_VALIDATE = 1'b0,
  parameter bit PIPELINED_META_LENGTH = 1'b0,
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
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o,
  output logic [63:0] trace_read_requests_o, trace_write_requests_o,
  output logic [63:0] trace_read_bytes_o, trace_write_bytes_o,
  output logic [31:0] trace_first_kv_address_o, trace_last_kv_address_o
);
  p1_b5_exp_input_pipeline_litex_top #(
    .HEADS(HEADS), .NOPE_DIM(NOPE_DIM), .ROPE_DIM(ROPE_DIM),
    .INDEX_DIM(INDEX_DIM), .VALUE_DIM(VALUE_DIM), .K_MAX(K_MAX),
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX),
    .PIPELINED_SCORE_SCALE(PIPELINED_SCORE_SCALE),
    .PIPELINED_PAGE_VALIDATE(PIPELINED_PAGE_VALIDATE),
    .PIPELINED_META_LENGTH(PIPELINED_META_LENGTH),
    .PPA_SRAM_GUARD(PPA_SRAM_GUARD), .TRACE_ONLY(TRACE_ONLY)
  ) u_candidate (.*);
endmodule
