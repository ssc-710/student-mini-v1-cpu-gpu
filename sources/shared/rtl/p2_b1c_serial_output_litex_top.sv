// SPDX-License-Identifier: Apache-2.0
// Complete P2 command -> descriptor -> DMA -> numeric core -> BF16 write seam.
module p2_b1c_serial_output_litex_top #(
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
  logic op_valid, op_ready;
  logic [2:0] op_opcode;
  logic [511:0] op_descriptor;
  logic [7:0] op_arg;
  logic op_dma_req_valid, op_dma_req_ready, op_dma_req_write;
  logic [31:0] op_dma_req_addr;
  logic [127:0] op_dma_req_wdata;
  logic [15:0] op_dma_req_wstrb;
  logic op_dma_rsp_valid, op_dma_rsp_ready, op_dma_rsp_error;
  logic [127:0] op_dma_rsp_rdata;
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
    .op_dma_req_valid_i(op_dma_req_valid), .op_dma_req_ready_o(op_dma_req_ready),
    .op_dma_req_write_i(op_dma_req_write), .op_dma_req_addr_i(op_dma_req_addr),
    .op_dma_req_wdata_i(op_dma_req_wdata), .op_dma_req_wstrb_i(op_dma_req_wstrb),
    .op_dma_rsp_valid_o(op_dma_rsp_valid), .op_dma_rsp_ready_i(op_dma_rsp_ready),
    .op_dma_rsp_rdata_o(op_dma_rsp_rdata), .op_dma_rsp_error_o(op_dma_rsp_error),
    .op_rsp_valid_i(op_rsp_valid), .op_rsp_ready_o(op_rsp_ready),
    .op_rsp_status_i(op_rsp_status), .op_rsp_cycles_i(op_rsp_cycles),
    .rsp_valid_o, .rsp_ready_i, .rsp_status_o, .rsp_cycles_o
  );

  generate
    if (TRACE_ONLY) begin : g_trace
      p2_trace_operator_b0 u_p2_trace (
        .clk_i, .rst_ni,
        .cmd_valid_i(op_valid && op_opcode == 3'd2), .cmd_ready_o(op_ready),
        .descriptor_i(op_descriptor),
        .dma_req_valid_o(op_dma_req_valid), .dma_req_ready_i(op_dma_req_ready),
        .dma_req_write_o(op_dma_req_write), .dma_req_addr_o(op_dma_req_addr),
        .dma_req_wdata_o(op_dma_req_wdata), .dma_req_wstrb_o(op_dma_req_wstrb),
        .dma_rsp_valid_i(op_dma_rsp_valid), .dma_rsp_ready_o(op_dma_rsp_ready),
        .dma_rsp_rdata_i(op_dma_rsp_rdata), .dma_rsp_error_i(op_dma_rsp_error),
        .rsp_valid_o(op_rsp_valid), .rsp_ready_i(op_rsp_ready),
        .rsp_status_o(op_rsp_status), .rsp_cycles_o(op_rsp_cycles)
      );
    end else begin : g_numeric
      p2_dma_operator_b1c_serial_output #(
        .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX),
        .RADIX16_MERGE(RADIX16_MERGE)
      ) u_p2 (
        .clk_i, .rst_ni,
        .cmd_valid_i(op_valid && op_opcode == 3'd2), .cmd_ready_o(op_ready),
        .descriptor_i(op_descriptor),
        .dma_req_valid_o(op_dma_req_valid), .dma_req_ready_i(op_dma_req_ready),
        .dma_req_write_o(op_dma_req_write), .dma_req_addr_o(op_dma_req_addr),
        .dma_req_wdata_o(op_dma_req_wdata), .dma_req_wstrb_o(op_dma_req_wstrb),
        .dma_rsp_valid_i(op_dma_rsp_valid), .dma_rsp_ready_o(op_dma_rsp_ready),
        .dma_rsp_rdata_i(op_dma_rsp_rdata), .dma_rsp_error_i(op_dma_rsp_error),
        .rsp_valid_o(op_rsp_valid), .rsp_ready_i(op_rsp_ready),
        .rsp_status_o(op_rsp_status), .rsp_cycles_o(op_rsp_cycles)
      );
    end
  endgenerate

  logic unused;
  assign unused = ^op_arg;
endmodule
