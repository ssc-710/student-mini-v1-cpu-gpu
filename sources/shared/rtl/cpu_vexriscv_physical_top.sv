module cpu_vexriscv_physical_top (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [31:0] reset_vector_i,
    input  logic        timer_interrupt_i,
    input  logic        software_interrupt_i,
    input  logic [31:0] external_interrupt_i,
    output logic [31:0] activity_o
);
  logic i_cyc, i_stb, i_ack, i_we, i_err;
  logic [29:0] i_addr;
  logic [31:0] i_wdata, i_rdata;
  logic [3:0] i_sel;
  logic [2:0] i_cti;
  logic [1:0] i_bte;
  logic d_cyc, d_stb, d_ack, d_we, d_err;
  logic [29:0] d_addr;
  logic [31:0] d_wdata, d_rdata;
  logic [3:0] d_sel;
  logic [2:0] d_cti;
  logic [1:0] d_bte;
  logic native_cmd_valid, native_cmd_ready, native_cmd_we;
  logic [29:0] native_cmd_addr;
  logic native_wdata_valid, native_wdata_ready;
  logic [31:0] native_wdata;
  logic [3:0] native_wdata_we;
  logic native_rdata_valid, native_rdata_ready;
  logic [31:0] native_rdata;
  logic native_error;

  VexRiscv core (
    .externalResetVector(reset_vector_i),
    .timerInterrupt(timer_interrupt_i),
    .softwareInterrupt(software_interrupt_i),
    .externalInterruptArray(external_interrupt_i),
    .iBusWishbone_CYC(i_cyc), .iBusWishbone_STB(i_stb),
    .iBusWishbone_ACK(i_ack), .iBusWishbone_WE(i_we),
    .iBusWishbone_ADR(i_addr), .iBusWishbone_DAT_MISO(i_rdata),
    .iBusWishbone_DAT_MOSI(i_wdata), .iBusWishbone_SEL(i_sel),
    .iBusWishbone_ERR(i_err), .iBusWishbone_CTI(i_cti),
    .iBusWishbone_BTE(i_bte),
    .dBusWishbone_CYC(d_cyc), .dBusWishbone_STB(d_stb),
    .dBusWishbone_ACK(d_ack), .dBusWishbone_WE(d_we),
    .dBusWishbone_ADR(d_addr), .dBusWishbone_DAT_MISO(d_rdata),
    .dBusWishbone_DAT_MOSI(d_wdata), .dBusWishbone_SEL(d_sel),
    .dBusWishbone_ERR(d_err), .dBusWishbone_CTI(d_cti),
    .dBusWishbone_BTE(d_bte), .clk(clk_i), .reset(!rst_ni)
  );

  cpu_wishbone_litedram_adapter adapter (
    .clk_i(clk_i), .rst_ni(rst_ni),
    .i_wb_cyc_i(i_cyc), .i_wb_stb_i(i_stb), .i_wb_we_i(i_we),
    .i_wb_adr_i(i_addr), .i_wb_dat_i(i_wdata), .i_wb_sel_i(i_sel),
    .i_wb_ack_o(i_ack), .i_wb_err_o(i_err), .i_wb_dat_o(i_rdata),
    .d_wb_cyc_i(d_cyc), .d_wb_stb_i(d_stb), .d_wb_we_i(d_we),
    .d_wb_adr_i(d_addr), .d_wb_dat_i(d_wdata), .d_wb_sel_i(d_sel),
    .d_wb_ack_o(d_ack), .d_wb_err_o(d_err), .d_wb_dat_o(d_rdata),
    .native_cmd_valid_o(native_cmd_valid), .native_cmd_ready_i(native_cmd_ready),
    .native_cmd_we_o(native_cmd_we), .native_cmd_addr_o(native_cmd_addr),
    .native_wdata_valid_o(native_wdata_valid), .native_wdata_ready_i(native_wdata_ready),
    .native_wdata_o(native_wdata), .native_wdata_we_o(native_wdata_we),
    .native_rdata_valid_i(native_rdata_valid), .native_rdata_ready_o(native_rdata_ready),
    .native_rdata_i(native_rdata), .native_error_i(native_error)
  );

  cpu_local_sram_endpoint memory (
    .clk_i(clk_i), .rst_ni(rst_ni),
    .cmd_valid_i(native_cmd_valid), .cmd_ready_o(native_cmd_ready),
    .cmd_we_i(native_cmd_we), .cmd_addr_i(native_cmd_addr),
    .wdata_valid_i(native_wdata_valid), .wdata_ready_o(native_wdata_ready),
    .wdata_i(native_wdata), .wdata_we_i(native_wdata_we),
    .rdata_valid_o(native_rdata_valid), .rdata_ready_i(native_rdata_ready),
    .rdata_o(native_rdata), .error_o(native_error)
  );

  always_comb begin
    activity_o = {i_addr[7:0], d_addr[7:0], native_cmd_addr[7:0],
                  i_cyc, d_cyc, native_cmd_valid, native_cmd_we,
                  native_wdata_valid, native_rdata_valid, i_ack, d_ack};
  end
endmodule
