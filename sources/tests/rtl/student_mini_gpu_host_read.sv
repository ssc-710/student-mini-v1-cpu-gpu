`timescale 1ns/1ps
module bench;
 reg clk=0,reset=1,dcr_req_valid=0,dcr_req_rw=0,start=0;
 reg [11:0] dcr_req_addr=0;reg [31:0] dcr_req_data=0;
 wire dcr_rsp_valid,busy;wire [31:0] dcr_rsp_data;
 integer drain,index,spins,reads=0;
 student_mini_gpu_physical_bridge dut(.clk,.reset,.dcr_req_valid,.dcr_req_rw,
    .dcr_req_addr,.dcr_req_data,.dcr_rsp_valid,.dcr_rsp_data,.start,.busy);
 task tick;begin clk=0;#5;clk=1;#5;end endtask
 task read_dcr(input [11:0] address);
 begin
   dcr_req_valid=1;dcr_req_rw=0;dcr_req_addr=address;dcr_req_data=32'h12345678;
   tick;dcr_req_valid=0;tick;
   spins=0;
   while(!dcr_rsp_valid && spins<20) begin tick;spins=spins+1;end
   if(!dcr_rsp_valid || dcr_rsp_data!=={20'b0,address}) $fatal(1,"DCR_RESPONSE_MISMATCH");
   reads=reads+1;
   if(drain) tick;
 end
 endtask
 initial begin
  if(!$value$plusargs("drain=%d",drain)) drain=0;
  repeat(3) tick;reset=0;tick;
  for(index=0;index<32;index=index+1) begin
   // Exactly the pinned driver's write/read tick schedule.
   dcr_req_valid=1;dcr_req_rw=1;dcr_req_addr=index;dcr_req_data=index;tick;
   dcr_req_valid=0;tick;
   read_dcr(index);read_dcr(index+64);
  end
  if(reads!=64) $fatal(1,"MISSING_READ");
  $display("GPU_HOST_READ_HANDSHAKE_PASS reads=64");$finish;
 end
endmodule
