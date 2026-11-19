// Physical memory adaptation for enabled synchronous CPU memories.
// PROVISIONAL: not connected to the frozen CPU boundary. Same-address
// read/write behavior is not qualified; never advertise a read-old guarantee.
// The real OpenRAM read port does not promise to hold its output while idle.
// Retain the preceding valid word when read_enable is low; do not add a cycle
// to an enabled read. No initialized contents or reset values are invented.
module student_mini_cpu_sram_32x1024 (
    input wire clk,
    input wire [9:0] write_address, read_address,
    input wire [31:0] write_data,
    input wire [3:0] write_enable,
    input wire read_enable,
    output wire [31:0] read_data
);
  wire [31:0] macro_data;
  reg read_live;
  reg [31:0] held_data;
  always @(posedge clk) begin
    read_live <= read_enable;
    if (read_live) held_data <= macro_data;
  end
  assign read_data = read_live ? macro_data : held_data;
  vortex_sp_32x1024_w4 storage (
    .clk0(clk), .csb0(~(|write_enable)), .wmask0(write_enable),
    .addr0(write_address), .din0(write_data),
    .clk1(clk), .csb1(~read_enable), .addr1(read_address), .dout1(macro_data)
  );
endmodule
