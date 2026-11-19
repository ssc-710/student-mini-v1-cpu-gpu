// SPDX-License-Identifier: Apache-2.0
module paged_address_gen (
  input logic clk_i, input logic rst_ni, input logic start_i,
  input logic [31:0] token_count_i, input logic [4:0] page_shift_i,
  output logic page_req_valid_o, input logic page_req_ready_i, output logic [31:0] logical_page_o,
  input logic page_id_valid_i, output logic page_id_ready_o, input logic [31:0] physical_page_i,
  output logic out_valid_o, input logic out_ready_i,
  output logic [31:0] page_o, output logic [15:0] offset_o, output logic last_o
);
  typedef enum logic [1:0] {IDLE, REQUEST_PAGE, WAIT_PAGE, EMIT} state_t;
  state_t state_q;
  logic [31:0] token_q, count_q, page_q;
  logic [4:0] shift_q;
  logic [31:0] page_mask;

  assign page_mask = (32'h1 << shift_q) - 1'b1;
  assign page_req_valid_o = state_q == REQUEST_PAGE;
  assign logical_page_o = token_q >> shift_q;
  assign page_id_ready_o = state_q == WAIT_PAGE;
  assign out_valid_o = state_q == EMIT;
  assign page_o = page_q;
  assign offset_o = token_q[15:0] & page_mask[15:0];
  assign last_o = token_q + 1'b1 == count_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin state_q <= IDLE; token_q <= '0; count_q <= '0; shift_q <= '0; page_q <= '0; end
    else begin
      unique case (state_q)
        IDLE: if (start_i && token_count_i != 0) begin
          token_q <= '0; count_q <= token_count_i; shift_q <= page_shift_i; state_q <= REQUEST_PAGE;
        end
        REQUEST_PAGE: if (page_req_ready_i) state_q <= WAIT_PAGE;
        WAIT_PAGE: if (page_id_valid_i) begin page_q <= physical_page_i; state_q <= EMIT; end
        EMIT: if (out_ready_i) begin
          if (last_o) state_q <= IDLE;
          else begin
            token_q <= token_q + 1'b1;
            if (((token_q + 1'b1) & page_mask) == 0) state_q <= REQUEST_PAGE;
          end
        end
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
