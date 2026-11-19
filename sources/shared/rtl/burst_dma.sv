// SPDX-License-Identifier: Apache-2.0
module burst_dma (
  input logic clk_i, input logic rst_ni, input logic start_i,
  input logic [31:0] src_addr_i, input logic [31:0] dst_addr_i,
  input logic [31:0] bytes_i, output logic busy_o, output logic done_o,
  output logic rd_valid_o, input logic rd_ready_i, output logic [31:0] rd_addr_o,
  input logic rsp_valid_i, output logic rsp_ready_o, input logic [127:0] rsp_data_i,
  output logic wr_valid_o, input logic wr_ready_i, output logic [31:0] wr_addr_o,
  output logic [127:0] wr_data_o
);
  typedef enum logic [1:0] {IDLE, READ_REQ, READ_RSP, WRITE_REQ} state_t;
  state_t state_q;
  logic [31:0] src_q, dst_q, remaining_q;
  logic [127:0] data_q;

  assign busy_o = state_q != IDLE;
  assign rd_valid_o = state_q == READ_REQ;
  assign rd_addr_o = src_q;
  assign rsp_ready_o = state_q == READ_RSP;
  assign wr_valid_o = state_q == WRITE_REQ;
  assign wr_addr_o = dst_q;
  assign wr_data_o = data_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; src_q <= '0; dst_q <= '0; remaining_q <= '0; data_q <= '0; done_o <= 1'b0;
    end else begin
      done_o <= 1'b0;
      unique case (state_q)
        IDLE: if (start_i && bytes_i != 0) begin
          src_q <= src_addr_i; dst_q <= dst_addr_i; remaining_q <= bytes_i; state_q <= READ_REQ;
        end
        READ_REQ: if (rd_ready_i) state_q <= READ_RSP;
        READ_RSP: if (rsp_valid_i) begin data_q <= rsp_data_i; state_q <= WRITE_REQ; end
        WRITE_REQ: if (wr_ready_i) begin
          if (remaining_q <= 16) begin remaining_q <= '0; state_q <= IDLE; done_o <= 1'b1; end
          else begin
            src_q <= src_q + 16; dst_q <= dst_q + 16; remaining_q <= remaining_q - 16; state_q <= READ_REQ;
          end
        end
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
