// SPDX-License-Identifier: Apache-2.0
module accelerator_shell (
  input logic clk_i,input logic rst_ni,
  input logic csr_req_valid_i,output logic csr_req_ready_o,input logic csr_write_i,input logic [7:0] csr_addr_i,input logic [31:0] csr_wdata_i,
  output logic csr_rsp_valid_o,input logic csr_rsp_ready_i,output logic [31:0] csr_rdata_o,
  output logic accel_cmd_valid_o,input logic accel_cmd_ready_i,output logic [2:0] accel_cmd_opcode_o,output logic [31:0] accel_cmd_desc_addr_o,
  input logic accel_rsp_valid_i,output logic accel_rsp_ready_o,input logic [7:0] accel_rsp_status_i,input logic [63:0] accel_rsp_cycles_i,
  output logic irq_o
);
  logic start_raw,irq_clear,pending_q,inflight_q,irq_q;logic[2:0]opcode_cfg,opcode_q;logic[31:0]desc_cfg,desc_q;logic[7:0]status_q;logic[63:0]cycles_q;logic busy;
  assign busy=pending_q|inflight_q;assign accel_cmd_valid_o=pending_q;assign accel_cmd_opcode_o=opcode_q;assign accel_cmd_desc_addr_o=desc_q;assign accel_rsp_ready_o=1'b1;assign irq_o=irq_q;
  course_csr u_csr(.clk_i,.rst_ni,.req_valid_i(csr_req_valid_i),.req_ready_o(csr_req_ready_o),.req_write_i(csr_write_i),.req_addr_i(csr_addr_i),.req_wdata_i(csr_wdata_i),.req_wstrb_i(csr_write_i?4'hf:4'h0),.rsp_valid_o(csr_rsp_valid_o),.rsp_ready_i(csr_rsp_ready_i),.rsp_rdata_o(csr_rdata_o),.start_o(start_raw),.irq_clear_o(irq_clear),.done_i(irq_q),.busy_i(busy),.opcode_o(opcode_cfg),.descriptor_addr_o(desc_cfg),.result_status_i(status_q),.result_cycles_i(cycles_q));
  always_ff @(posedge clk_i or negedge rst_ni)begin
    if(!rst_ni)begin pending_q<=0;inflight_q<=0;irq_q<=0;opcode_q<=0;desc_q<=0;status_q<=0;cycles_q<=0;end else begin
      if(start_raw&&!busy)begin pending_q<=1;opcode_q<=opcode_cfg;desc_q<=desc_cfg;end
      if(accel_cmd_valid_o&&accel_cmd_ready_i)begin pending_q<=0;inflight_q<=1;end
      if(irq_clear)irq_q<=0;
      if(accel_rsp_valid_i&&accel_rsp_ready_o)begin inflight_q<=0;status_q<=accel_rsp_status_i;cycles_q<=accel_rsp_cycles_i;irq_q<=1;end
    end
  end
endmodule
