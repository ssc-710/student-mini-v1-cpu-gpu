// SPDX-License-Identifier: Apache-2.0
// Unified Nano integration top for timing-safe B0 through M1 candidates.
// Compile-time selectors change only the operator under evaluation; the other
// two operators remain at their accepted direct-parent implementations.  Each operator retains its independently
// verified descriptor/DMA shell; this router only grants the shared external
// memory seam to the opcode-selected command until its response is accepted.
module litex_p123_microarchitecture_top #(
  parameter int P1_HEADS = 4, parameter int P1_NOPE_DIM = 8,
  parameter int P1_ROPE_DIM = 4, parameter int P1_INDEX_DIM = 8,
  parameter int P1_VALUE_DIM = 8, parameter int P1_K_MAX = 32,
  parameter bit P1_PIPELINED_SOFTMAX = 1'b1,
  parameter bit P1_PIPELINED_SCORE_SCALE = 1'b1,
  parameter bit P2_PIPELINED_SOFTMAX = 1'b1,
  parameter bit P2_RADIX16_MERGE = 1'b0,
  parameter int P3_MAX_HIDDEN = 256,
  parameter int P3_MAX_INTERMEDIATE = 64,
  parameter bit P3_PIPELINED_SILU = 1'b1,
  parameter bit P3_PIPELINED_SCALE_QUANTIZE = 1'b1
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
  logic [1:0] active_q;
  logic [2:0] local_cmd_ready, local_req_valid, local_req_write;
  logic [31:0] local_req_addr [0:2];
  logic [127:0] local_req_wdata [0:2];
  logic [15:0] local_req_wstrb [0:2];
  logic [2:0] local_rsp_ready, local_rsp_valid, local_mem_rsp_ready;
  logic [7:0] local_status [0:2];
  logic [63:0] local_cycles [0:2];
  logic [63:0] unused_trace64 [0:3];
  logic [31:0] unused_trace32 [0:1];

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      active_q <= 2'd0;
    end else begin
      if (active_q == 0 && cmd_valid_i && cmd_ready_o)
        active_q <= cmd_opcode_i[1:0];
      else if (active_q != 0 && rsp_valid_o && rsp_ready_i)
        active_q <= 2'd0;
    end
  end

  always_comb begin
    cmd_ready_o = 1'b0;
    if (active_q == 0) begin
      case (cmd_opcode_i)
        3'd1: cmd_ready_o = local_cmd_ready[0];
        3'd2: cmd_ready_o = local_cmd_ready[1];
        3'd3: cmd_ready_o = local_cmd_ready[2];
        default: cmd_ready_o = 1'b0;
      endcase
    end
    mem_req_valid_o = 1'b0; mem_req_write_o = 1'b0;
    mem_req_addr_o = '0; mem_req_wdata_o = '0; mem_req_wstrb_o = '0;
    mem_rsp_ready_o = 1'b0; rsp_valid_o = 1'b0;
    rsp_status_o = 8'd1; rsp_cycles_o = '0;
    local_rsp_ready = '0;
    case (active_q)
      2'd1: begin
        mem_req_valid_o = local_req_valid[0]; mem_req_write_o = local_req_write[0];
        mem_req_addr_o = local_req_addr[0]; mem_req_wdata_o = local_req_wdata[0];
        mem_req_wstrb_o = local_req_wstrb[0]; mem_rsp_ready_o = local_mem_rsp_ready[0];
        rsp_valid_o = local_rsp_valid[0]; rsp_status_o = local_status[0];
        rsp_cycles_o = local_cycles[0]; local_rsp_ready[0] = rsp_ready_i;
      end
      2'd2: begin
        mem_req_valid_o = local_req_valid[1]; mem_req_write_o = local_req_write[1];
        mem_req_addr_o = local_req_addr[1]; mem_req_wdata_o = local_req_wdata[1];
        mem_req_wstrb_o = local_req_wstrb[1]; mem_rsp_ready_o = local_mem_rsp_ready[1];
        rsp_valid_o = local_rsp_valid[1]; rsp_status_o = local_status[1];
        rsp_cycles_o = local_cycles[1]; local_rsp_ready[1] = rsp_ready_i;
      end
      2'd3: begin
        mem_req_valid_o = local_req_valid[2]; mem_req_write_o = local_req_write[2];
        mem_req_addr_o = local_req_addr[2]; mem_req_wdata_o = local_req_wdata[2];
        mem_req_wstrb_o = local_req_wstrb[2]; mem_rsp_ready_o = local_mem_rsp_ready[2];
        rsp_valid_o = local_rsp_valid[2]; rsp_status_o = local_status[2];
        rsp_cycles_o = local_cycles[2]; local_rsp_ready[2] = rsp_ready_i;
      end
      default: begin end
    endcase
  end

  p1_b2_bf16_pipeline_litex_top #(
    .HEADS(P1_HEADS), .NOPE_DIM(P1_NOPE_DIM), .ROPE_DIM(P1_ROPE_DIM),
    .INDEX_DIM(P1_INDEX_DIM), .VALUE_DIM(P1_VALUE_DIM), .K_MAX(P1_K_MAX),
    .PIPELINED_SOFTMAX(1'b1), .PIPELINED_SCORE_SCALE(1'b1),
    .PIPELINED_PAGE_VALIDATE(1'b1)
  ) u_p1 (
    .clk_i, .rst_ni, .cmd_valid_i(cmd_valid_i && active_q == 0 && cmd_opcode_i == 3'd1),
    .cmd_ready_o(local_cmd_ready[0]), .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(local_req_valid[0]), .mem_req_ready_i(mem_req_ready_i && active_q == 1),
    .mem_req_write_o(local_req_write[0]), .mem_req_addr_o(local_req_addr[0]),
    .mem_req_wdata_o(local_req_wdata[0]), .mem_req_wstrb_o(local_req_wstrb[0]),
    .mem_rsp_valid_i(mem_rsp_valid_i && active_q == 1),
    .mem_rsp_ready_o(local_mem_rsp_ready[0]), .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(local_rsp_valid[0]), .rsp_ready_i(local_rsp_ready[0]),
    .rsp_status_o(local_status[0]), .rsp_cycles_o(local_cycles[0]),
    .trace_read_requests_o(unused_trace64[0]),
    .trace_write_requests_o(unused_trace64[1]),
    .trace_read_bytes_o(unused_trace64[2]), .trace_write_bytes_o(unused_trace64[3]),
    .trace_first_kv_address_o(unused_trace32[0]),
    .trace_last_kv_address_o(unused_trace32[1])
  );

`ifdef P2_M1_DMA_REUSE
`define P2_SELECTED_TOP p2_m1_dma_compute_overlap_litex_top
`else
`define P2_SELECTED_TOP p2_b8_online_accumulate_cut_litex_top
`endif
  `P2_SELECTED_TOP #(
    .PIPELINED_SOFTMAX(1'b1), .RADIX16_MERGE(P2_RADIX16_MERGE)
  ) u_p2 (
    .clk_i, .rst_ni, .cmd_valid_i(cmd_valid_i && active_q == 0 && cmd_opcode_i == 3'd2),
    .cmd_ready_o(local_cmd_ready[1]), .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(local_req_valid[1]), .mem_req_ready_i(mem_req_ready_i && active_q == 2),
    .mem_req_write_o(local_req_write[1]), .mem_req_addr_o(local_req_addr[1]),
    .mem_req_wdata_o(local_req_wdata[1]), .mem_req_wstrb_o(local_req_wstrb[1]),
    .mem_rsp_valid_i(mem_rsp_valid_i && active_q == 2),
    .mem_rsp_ready_o(local_mem_rsp_ready[1]), .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(local_rsp_valid[1]), .rsp_ready_i(local_rsp_ready[1]),
    .rsp_status_o(local_status[1]), .rsp_cycles_o(local_cycles[1])
  );
`undef P2_SELECTED_TOP

`ifdef P3_M1_WEIGHT_STATIONARY
  p3_m1_weight_stationary_litex_top #(
    .MAX_HIDDEN(P3_MAX_HIDDEN), .MAX_INTERMEDIATE(P3_MAX_INTERMEDIATE),
    .PIPELINED_SILU(1'b1), .PIPELINED_SCALE_QUANTIZE(1'b1)
  ) u_p3 (
    .clk_i, .rst_ni, .cmd_valid_i(cmd_valid_i && active_q == 0 && cmd_opcode_i == 3'd3),
    .cmd_ready_o(local_cmd_ready[2]), .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(local_req_valid[2]), .mem_req_ready_i(mem_req_ready_i && active_q == 3),
    .mem_req_write_o(local_req_write[2]), .mem_req_addr_o(local_req_addr[2]),
    .mem_req_wdata_o(local_req_wdata[2]), .mem_req_wstrb_o(local_req_wstrb[2]),
    .mem_rsp_valid_i(mem_rsp_valid_i && active_q == 3),
    .mem_rsp_ready_o(local_mem_rsp_ready[2]), .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(local_rsp_valid[2]), .rsp_ready_i(local_rsp_ready[2]),
    .rsp_status_o(local_status[2]), .rsp_cycles_o(local_cycles[2]),
    .tile_start_o(p3_tile_start_o), .weight_switch_o(p3_weight_switch_o)
  );
`elsif P3_EXPERT_GROUP_LINE_BUFFER
  p3_b13_weight_cache_litex_top #(
    .MAX_HIDDEN(P3_MAX_HIDDEN), .MAX_INTERMEDIATE(P3_MAX_INTERMEDIATE),
    .PIPELINED_SILU(1'b1), .PIPELINED_SCALE_QUANTIZE(1'b1)
  ) u_p3 (
    .clk_i, .rst_ni, .cmd_valid_i(cmd_valid_i && active_q == 0 && cmd_opcode_i == 3'd3),
    .cmd_ready_o(local_cmd_ready[2]), .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(local_req_valid[2]), .mem_req_ready_i(mem_req_ready_i && active_q == 3),
    .mem_req_write_o(local_req_write[2]), .mem_req_addr_o(local_req_addr[2]),
    .mem_req_wdata_o(local_req_wdata[2]), .mem_req_wstrb_o(local_req_wstrb[2]),
    .mem_rsp_valid_i(mem_rsp_valid_i && active_q == 3),
    .mem_rsp_ready_o(local_mem_rsp_ready[2]), .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(local_rsp_valid[2]), .rsp_ready_i(local_rsp_ready[2]),
    .rsp_status_o(local_status[2]), .rsp_cycles_o(local_cycles[2]),
    .tile_start_o(p3_tile_start_o), .weight_switch_o(p3_weight_switch_o)
  );
`else
  p3_b12_output_row_base_litex_top #(
    .MAX_HIDDEN(P3_MAX_HIDDEN), .MAX_INTERMEDIATE(P3_MAX_INTERMEDIATE),
    .PIPELINED_SILU(1'b1), .PIPELINED_SCALE_QUANTIZE(1'b1)
  ) u_p3 (
    .clk_i, .rst_ni, .cmd_valid_i(cmd_valid_i && active_q == 0 && cmd_opcode_i == 3'd3),
    .cmd_ready_o(local_cmd_ready[2]), .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(local_req_valid[2]), .mem_req_ready_i(mem_req_ready_i && active_q == 3),
    .mem_req_write_o(local_req_write[2]), .mem_req_addr_o(local_req_addr[2]),
    .mem_req_wdata_o(local_req_wdata[2]), .mem_req_wstrb_o(local_req_wstrb[2]),
    .mem_rsp_valid_i(mem_rsp_valid_i && active_q == 3),
    .mem_rsp_ready_o(local_mem_rsp_ready[2]), .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(local_rsp_valid[2]), .rsp_ready_i(local_rsp_ready[2]),
    .rsp_status_o(local_status[2]), .rsp_cycles_o(local_cycles[2]),
    .tile_start_o(p3_tile_start_o), .weight_switch_o(p3_weight_switch_o)
  );
`endif
endmodule


