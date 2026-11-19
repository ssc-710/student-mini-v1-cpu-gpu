(* blackbox *)
module vortex_dp_80x64_w4 (
  input wire clk0,
  input wire csb0,
  input wire [3:0] wmask0,
  input wire [5:0] addr0,
  input wire [79:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [5:0] addr1,
  output wire [79:0] dout1
);
endmodule

(* blackbox *)
module vortex_sp_32x256_w1 (
  input wire clk0,
  input wire csb0,
  input wire [7:0] addr0,
  input wire [31:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [7:0] addr1,
  output wire [31:0] dout1
);
endmodule

(* blackbox *)
module vortex_sp_32x512_w4 (
  input wire clk0,
  input wire csb0,
  input wire [3:0] wmask0,
  input wire [8:0] addr0,
  input wire [31:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [8:0] addr1,
  output wire [31:0] dout1
);
endmodule

(* blackbox *)
module vortex_sp_32x1024_w4 (
  input wire clk0,
  input wire csb0,
  input wire [3:0] wmask0,
  input wire [9:0] addr0,
  input wire [31:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [9:0] addr1,
  output wire [31:0] dout1
);
endmodule

(* blackbox *)
module vortex_sp_64x128_w8 (
  input wire clk0,
  input wire csb0,
  input wire [7:0] wmask0,
  input wire [6:0] addr0,
  input wire [63:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [6:0] addr1,
  output wire [63:0] dout1
);
endmodule

(* blackbox *)
module vortex_sp_128x128_w16 (
  input wire clk0,
  input wire csb0,
  input wire [15:0] wmask0,
  input wire [6:0] addr0,
  input wire [127:0] din0,
  input wire clk1,
  input wire csb1,
  input wire [6:0] addr1,
  output wire [127:0] dout1
);
endmodule
