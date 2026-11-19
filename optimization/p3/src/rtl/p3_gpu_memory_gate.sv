// One ready/valid channel, seeded backpressure. Once valid is exposed, it
// stays exposed until acceptance: random gating must not withdraw valid.
module p3_gpu_memory_gate #(parameter int WIDTH=32) (
 input wire clk, reset, input wire [31:0] seed,
 input wire [7:0] stall_threshold,
 input wire in_valid, output wire in_ready, input wire [WIDTH-1:0] in_data,
 output wire out_valid, input wire out_ready, output wire [WIDTH-1:0] out_data,
 output reg [63:0] stall_cycles, accepted);
 reg [31:0] rng; reg exposed, was_stalled;
 reg [WIDTH-1:0] stalled_data;
 function automatic [31:0] xorshift(input [31:0] value);
   reg [31:0] x;
   begin x=value^(value<<13); x=x^(x>>17); xorshift=x^(x<<5); end
 endfunction
 wire allow = exposed || rng[7:0]>=stall_threshold;
 assign out_valid = in_valid && allow;
 assign in_ready = out_ready && allow;
 assign out_data = in_data;
 always @(posedge clk) begin
   if (reset) begin
     rng <= seed==0 ? 32'h6d2b79f5 : seed;
     exposed<=0; was_stalled<=0; stalled_data<='0; stall_cycles<=0; accepted<=0;
   end else begin
     rng<=xorshift(rng);
     if (was_stalled && (!in_valid || in_data!=stalled_data))
       $fatal(1,"MINI31 upstream payload changed before handshake");
     was_stalled<=in_valid && !in_ready;
     if (in_valid && !in_ready) begin stalled_data<=in_data; stall_cycles<=stall_cycles+1; end
     if (in_valid && in_ready) accepted<=accepted+1;
     if (!in_valid || (out_valid && out_ready)) exposed<=0;
     else if (out_valid && !out_ready) exposed<=1;
   end
 end
endmodule
