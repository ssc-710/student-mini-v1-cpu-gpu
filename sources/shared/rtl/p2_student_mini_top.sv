// SPDX-License-Identifier: Apache-2.0
module p2_student_mini_top (
  input logic clk_i, rst_ni,
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
  logic op_valid, op_ready; logic [2:0] opcode; logic [511:0] descriptor;
  logic req_valid,req_ready,req_write,dma_rsp_valid,dma_rsp_ready,dma_error;
  logic [31:0] req_addr;logic [127:0] req_data,dma_data;logic [15:0] strobe;
  logic done,done_ready;logic [7:0] status;logic [63:0] cycles;
  litex_accelerator_dispatcher u_dispatcher (
    .clk_i,.rst_ni,.cmd_valid_i,.cmd_ready_o,.cmd_opcode_i,.cmd_desc_addr_i,
    .mem_req_valid_o,.mem_req_ready_i,.mem_req_write_o,.mem_req_addr_o,.mem_req_wdata_o,.mem_req_wstrb_o,
    .mem_rsp_valid_i,.mem_rsp_ready_o,.mem_rsp_rdata_i,.mem_rsp_error_i,
    .op_valid_o(op_valid),.op_ready_i(op_ready),.op_opcode_o(opcode),.op_descriptor_o(descriptor),.op_operator_arg_o(),
    .op_dma_req_valid_i(req_valid),.op_dma_req_ready_o(req_ready),.op_dma_req_write_i(req_write),.op_dma_req_addr_i(req_addr),
    .op_dma_req_wdata_i(req_data),.op_dma_req_wstrb_i(strobe),.op_dma_rsp_valid_o(dma_rsp_valid),.op_dma_rsp_ready_i(dma_rsp_ready),
    .op_dma_rsp_rdata_o(dma_data),.op_dma_rsp_error_o(dma_error),.op_rsp_valid_i(done),.op_rsp_ready_o(done_ready),
    .op_rsp_status_i(status),.op_rsp_cycles_i(cycles),.rsp_valid_o,.rsp_ready_i,.rsp_status_o,.rsp_cycles_o
  );
  p2_student_mini_vector u_vector (
    .clk_i,.rst_ni,.cmd_valid_i(op_valid && opcode==3'd2),.cmd_ready_o(op_ready),.descriptor_i(descriptor),
    .dma_req_valid_o(req_valid),.dma_req_ready_i(req_ready),.dma_req_write_o(req_write),.dma_req_addr_o(req_addr),
    .dma_req_wdata_o(req_data),.dma_req_wstrb_o(strobe),.dma_rsp_valid_i(dma_rsp_valid),.dma_rsp_ready_o(dma_rsp_ready),
    .dma_rsp_rdata_i(dma_data),.dma_rsp_error_i(dma_error),.rsp_valid_o(done),.rsp_ready_i(done_ready),.rsp_status_o(status),.rsp_cycles_o(cycles)
  );
endmodule
