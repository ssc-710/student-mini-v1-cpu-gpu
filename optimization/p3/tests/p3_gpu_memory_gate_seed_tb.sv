`timescale 1ns/1ps
module p3_gpu_memory_gate_seed_tb;
 integer test_seed=1;
 reg clk=0; always #5 clk=~clk;
 reg reset=1, valid=0, ready=0; reg [31:0] data=0;
 wire in_ready,out_valid; wire [31:0] out_data;
 wire [63:0] stalls,accepted;
 integer sent=0,received=0,cycles=0; reg held=0; reg [31:0] held_data;
 p3_gpu_memory_gate dut(.clk(clk),.reset(reset),.seed(test_seed),.stall_threshold(8'd128),
  .in_valid(valid),.in_ready(in_ready),.in_data(data),.out_valid(out_valid),
  .out_ready(ready),.out_data(out_data),.stall_cycles(stalls),.accepted(accepted));
 always @(posedge clk) if (!reset) begin
  if (held && (!out_valid || out_data!=held_data)) $fatal(1,"exposed valid withdrawn");
  held<=out_valid && !ready; held_data<=out_data;
  if (out_valid && ready) begin
   if (out_data!==received) $fatal(1,"lost/duplicated/reordered transaction");
   received=received+1;
  end
  if (valid && in_ready) sent=sent+1;
 end
 initial begin
  if (!$value$plusargs("SEED=%d",test_seed)) test_seed=1;
  repeat(2) @(negedge clk); reset=0;
  while(received<100) begin
   valid=(sent<100); data=sent; ready=(cycles%7>=3);
   @(negedge clk); cycles=cycles+1;
   if(cycles>2000) $fatal(1,"timeout");
  end
  valid=0;
  if(sent!=100 || accepted!=100 || stalls==0) $fatal(1,"counters invalid");
  $display("P3_MEMORY_GATE_UNIT_PASS seed=%0d transactions=%0d stalls=%0d cycles=%0d",test_seed,accepted,stalls,cycles);
  $finish;
 end
endmodule

