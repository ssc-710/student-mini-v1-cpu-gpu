`timescale 1ns/1ps
// Stub only the core producer/consumer. Its packing mirrors the bound sv2v
// export; both real adapters and the actual physical top are under test.
module Vortex (
 input clk,reset,input [0:1] mem_req_ready,mem_rsp_valid,
 input [1023:0] mem_rsp_data,input [19:0] mem_rsp_tag,
 output reg [0:1] mem_req_valid=0,mem_req_rw=0,mem_rsp_ready=0,
 output reg [127:0] mem_req_byteen=0,output reg [51:0] mem_req_addr=0,
 output reg [1023:0] mem_req_data=0,output reg [19:0] mem_req_tag=0,
 input dcr_req_valid,dcr_req_rw,input [11:0] dcr_req_addr,
 input [31:0] dcr_req_data,input start,
 output dcr_rsp_valid,output [31:0] dcr_rsp_data,output busy
);
 assign dcr_rsp_valid=0;assign dcr_rsp_data=0;assign busy=0;
endmodule

module bench;
 reg clk_i=0,rst_ni=0;
 always #5 clk_i=~clk_i;
 reg [0:1] mem_req_ready_i=0,mem_rsp_valid_i=0;
 wire [0:1] mem_req_valid_o,mem_req_rw_o,mem_rsp_ready_o;
 wire [127:0] mem_req_byteen_o;
 wire [51:0] mem_req_addr_o;
 wire [1023:0] mem_req_data_o;
 wire [19:0] mem_req_tag_o;
 reg [1023:0] mem_rsp_data_i=0;
 reg [19:0] mem_rsp_tag_i=0;
 wire host_cmd_ready_o,host_rsp_valid_o,host_rsp_error_o,busy_o;
 wire [31:0] host_rsp_data_o;
 vortex_physical_top dut(.clk_i,.rst_ni,
   .host_cmd_valid_i(1'b0),.host_cmd_kind_i(2'b0),.host_cmd_addr_i(12'b0),
   .host_cmd_data_i(32'b0),.host_rsp_ready_i(1'b1),
   .host_cmd_ready_o,.host_rsp_valid_o,.host_rsp_error_o,.host_rsp_data_o,.busy_o,
   .mem_req_valid_o,.mem_req_ready_i,.mem_req_rw_o,.mem_req_byteen_o,
   .mem_req_addr_o,.mem_req_data_o,.mem_req_tag_o,
   .mem_rsp_valid_i,.mem_rsp_ready_o,.mem_rsp_data_i,.mem_rsp_tag_i);
 integer seed,state,k,p,j,active;
 reg [0:1] val,wr;
 reg [63:0] be[0:1];reg [25:0] addr[0:1];
 reg [511:0] data[0:1],rsp[0:1];reg [9:0] tag[0:1],rtag[0:1];
 task check_requests;
   begin
    for(p=0;p<2;p=p+1) begin
     if(mem_req_valid_o[p]!==val[p]) $fatal(1,"PORT_VALID_MISMATCH");
     if(val[p] && (mem_req_rw_o[p]!==wr[p] ||
       mem_req_byteen_o[p*64+:64]!==be[p] ||
       mem_req_addr_o[p*26+:26]!==addr[p] ||
       mem_req_data_o[p*512+:512]!==data[p] ||
       mem_req_tag_o[p*10+:10]!==tag[p]))
       $fatal(1,"PORT_REQUEST_MISMATCH seed=%0d row=%0d port=%0d",seed,k,p);
    end
   end
 endtask
 task check_responses;
   begin
    for(p=0;p<2;p=p+1) begin
     if(dut.core.mem_rsp_valid[p]!==val[p]) $fatal(1,"RESPONSE_VALID_MISMATCH");
     if(val[p] && (dut.core.mem_rsp_data[(1-p)*512+:512]!==rsp[p] ||
       dut.core.mem_rsp_tag[(1-p)*10+:10]!==rtag[p]))
       $fatal(1,"PORT_RESPONSE_MISMATCH seed=%0d row=%0d port=%0d",seed,k,p);
    end
   end
 endtask
 initial begin
  if(!$value$plusargs("seed=%d",seed)) seed=1;
  state=seed;
  repeat(2) @(negedge clk_i);
  for(k=0;k<64;k=k+1) begin
   rst_ni=1;
   val=(k%3==0)?2'b10:((k%3==1)?2'b01:2'b11);
   wr=k;dut.core.mem_req_valid=val;dut.core.mem_req_rw=wr;
   dut.core.mem_rsp_ready=0;mem_req_ready_i=0;mem_rsp_valid_i=val;
   for(p=0;p<2;p=p+1) begin
    be[p]={$random(state),$random(state)};addr[p]=$random(state);tag[p]=$random(state);
    rtag[p]=$random(state);
    for(j=0;j<16;j=j+1) begin data[p][j*32+:32]=$random(state);rsp[p][j*32+:32]=$random(state);end
    dut.core.mem_req_byteen[(1-p)*64+:64]=be[p];
    dut.core.mem_req_addr[(1-p)*26+:26]=addr[p];
    dut.core.mem_req_data[(1-p)*512+:512]=data[p];
    dut.core.mem_req_tag[(1-p)*10+:10]=tag[p];
    mem_rsp_data_i[p*512+:512]=rsp[p];mem_rsp_tag_i[p*10+:10]=rtag[p];
   end
   @(negedge clk_i);check_requests;check_responses;
   dut.core.mem_req_valid=0;mem_rsp_valid_i=0;
   // Change upstream payload while each occupied skid remains backpressured.
   dut.core.mem_req_data='1;mem_rsp_data_i='1;
   repeat(3) begin @(negedge clk_i);check_requests;check_responses;end
   mem_req_ready_i=2'b11;dut.core.mem_rsp_ready=2'b11;
   @(negedge clk_i);val=0;check_requests;check_responses;
   // Reset occupied queues in alternating trials, then verify recovery.
   if(k%2==0) begin
    dut.core.mem_req_valid=2'b11;mem_rsp_valid_i=2'b11;
    @(negedge clk_i);rst_ni=0;dut.core.mem_req_valid=0;mem_rsp_valid_i=0;
    @(negedge clk_i);val=0;check_requests;check_responses;
   end
  end
  $display("PORT_PACKING_PASS seed=%0d trials=64",seed);$finish;
 end
endmodule
