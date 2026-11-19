// SPDX-License-Identifier: Apache-2.0
// Unique P3 B3 top.  The unchanged B2 hierarchy is intentionally wrapped so
// the only candidate mechanism is the requantizer register cut.
module p3_b3_requant_finalize_litex_top #(
  parameter int MAX_HIDDEN = 256,
  parameter int MAX_INTERMEDIATE = 64,
  parameter bit PIPELINED_SILU = 1'b0,
  parameter bit PIPELINED_SCALE_QUANTIZE = 1'b0,
  parameter bit PIPELINED_COMBINED_SCALES = 1'b0,
  parameter bit PIPELINED_ACTIVATION_PRODUCT = 1'b0,
  parameter bit PIPELINED_ROW_BASE = 1'b0,
  parameter bit PIPELINED_WEIGHT_ROW_BASE = 1'b0,
  parameter bit PIPELINED_OUTPUT_ROW_BASE = 1'b0,
  parameter bit PIPELINED_ADDRESS_BASES = 1'b0,
  parameter bit PIPELINED_DISPATCHER_COUNTER = 1'b0,
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
  output logic tile_start_o, output logic weight_switch_o
);
  p3_b2_bf16_pipeline_litex_top #(
    .MAX_HIDDEN(MAX_HIDDEN), .MAX_INTERMEDIATE(MAX_INTERMEDIATE),
    .PIPELINED_SILU(PIPELINED_SILU),
    .PIPELINED_SCALE_QUANTIZE(PIPELINED_SCALE_QUANTIZE),
    .PIPELINED_COMBINED_SCALES(PIPELINED_COMBINED_SCALES),
    .PIPELINED_ACTIVATION_PRODUCT(PIPELINED_ACTIVATION_PRODUCT),
    .PIPELINED_ROW_BASE(PIPELINED_ROW_BASE),
    .PIPELINED_WEIGHT_ROW_BASE(PIPELINED_WEIGHT_ROW_BASE),
    .PIPELINED_OUTPUT_ROW_BASE(PIPELINED_OUTPUT_ROW_BASE),
    .PIPELINED_ADDRESS_BASES(PIPELINED_ADDRESS_BASES),
    .PIPELINED_DISPATCHER_COUNTER(PIPELINED_DISPATCHER_COUNTER),
    .PPA_SRAM_GUARD(PPA_SRAM_GUARD)
  ) u_candidate (.*);
endmodule
