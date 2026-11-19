// SPDX-License-Identifier: Apache-2.0
// Complete P1 command -> descriptor -> paged DMA -> numeric -> BF16 write seam.
module p1_b13_beat_width_litex_top #(
  parameter int HEADS = 4,
  parameter int NOPE_DIM = 8,
  parameter int ROPE_DIM = 4,
  parameter int INDEX_DIM = 8,
  parameter int VALUE_DIM = 8,
  parameter int K_MAX = 32,
  parameter bit PIPELINED_SOFTMAX = 1'b1,
  parameter bit PIPELINED_SCORE_SCALE = 1'b1,
  parameter bit PIPELINED_PAGE_VALIDATE = 1'b1,
  parameter bit PIPELINED_META_LENGTH = 1'b1,
  parameter bit PIPELINED_VISIBLE = 1'b1,
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
  logic op_valid, op_ready;
  logic [2:0] op_opcode;
  logic [511:0] op_descriptor;
  logic [7:0] op_arg;
  logic dma_valid, dma_ready, dma_write, dma_rsp_valid, dma_rsp_ready, dma_rsp_error;
  logic [31:0] dma_addr;
  logic [127:0] dma_wdata, dma_rdata;
  logic [15:0] dma_wstrb;
  logic op_rsp_valid, op_rsp_ready;
  logic [7:0] op_rsp_status;
  logic [63:0] op_rsp_cycles;
  logic dispatch_cmd_valid, dispatch_cmd_ready;
  logic [2:0] dispatch_cmd_opcode;
  logic [31:0] dispatch_cmd_desc_addr;

  generate
    if (PPA_SRAM_GUARD) begin : g_command_scratch
      ppa_sram_command_guard u_command_guard (
        .clk_i, .rst_ni, .cmd_valid_i, .cmd_ready_o, .cmd_opcode_i,
        .cmd_desc_addr_i, .guarded_valid_o(dispatch_cmd_valid),
        .guarded_ready_i(dispatch_cmd_ready),
        .guarded_opcode_o(dispatch_cmd_opcode),
        .guarded_desc_addr_o(dispatch_cmd_desc_addr)
      );
    end else begin : g_direct_command
      assign dispatch_cmd_valid = cmd_valid_i;
      assign cmd_ready_o = dispatch_cmd_ready;
      assign dispatch_cmd_opcode = cmd_opcode_i;
      assign dispatch_cmd_desc_addr = cmd_desc_addr_i;
    end
  endgenerate

  litex_accelerator_dispatcher u_dispatcher (
    .clk_i, .rst_ni, .cmd_valid_i(dispatch_cmd_valid),
    .cmd_ready_o(dispatch_cmd_ready), .cmd_opcode_i(dispatch_cmd_opcode),
    .cmd_desc_addr_i(dispatch_cmd_desc_addr),
    .mem_req_valid_o, .mem_req_ready_i, .mem_req_write_o, .mem_req_addr_o,
    .mem_req_wdata_o, .mem_req_wstrb_o, .mem_rsp_valid_i, .mem_rsp_ready_o,
    .mem_rsp_rdata_i, .mem_rsp_error_i,
    .op_valid_o(op_valid), .op_ready_i(op_ready), .op_opcode_o(op_opcode),
    .op_descriptor_o(op_descriptor), .op_operator_arg_o(op_arg),
    .op_dma_req_valid_i(dma_valid), .op_dma_req_ready_o(dma_ready),
    .op_dma_req_write_i(dma_write), .op_dma_req_addr_i(dma_addr),
    .op_dma_req_wdata_i(dma_wdata), .op_dma_req_wstrb_i(dma_wstrb),
    .op_dma_rsp_valid_o(dma_rsp_valid), .op_dma_rsp_ready_i(dma_rsp_ready),
    .op_dma_rsp_rdata_o(dma_rdata), .op_dma_rsp_error_o(dma_rsp_error),
    .op_rsp_valid_i(op_rsp_valid), .op_rsp_ready_o(op_rsp_ready),
    .op_rsp_status_i(op_rsp_status), .op_rsp_cycles_i(op_rsp_cycles),
    .rsp_valid_o, .rsp_ready_i, .rsp_status_o, .rsp_cycles_o
  );

  generate
    if (TRACE_ONLY) begin : g_trace
      p1_trace_operator_b0 #(
        .HEADS(HEADS), .Q_STRIDE(((NOPE_DIM + ROPE_DIM + INDEX_DIM + 15) / 16) * 16),
        .KV_STRIDE(((NOPE_DIM + ROPE_DIM + INDEX_DIM + 15) / 16) * 16),
        .VALUE_DIM(VALUE_DIM)
      ) u_p1_trace (
        .clk_i, .rst_ni, .cmd_valid_i(op_valid && op_opcode == 3'd1),
        .cmd_ready_o(op_ready), .descriptor_i(op_descriptor), .operator_arg_i(op_arg),
        .dma_req_valid_o(dma_valid), .dma_req_ready_i(dma_ready),
        .dma_req_write_o(dma_write), .dma_req_addr_o(dma_addr),
        .dma_req_wdata_o(dma_wdata), .dma_req_wstrb_o(dma_wstrb),
        .dma_rsp_valid_i(dma_rsp_valid), .dma_rsp_ready_o(dma_rsp_ready),
        .dma_rsp_rdata_i(dma_rdata), .dma_rsp_error_i(dma_rsp_error),
        .rsp_valid_o(op_rsp_valid), .rsp_ready_i(op_rsp_ready),
        .rsp_status_o(op_rsp_status), .rsp_cycles_o(op_rsp_cycles),
        .projected_read_requests_o(trace_read_requests_o),
        .projected_write_requests_o(trace_write_requests_o),
        .projected_read_bytes_o(trace_read_bytes_o),
        .projected_write_bytes_o(trace_write_bytes_o),
        .first_kv_address_o(trace_first_kv_address_o),
        .last_kv_address_o(trace_last_kv_address_o)
      );
    end else begin : g_numeric
      p1_dma_operator_b13_beat_width #(
        .HEADS(HEADS), .NOPE_DIM(NOPE_DIM), .ROPE_DIM(ROPE_DIM),
        .INDEX_DIM(INDEX_DIM), .VALUE_DIM(VALUE_DIM), .K_MAX(K_MAX),
        .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX),
        .PIPELINED_SCORE_SCALE(PIPELINED_SCORE_SCALE),
        .PIPELINED_PAGE_VALIDATE(PIPELINED_PAGE_VALIDATE),
        .PIPELINED_META_LENGTH(PIPELINED_META_LENGTH),
        .PIPELINED_VISIBLE(PIPELINED_VISIBLE)
      ) u_p1 (
        .clk_i, .rst_ni, .cmd_valid_i(op_valid && op_opcode == 3'd1),
        .cmd_ready_o(op_ready), .descriptor_i(op_descriptor), .operator_arg_i(op_arg),
        .dma_req_valid_o(dma_valid), .dma_req_ready_i(dma_ready),
        .dma_req_write_o(dma_write), .dma_req_addr_o(dma_addr),
        .dma_req_wdata_o(dma_wdata), .dma_req_wstrb_o(dma_wstrb),
        .dma_rsp_valid_i(dma_rsp_valid), .dma_rsp_ready_o(dma_rsp_ready),
        .dma_rsp_rdata_i(dma_rdata), .dma_rsp_error_i(dma_rsp_error),
        .rsp_valid_o(op_rsp_valid), .rsp_ready_i(op_rsp_ready),
        .rsp_status_o(op_rsp_status), .rsp_cycles_o(op_rsp_cycles)
      );
      assign trace_read_requests_o = '0;
      assign trace_write_requests_o = '0;
      assign trace_read_bytes_o = '0;
      assign trace_write_bytes_o = '0;
      assign trace_first_kv_address_o = '0;
      assign trace_last_kv_address_o = '0;
    end
  endgenerate
endmodule
