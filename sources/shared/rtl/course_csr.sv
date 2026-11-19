// SPDX-License-Identifier: Apache-2.0
// 0x00 control/status, 0x04 opcode, 0x08 descriptor, 0x0c IRQ clear,
// 0x10 result status, 0x14 cycles low, 0x18 cycles high.
module course_csr (
  input logic clk_i,input logic rst_ni,
  input logic req_valid_i,output logic req_ready_o,input logic req_write_i,
  input logic [7:0] req_addr_i,input logic [31:0] req_wdata_i,input logic [3:0] req_wstrb_i,
  output logic rsp_valid_o,input logic rsp_ready_i,output logic [31:0] rsp_rdata_o,
  output logic start_o,output logic irq_clear_o,input logic done_i,input logic busy_i,
  output logic [2:0] opcode_o,output logic [31:0] descriptor_addr_o,
  input logic [7:0] result_status_i,input logic [63:0] result_cycles_i
);
  logic rsp_valid_q;logic[31:0]rsp_data_q;logic[63:0]cycles_snapshot_q;
  assign req_ready_o=~rsp_valid_q|rsp_ready_i;assign rsp_valid_o=rsp_valid_q;assign rsp_rdata_o=rsp_data_q;
  assign irq_clear_o=req_valid_i&&req_ready_o&&req_write_i&&(req_addr_i[7:2]==6'h03)&&req_wstrb_i[0]&&req_wdata_i[0];
  always_ff @(posedge clk_i or negedge rst_ni)begin
    if(!rst_ni)begin rsp_valid_q<=0;rsp_data_q<=0;start_o<=0;opcode_o<=0;descriptor_addr_o<=0;cycles_snapshot_q<=0;end
    else begin
      start_o<=0;if(rsp_ready_i)rsp_valid_q<=0;
      if(req_valid_i&&req_ready_o)begin rsp_valid_q<=1;
        unique case(req_addr_i[7:2])
          6'h00:begin rsp_data_q<={30'b0,done_i,busy_i};if(req_write_i&&req_wstrb_i[0]&&req_wdata_i[0])start_o<=1;end
          6'h01:begin rsp_data_q<={29'b0,opcode_o};if(req_write_i&&req_wstrb_i[0])opcode_o<=req_wdata_i[2:0];end
          6'h02:begin rsp_data_q<=descriptor_addr_o;if(req_write_i)begin if(req_wstrb_i[0])descriptor_addr_o[7:0]<=req_wdata_i[7:0];if(req_wstrb_i[1])descriptor_addr_o[15:8]<=req_wdata_i[15:8];if(req_wstrb_i[2])descriptor_addr_o[23:16]<=req_wdata_i[23:16];if(req_wstrb_i[3])descriptor_addr_o[31:24]<=req_wdata_i[31:24];end end
          6'h03:rsp_data_q<=0;
          6'h04:rsp_data_q<={24'b0,result_status_i};
          // Reading low captures one stable 64-bit snapshot; high completes it.
          6'h05:begin rsp_data_q<=result_cycles_i[31:0];cycles_snapshot_q<=result_cycles_i;end
          6'h06:rsp_data_q<=cycles_snapshot_q[63:32];
          default:rsp_data_q<=32'hbad0_add0;
        endcase
      end
    end
  end
endmodule
