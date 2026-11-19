// SPDX-License-Identifier: Apache-2.0
// One descriptor/DMA front-end shared by the three numerical B0 operators.
// The dispatcher owns the external one-outstanding memory seam; only the
// opcode-selected operator can drive a request or consume a response.
module litex_p123_b1_p2_output_cut_top #(
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

  logic [2:0] ready;
  logic [2:0] req_valid;
  logic [2:0] req_write;
  logic [31:0] req_addr [0:2];
  logic [127:0] req_wdata [0:2];
  logic [15:0] req_wstrb [0:2];
  logic [2:0] req_ready;
  logic [2:0] local_rsp_valid;
  logic [2:0] local_rsp_ready;
  logic [7:0] local_status [0:2];
  logic [63:0] local_cycles [0:2];
  logic [2:0] dma_response_ready;
  logic [2:0] dma_response_valid;

  litex_accelerator_dispatcher u_dispatcher (
    .clk_i, .rst_ni, .cmd_valid_i, .cmd_ready_o, .cmd_opcode_i, .cmd_desc_addr_i,
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

  always_comb begin
    op_ready = 1'b0;
    dma_valid = 1'b0;
    dma_write = 1'b0;
    dma_addr = '0;
    dma_wdata = '0;
    dma_wstrb = '0;
    dma_rsp_ready = 1'b0;
    op_rsp_valid = 1'b0;
    op_rsp_status = 8'd1;
    op_rsp_cycles = '0;
    req_ready = '0;
    local_rsp_ready = '0;
    dma_response_valid = '0;
    unique case (op_opcode)
      3'd1: begin
        op_ready = ready[0];
        dma_valid = req_valid[0]; dma_write = req_write[0];
        dma_addr = req_addr[0]; dma_wdata = req_wdata[0]; dma_wstrb = req_wstrb[0];
        req_ready[0] = dma_ready; dma_response_valid[0] = dma_rsp_valid;
        dma_rsp_ready = dma_response_ready[0];
        op_rsp_valid = local_rsp_valid[0]; local_rsp_ready[0] = op_rsp_ready;
        op_rsp_status = local_status[0]; op_rsp_cycles = local_cycles[0];
      end
      3'd2: begin
        op_ready = ready[1];
        dma_valid = req_valid[1]; dma_write = req_write[1];
        dma_addr = req_addr[1]; dma_wdata = req_wdata[1]; dma_wstrb = req_wstrb[1];
        req_ready[1] = dma_ready; dma_response_valid[1] = dma_rsp_valid;
        dma_rsp_ready = dma_response_ready[1];
        op_rsp_valid = local_rsp_valid[1]; local_rsp_ready[1] = op_rsp_ready;
        op_rsp_status = local_status[1]; op_rsp_cycles = local_cycles[1];
      end
      3'd3: begin
        op_ready = ready[2];
        dma_valid = req_valid[2]; dma_write = req_write[2];
        dma_addr = req_addr[2]; dma_wdata = req_wdata[2]; dma_wstrb = req_wstrb[2];
        req_ready[2] = dma_ready; dma_response_valid[2] = dma_rsp_valid;
        dma_rsp_ready = dma_response_ready[2];
        op_rsp_valid = local_rsp_valid[2]; local_rsp_ready[2] = op_rsp_ready;
        op_rsp_status = local_status[2]; op_rsp_cycles = local_cycles[2];
      end
      default: begin end
    endcase
  end

  p1_dma_operator_b0 #(
    .HEADS(P1_HEADS), .NOPE_DIM(P1_NOPE_DIM), .ROPE_DIM(P1_ROPE_DIM),
    .INDEX_DIM(P1_INDEX_DIM), .VALUE_DIM(P1_VALUE_DIM), .K_MAX(P1_K_MAX),
    .PIPELINED_SOFTMAX(P1_PIPELINED_SOFTMAX)
  ) u_p1 (
    .clk_i, .rst_ni, .cmd_valid_i(op_valid && op_opcode == 3'd1),
    .cmd_ready_o(ready[0]), .descriptor_i(op_descriptor), .operator_arg_i(op_arg),
    .dma_req_valid_o(req_valid[0]), .dma_req_ready_i(req_ready[0]),
    .dma_req_write_o(req_write[0]), .dma_req_addr_o(req_addr[0]),
    .dma_req_wdata_o(req_wdata[0]), .dma_req_wstrb_o(req_wstrb[0]),
    .dma_rsp_valid_i(dma_response_valid[0]), .dma_rsp_ready_o(dma_response_ready[0]),
    .dma_rsp_rdata_i(dma_rdata), .dma_rsp_error_i(dma_rsp_error),
    .rsp_valid_o(local_rsp_valid[0]), .rsp_ready_i(local_rsp_ready[0]),
    .rsp_status_o(local_status[0]), .rsp_cycles_o(local_cycles[0])
  );

  p2_dma_operator_b1_output_cut #(.PIPELINED_SOFTMAX(P2_PIPELINED_SOFTMAX)) u_p2 (
    .clk_i, .rst_ni, .cmd_valid_i(op_valid && op_opcode == 3'd2),
    .cmd_ready_o(ready[1]), .descriptor_i(op_descriptor),
    .dma_req_valid_o(req_valid[1]), .dma_req_ready_i(req_ready[1]),
    .dma_req_write_o(req_write[1]), .dma_req_addr_o(req_addr[1]),
    .dma_req_wdata_o(req_wdata[1]), .dma_req_wstrb_o(req_wstrb[1]),
    .dma_rsp_valid_i(dma_response_valid[1]), .dma_rsp_ready_o(dma_response_ready[1]),
    .dma_rsp_rdata_i(dma_rdata), .dma_rsp_error_i(dma_rsp_error),
    .rsp_valid_o(local_rsp_valid[1]), .rsp_ready_i(local_rsp_ready[1]),
    .rsp_status_o(local_status[1]), .rsp_cycles_o(local_cycles[1])
  );

  p3_dma_operator_b0 #(
    .MAX_HIDDEN(P3_MAX_HIDDEN), .MAX_INTERMEDIATE(P3_MAX_INTERMEDIATE),
    .PIPELINED_SILU(P3_PIPELINED_SILU)
  ) u_p3 (
    .clk_i, .rst_ni, .cmd_valid_i(op_valid && op_opcode == 3'd3),
    .cmd_ready_o(ready[2]), .descriptor_i(op_descriptor),
    .dma_req_valid_o(req_valid[2]), .dma_req_ready_i(req_ready[2]),
    .dma_req_write_o(req_write[2]), .dma_req_addr_o(req_addr[2]),
    .dma_req_wdata_o(req_wdata[2]), .dma_req_wstrb_o(req_wstrb[2]),
    .dma_rsp_valid_i(dma_response_valid[2]), .dma_rsp_ready_o(dma_response_ready[2]),
    .dma_rsp_rdata_i(dma_rdata), .dma_rsp_error_i(dma_rsp_error),
    .rsp_valid_o(local_rsp_valid[2]), .rsp_ready_i(local_rsp_ready[2]),
    .rsp_status_o(local_status[2]), .rsp_cycles_o(local_cycles[2]),
    .tile_start_o(p3_tile_start_o), .weight_switch_o(p3_weight_switch_o)
  );
endmodule
