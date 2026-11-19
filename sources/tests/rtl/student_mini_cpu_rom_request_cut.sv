// Timing-foundation candidate only; not installed into an accepted CPU.
// Classic Wishbone: capture address, perform the synchronous ROM read, reply.
module student_mini_cpu_rom_request_cut (
    input wire clk, reset, cyc, stb,
    input wire [14:0] address,
    output reg [14:0] rom_address,
    output wire ack
);
  reg [1:0] state = 0;
  assign ack = (state == 2) && cyc && stb && !reset;
  always @(posedge clk) begin
    if (reset || !cyc || !stb) state <= 0;
    else case (state)
      0: begin rom_address <= address; state <= 1; end
      1: state <= 2;
      default: state <= 0;
    endcase
  end
endmodule
