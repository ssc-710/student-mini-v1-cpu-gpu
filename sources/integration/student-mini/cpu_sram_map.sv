// Exact pin mapping for the provisional CPU memory library; no behavior model.
module $__STUDENT_CPU_SRAM32X1024_ (
    input wire CLK_C, PORT_W_CLK, PORT_R_CLK,
    input wire [9:0] PORT_W_ADDR, PORT_R_ADDR,
    input wire [31:0] PORT_W_WR_DATA,
    input wire [3:0] PORT_W_WR_EN,
    input wire PORT_R_RD_EN,
    output wire [31:0] PORT_R_RD_DATA
);
  parameter [32767:0] INIT = {32768{1'bx}};
  wire _TECHMAP_FAIL_ = (INIT !== {32768{1'bx}});
  student_mini_cpu_sram_32x1024 _TECHMAP_REPLACE_ (
    .clk(CLK_C), .write_address(PORT_W_ADDR), .read_address(PORT_R_ADDR),
    .write_data(PORT_W_WR_DATA), .write_enable(PORT_W_WR_EN),
    .read_enable(PORT_R_RD_EN), .read_data(PORT_R_RD_DATA)
  );
endmodule
