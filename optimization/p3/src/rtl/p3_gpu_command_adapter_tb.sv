`timescale 1ns/1ps
module p3_gpu_command_adapter_tb;
 reg clk=0; always #5 clk=~clk;
 reg rst_ni=0, cmd_valid=0, rsp_ready=0, dcr_valid=0, busy=0;
 reg [1:0] kind=0; reg [11:0] addr=0;
 reg [31:0] data=0, dcr_data=0;
 wire ready, rsp_valid, error, req_valid, rw, start;
 wire [11:0] req_addr; wire [31:0] rsp_data, req_data;
 p3_gpu_command_adapter dut(.clk_i(clk), .rst_ni(rst_ni),
  .host_cmd_valid_i(cmd_valid), .host_cmd_ready_o(ready), .host_cmd_kind_i(kind),
  .host_cmd_addr_i(addr), .host_cmd_data_i(data), .host_rsp_valid_o(rsp_valid),
  .host_rsp_ready_i(rsp_ready), .host_rsp_data_o(rsp_data), .host_rsp_error_o(error),
  .dcr_req_valid_o(req_valid), .dcr_req_rw_o(rw), .dcr_req_addr_o(req_addr),
  .dcr_req_data_o(req_data), .dcr_rsp_valid_i(dcr_valid), .dcr_rsp_data_i(dcr_data),
  .start_o(start), .busy_i(busy));
 task tick; begin @(posedge clk); #1; end endtask
 initial begin
  tick(); @(negedge clk); rst_ni=1;
  // Nonzero read tag must survive the seam unchanged.
  cmd_valid=1; kind=1; addr=12'h805; data=32'hcafe0042; tick();
  if (!req_valid || rw || req_addr!=12'h805 || req_data!=32'hcafe0042)
   $fatal(1,"read tag/address changed");
  @(negedge clk); cmd_valid=0; tick();
  if (rsp_valid) $fatal(1,"read responded before core");
  @(negedge clk); dcr_valid=1; dcr_data=32'h12345678; tick();
  @(negedge clk); dcr_valid=0;
  repeat(17) begin tick(); if (!rsp_valid || rsp_data!=32'h12345678 || error || ready)
   $fatal(1,"held response unstable"); end
  @(negedge clk); rsp_ready=1; tick();
  if (rsp_valid || !ready) $fatal(1,"response not accepted exactly once");
  @(negedge clk); rsp_ready=0; busy=1; cmd_valid=1; kind=2; tick();
  if (ready || start) $fatal(1,"start accepted while busy");
  @(negedge clk); busy=0; tick();
  if (!start || !rsp_valid) $fatal(1,"idle start was not accepted");
  @(negedge clk); cmd_valid=0; rst_ni=0; tick();
  if (rsp_valid || start || req_valid) $fatal(1,"reset did not clear pending response");
  $display("P3_COMMAND_UNIT_PASS tag_preserved=1 response_hold_cycles=17 busy_start_gate=1 reset_clear=1");
  $finish;
 end
 initial begin #10000; $fatal(1,"unit timeout"); end
endmodule
