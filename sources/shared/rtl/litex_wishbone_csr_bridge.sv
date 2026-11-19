// SPDX-License-Identifier: Apache-2.0
// Converts one LiteX/Wishbone classic transaction into the course CSR handshake.
module litex_wishbone_csr_bridge (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  logic        wb_cyc_i,
  input  logic        wb_stb_i,
  input  logic        wb_we_i,
  input  logic [29:0] wb_adr_i,
  input  logic [31:0] wb_dat_w_i,
  input  logic [3:0]  wb_sel_i,
  output logic [31:0] wb_dat_r_o,
  output logic        wb_ack_o,
  output logic        wb_err_o,
  output logic        csr_req_valid_o,
  input  logic        csr_req_ready_i,
  output logic        csr_write_o,
  output logic [7:0]  csr_addr_o,
  output logic [31:0] csr_wdata_o,
  input  logic        csr_rsp_valid_i,
  output logic        csr_rsp_ready_o,
  input  logic [31:0] csr_rdata_i
);
  typedef enum logic [1:0] {IDLE, REQUEST, RESPONSE, ACK} state_t;
  state_t state_q;
  logic write_q;
  logic [7:0] addr_q;
  logic [31:0] wdata_q;

  assign csr_req_valid_o = state_q == REQUEST;
  assign csr_write_o = write_q;
  assign csr_addr_o = addr_q;
  assign csr_wdata_o = wdata_q;
  assign csr_rsp_ready_o = state_q == RESPONSE;
  assign wb_ack_o = state_q == ACK;
  assign wb_err_o = 1'b0;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      write_q <= 1'b0;
      addr_q <= '0;
      wdata_q <= '0;
      wb_dat_r_o <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (wb_cyc_i && wb_stb_i) begin
          write_q <= wb_we_i;
          addr_q <= {wb_adr_i[5:0], 2'b00};
          wdata_q <= wb_dat_w_i;
          state_q <= REQUEST;
        end
        REQUEST: if (csr_req_ready_i) state_q <= RESPONSE;
        RESPONSE: if (csr_rsp_valid_i) begin
          wb_dat_r_o <= csr_rdata_i;
          state_q <= ACK;
        end
        ACK: state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  logic unused_sel;
  assign unused_sel = ^wb_sel_i;
endmodule
