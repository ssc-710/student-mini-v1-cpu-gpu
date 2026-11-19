// SPDX-License-Identifier: Apache-2.0
// Trace-profile counterpart of the P3 M1 DMA-boundary reuse block.
module p3_m1_weight_stationary_trace_top #(
  parameter bit TRACE_DOWN = 1'b0,
  parameter bit PPA_SRAM_GUARD = 1'b0
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
  output logic [63:0] trace_mac_count_o,
  output logic [31:0] trace_weight_switches_o,
  output logic [31:0] trace_first_weight_address_o, trace_last_weight_address_o
);
  logic a1_req_valid, a1_req_ready, a1_req_write;
  logic [31:0] a1_req_addr;
  logic [127:0] a1_req_wdata;
  logic [15:0] a1_req_wstrb;
  logic a1_rsp_valid, a1_rsp_ready, a1_rsp_error;
  logic [127:0] a1_rsp_rdata;

  p3_trace_litex_b0_top #(.TRACE_DOWN(TRACE_DOWN), .PPA_SRAM_GUARD(PPA_SRAM_GUARD)) u_a1 (
    .clk_i, .rst_ni, .cmd_valid_i, .cmd_ready_o, .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(a1_req_valid), .mem_req_ready_i(a1_req_ready),
    .mem_req_write_o(a1_req_write), .mem_req_addr_o(a1_req_addr),
    .mem_req_wdata_o(a1_req_wdata), .mem_req_wstrb_o(a1_req_wstrb),
    .mem_rsp_valid_i(a1_rsp_valid), .mem_rsp_ready_o(a1_rsp_ready),
    .mem_rsp_rdata_i(a1_rsp_rdata), .mem_rsp_error_i(a1_rsp_error),
    .rsp_valid_o, .rsp_ready_i, .rsp_status_o, .rsp_cycles_o,
    .trace_read_requests_o, .trace_write_requests_o, .trace_read_bytes_o,
    .trace_write_bytes_o, .trace_mac_count_o, .trace_weight_switches_o,
    .trace_first_weight_address_o, .trace_last_weight_address_o
  );

  dma_128_read_reuse_buffer #(.SET_BITS(2), .WAYS(4)) u_weight_block (
    .clk_i, .rst_ni, .flush_i(cmd_valid_i && cmd_ready_o),
    .client_req_valid_i(a1_req_valid), .client_req_ready_o(a1_req_ready),
    .client_req_write_i(a1_req_write), .client_req_addr_i(a1_req_addr),
    .client_req_wdata_i(a1_req_wdata), .client_req_wstrb_i(a1_req_wstrb),
    .client_rsp_valid_o(a1_rsp_valid), .client_rsp_ready_i(a1_rsp_ready),
    .client_rsp_rdata_o(a1_rsp_rdata), .client_rsp_error_o(a1_rsp_error),
    .dma_req_valid_o(mem_req_valid_o), .dma_req_ready_i(mem_req_ready_i),
    .dma_req_write_o(mem_req_write_o), .dma_req_addr_o(mem_req_addr_o),
    .dma_req_wdata_o(mem_req_wdata_o), .dma_req_wstrb_o(mem_req_wstrb_o),
    .dma_rsp_valid_i(mem_rsp_valid_i), .dma_rsp_ready_o(mem_rsp_ready_o),
    .dma_rsp_rdata_i(mem_rsp_rdata_i), .dma_rsp_error_i(mem_rsp_error_i)
  );
endmodule
