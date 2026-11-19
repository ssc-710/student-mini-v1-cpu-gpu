// SPDX-License-Identifier: Apache-2.0
// Mini physical memory boundary: reject non-DRAM or unaligned DMA requests
// before they reach LiteDRAM (whose native protocol has no error response).
module student_mini_native_dma_bridge #(
  parameter int NATIVE_ADDR_WIDTH = 28,
  parameter bit DEBUG = 1'b0,
  parameter bit WRITE_FENCE = 1'b1
) (
  input logic clk_i,rst_ni,req_valid_i,
  output logic req_ready_o,
  input logic req_write_i,
  input logic [31:0] req_addr_i,
  input logic [127:0] req_wdata_i,
  input logic [15:0] req_wstrb_i,
  output logic rsp_valid_o,
  input logic rsp_ready_i,
  output logic [127:0] rsp_rdata_o,
  output logic rsp_error_o,
  output logic native_cmd_valid_o,
  input logic native_cmd_ready_i,
  output logic native_cmd_we_o,
  output logic [NATIVE_ADDR_WIDTH-1:0] native_cmd_addr_o,
  output logic native_wdata_valid_o,
  input logic native_wdata_ready_i,
  output logic [127:0] native_wdata_o,
  output logic [15:0] native_wstrb_o,
  input logic native_rdata_valid_i,
  output logic native_rdata_ready_o,
  input logic [127:0] native_rdata_i
);
  logic invalid_request,error_pending_q,core_ready,core_valid,core_error;
  logic [127:0] core_data;
  assign invalid_request=(req_addr_i[31:28]!=4'h4) || (req_addr_i[3:0]!=0);
  assign req_ready_o=core_ready && !error_pending_q;
  assign rsp_valid_o=core_valid || error_pending_q;
  assign rsp_error_o=core_error || error_pending_q;
  assign rsp_rdata_o=error_pending_q ? 128'd0 : core_data;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if(!rst_ni)error_pending_q<=0;
    else if(error_pending_q && rsp_ready_i)error_pending_q<=0;
    else if(req_valid_i && req_ready_o && invalid_request)error_pending_q<=1;
  end
  litex_native_dma_bridge #(.NATIVE_ADDR_WIDTH(NATIVE_ADDR_WIDTH),.DEBUG(DEBUG),.WRITE_FENCE(WRITE_FENCE)) u_native (
    .clk_i,.rst_ni,.req_valid_i(req_valid_i && !invalid_request && !error_pending_q),.req_ready_o(core_ready),
    .req_write_i,.req_addr_i,.req_wdata_i,.req_wstrb_i,.rsp_valid_o(core_valid),.rsp_ready_i(rsp_ready_i && !error_pending_q),
    .rsp_rdata_o(core_data),.rsp_error_o(core_error),.native_cmd_valid_o,.native_cmd_ready_i,.native_cmd_we_o,.native_cmd_addr_o,
    .native_wdata_valid_o,.native_wdata_ready_i,.native_wdata_o,.native_wstrb_o,.native_rdata_valid_i,.native_rdata_ready_o,.native_rdata_i
  );
endmodule
