// SPDX-License-Identifier: Apache-2.0
// Traffic-only P2 profile for P2-32/P2-33.  It reads every real page-table
// entry and compressed-KV record but deliberately performs no Split-KV math.
module p2_trace_operator_b0 (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [511:0] descriptor_i,
  output logic dma_req_valid_o, input logic dma_req_ready_i,
  output logic dma_req_write_o, output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o, output logic [15:0] dma_req_wstrb_o,
  input logic dma_rsp_valid_i, output logic dma_rsp_ready_o,
  input logic [127:0] dma_rsp_rdata_i, input logic dma_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  localparam logic [7:0] STATUS_OK = 0, STATUS_BAD_DESCRIPTOR = 1,
    STATUS_BAD_LENGTH = 2, STATUS_BAD_PAGE = 3, STATUS_BUS_ERROR = 5;
  typedef enum logic [2:0] {IDLE, PAGE_REQ, PAGE_RSP, KV_REQ, KV_RSP, RESPONSE} state_t;
  state_t state_q;
  logic [31:0] cache_len_q, page_count_q, kv_addr_q, page_addr_q, token_q;
  logic [31:0] page_entry_addr_q, kv_record_addr_q;
  logic [1:0] page_word_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;
  logic [31:0] physical_page_w;
  logic [31:0] next_logical_page_w;

  assign physical_page_w = dma_rsp_rdata_i[page_word_q*32 +: 32];
  assign next_logical_page_w = (token_q + 1'b1) >> 4;
  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;

  always_comb begin
    dma_req_valid_o = state_q == PAGE_REQ || state_q == KV_REQ;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = state_q == PAGE_REQ
      ? (page_entry_addr_q & 32'hfffffff0) : kv_record_addr_q;
    dma_req_wdata_o = '0;
    dma_req_wstrb_o = '0;
    dma_rsp_ready_o = state_q == PAGE_RSP || state_q == KV_RSP;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; cache_len_q <= 0; page_count_q <= 0;
      kv_addr_q <= 0; page_addr_q <= 0; token_q <= 0;
      page_entry_addr_q <= 0; kv_record_addr_q <= 0; page_word_q <= 0;
      status_q <= STATUS_OK; cycles_q <= 0; result_cycles_q <= 0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          cache_len_q <= descriptor_i[127:96];
          page_count_q <= descriptor_i[95:64];
          kv_addr_q <= descriptor_i[191:160];
          page_addr_q <= descriptor_i[223:192];
          token_q <= 0;
          page_entry_addr_q <= descriptor_i[223:192];
          page_word_q <= descriptor_i[223:192][3:2];
          cycles_q <= 0; result_cycles_q <= 0; status_q <= STATUS_OK;
          if (descriptor_i[63:32] != 1 ||
              !((descriptor_i[127:96] == 16384) ||
                (descriptor_i[127:96] == 61519))) begin
            status_q <= STATUS_BAD_LENGTH; state_q <= RESPONSE;
          end else if (descriptor_i[31:24] == 0 ||
                       descriptor_i[467:464] != 8 ||
                       descriptor_i[471:468] != 0 ||
                       descriptor_i[455:448] != 16 ||
                       descriptor_i[463:456] != 0 ||
                       descriptor_i[191:160][3:0] != 0 ||
                       descriptor_i[223:192][1:0] != 0) begin
            status_q <= STATUS_BAD_DESCRIPTOR; state_q <= RESPONSE;
          end else if (descriptor_i[95:64] < ((descriptor_i[127:96] + 15) >> 4)) begin
            status_q <= STATUS_BAD_PAGE; state_q <= RESPONSE;
          end else state_q <= PAGE_REQ;
        end
        PAGE_REQ: if (dma_req_ready_i) state_q <= PAGE_RSP;
        PAGE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin
            status_q <= STATUS_BUS_ERROR; result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (physical_page_w == 32'hffffffff) begin
            status_q <= STATUS_BAD_PAGE; result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else begin
            kv_record_addr_q <= kv_addr_q +
              (((physical_page_w << 4) + {28'd0, token_q[3:0]}) << 4);
            state_q <= KV_REQ;
          end
        end
        KV_REQ: if (dma_req_ready_i) state_q <= KV_RSP;
        KV_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin
            status_q <= STATUS_BUS_ERROR; result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (token_q + 1'b1 == cache_len_q) begin
            result_cycles_q <= cycles_q + 1'b1; state_q <= RESPONSE;
          end else begin
            token_q <= token_q + 1'b1;
            page_entry_addr_q <= page_addr_q + (next_logical_page_w << 2);
            page_word_q <= page_addr_q[3:2] + next_logical_page_w[1:0];
            state_q <= PAGE_REQ;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
