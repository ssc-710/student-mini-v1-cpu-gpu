// SPDX-License-Identifier: Apache-2.0
// Timing-equivalent dispatcher wrapper.  The base dispatcher's cycle output
// is intentionally left unconsumed so synthesis can remove its 16-bit limb
// counters.  Eight 8-bit limbs reproduce the exact 64-bit service-cycle
// count with a shorter per-cycle carry path.
module litex_accelerator_dispatcher_counter8 (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [2:0] cmd_opcode_i, input logic [31:0] cmd_desc_addr_i,
  output logic mem_req_valid_o, input logic mem_req_ready_i,
  output logic mem_req_write_o, output logic [31:0] mem_req_addr_o,
  output logic [127:0] mem_req_wdata_o, output logic [15:0] mem_req_wstrb_o,
  input logic mem_rsp_valid_i, output logic mem_rsp_ready_o,
  input logic [127:0] mem_rsp_rdata_i, input logic mem_rsp_error_i,
  output logic op_valid_o, input logic op_ready_i,
  output logic [2:0] op_opcode_o, output logic [511:0] op_descriptor_o,
  output logic [7:0] op_operator_arg_o,
  input logic op_dma_req_valid_i, output logic op_dma_req_ready_o,
  input logic op_dma_req_write_i, input logic [31:0] op_dma_req_addr_i,
  input logic [127:0] op_dma_req_wdata_i, input logic [15:0] op_dma_req_wstrb_i,
  output logic op_dma_rsp_valid_o, input logic op_dma_rsp_ready_i,
  output logic [127:0] op_dma_rsp_rdata_o, output logic op_dma_rsp_error_o,
  input logic op_rsp_valid_i, output logic op_rsp_ready_o,
  input logic [7:0] op_rsp_status_i, input logic [63:0] op_rsp_cycles_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  logic [63:0] unused_base_cycles;
  logic active_q;
  logic [7:0] cycle_q [0:7];

  litex_accelerator_dispatcher u_base (
    .clk_i, .rst_ni, .cmd_valid_i, .cmd_ready_o, .cmd_opcode_i,
    .cmd_desc_addr_i, .mem_req_valid_o, .mem_req_ready_i, .mem_req_write_o,
    .mem_req_addr_o, .mem_req_wdata_o, .mem_req_wstrb_o, .mem_rsp_valid_i,
    .mem_rsp_ready_o, .mem_rsp_rdata_i, .mem_rsp_error_i, .op_valid_o,
    .op_ready_i, .op_opcode_o, .op_descriptor_o, .op_operator_arg_o,
    .op_dma_req_valid_i, .op_dma_req_ready_o, .op_dma_req_write_i,
    .op_dma_req_addr_i, .op_dma_req_wdata_i, .op_dma_req_wstrb_i,
    .op_dma_rsp_valid_o, .op_dma_rsp_ready_i, .op_dma_rsp_rdata_o,
    .op_dma_rsp_error_o, .op_rsp_valid_i, .op_rsp_ready_o, .op_rsp_status_i,
    .op_rsp_cycles_i, .rsp_valid_o, .rsp_ready_i, .rsp_status_o,
    .rsp_cycles_o(unused_base_cycles)
  );

  assign rsp_cycles_o = {
    cycle_q[7], cycle_q[6], cycle_q[5], cycle_q[4],
    cycle_q[3], cycle_q[2], cycle_q[1], cycle_q[0]
  };

  integer limb;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      active_q <= 1'b0;
      for (limb = 0; limb < 8; limb = limb + 1) cycle_q[limb] <= '0;
    end else begin
      if (cmd_valid_i && cmd_ready_o) begin
        active_q <= 1'b1;
        for (limb = 0; limb < 8; limb = limb + 1) cycle_q[limb] <= '0;
      end else if (active_q && !rsp_valid_o) begin
        cycle_q[0] <= cycle_q[0] + 1'b1;
        if (&cycle_q[0]) begin
          cycle_q[1] <= cycle_q[1] + 1'b1;
          if (&cycle_q[1]) begin
            cycle_q[2] <= cycle_q[2] + 1'b1;
            if (&cycle_q[2]) begin
              cycle_q[3] <= cycle_q[3] + 1'b1;
              if (&cycle_q[3]) begin
                cycle_q[4] <= cycle_q[4] + 1'b1;
                if (&cycle_q[4]) begin
                  cycle_q[5] <= cycle_q[5] + 1'b1;
                  if (&cycle_q[5]) begin
                    cycle_q[6] <= cycle_q[6] + 1'b1;
                    if (&cycle_q[6]) cycle_q[7] <= cycle_q[7] + 1'b1;
                  end
                end
              end
            end
          end
        end
      end
      if (rsp_valid_o && rsp_ready_i) active_q <= 1'b0;
    end
  end

  logic unused;
  assign unused = ^unused_base_cycles;
endmodule
