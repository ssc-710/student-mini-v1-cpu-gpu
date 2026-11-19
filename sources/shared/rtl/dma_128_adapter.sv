// SPDX-License-Identifier: Apache-2.0
// One-outstanding 128-bit DMA adapter shared by the B0 operators.
module dma_128_adapter (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic cmd_write_i, input logic [31:0] cmd_addr_i,
  input logic [127:0] cmd_wdata_i, input logic [15:0] cmd_wstrb_i,
  output logic mem_req_valid_o, input logic mem_req_ready_i,
  output logic mem_req_write_o, output logic [31:0] mem_req_addr_o,
  output logic [127:0] mem_req_wdata_o, output logic [15:0] mem_req_wstrb_o,
  input logic mem_rsp_valid_i, output logic mem_rsp_ready_o,
  input logic [127:0] mem_rsp_rdata_i, input logic mem_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [127:0] rsp_rdata_o, output logic rsp_error_o,
  input logic counters_clear_i,
  output logic [31:0] read_requests_o, output logic [31:0] write_requests_o,
  output logic [63:0] read_bytes_o, output logic [63:0] write_bytes_o,
  output logic [63:0] wait_cycles_o, output logic [1:0] outstanding_peak_o
);
  typedef enum logic [1:0] {IDLE, REQUEST, WAIT_RESPONSE, RESPONSE} state_t;
  state_t state_q;
  logic write_q;
  logic [31:0] addr_q;
  logic [127:0] wdata_q, rdata_q;
  logic [15:0] wstrb_q;
  logic error_q;
  integer byte_index;
  logic [5:0] write_byte_count;

  always_comb begin
    write_byte_count = 6'd0;
    for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
      write_byte_count = write_byte_count + wstrb_q[byte_index];
  end

  assign cmd_ready_o = state_q == IDLE;
  assign mem_req_valid_o = state_q == REQUEST;
  assign mem_req_write_o = write_q;
  assign mem_req_addr_o = addr_q;
  assign mem_req_wdata_o = wdata_q;
  assign mem_req_wstrb_o = wstrb_q;
  assign mem_rsp_ready_o = state_q == WAIT_RESPONSE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_rdata_o = rdata_q;
  assign rsp_error_o = error_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; write_q <= 1'b0; addr_q <= '0; wdata_q <= '0; wstrb_q <= '0;
      rdata_q <= '0; error_q <= 1'b0; read_requests_o <= '0; write_requests_o <= '0;
      read_bytes_o <= '0; write_bytes_o <= '0; wait_cycles_o <= '0; outstanding_peak_o <= '0;
    end else begin
      if (counters_clear_i) begin
        read_requests_o <= '0; write_requests_o <= '0; read_bytes_o <= '0;
        write_bytes_o <= '0; wait_cycles_o <= '0; outstanding_peak_o <= '0;
      end
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          write_q <= cmd_write_i; addr_q <= cmd_addr_i; wdata_q <= cmd_wdata_i;
          wstrb_q <= cmd_wstrb_i; error_q <= 1'b0; state_q <= REQUEST;
        end
        REQUEST: begin
          if (!mem_req_ready_i) wait_cycles_o <= wait_cycles_o + 1'b1;
          if (mem_req_ready_i) begin
            if (write_q) begin
              write_requests_o <= write_requests_o + 1'b1;
              write_bytes_o <= write_bytes_o + {{58{1'b0}}, write_byte_count};
            end else begin
              read_requests_o <= read_requests_o + 1'b1;
              read_bytes_o <= read_bytes_o + 64'd16;
            end
            outstanding_peak_o <= 2'd1; state_q <= WAIT_RESPONSE;
          end
        end
        WAIT_RESPONSE: begin
          if (!mem_rsp_valid_i) wait_cycles_o <= wait_cycles_o + 1'b1;
          if (mem_rsp_valid_i) begin
            rdata_q <= mem_rsp_rdata_i; error_q <= mem_rsp_error_i; state_q <= RESPONSE;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
