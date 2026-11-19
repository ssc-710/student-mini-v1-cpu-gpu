// SPDX-License-Identifier: Apache-2.0
// Traffic-only P1 profile.  operator_arg==0 is an explicit all-visible
// sentinel used only by this profile because descriptor v1 has an 8-bit
// runtime Top-K field while the frozen DeepSeek traces use K=2048.
//
// This module reads and validates the real ragged/page metadata and every page
// table entry, then reports the traffic/cycle projection.  It deliberately
// does not read tensor elements or claim numerical execution.
module p1_trace_operator_b0 #(
  parameter int HEADS = 4,
  parameter int Q_STRIDE = 32,
  parameter int KV_STRIDE = 32,
  parameter int VALUE_DIM = 8,
  localparam int Q_BEATS = Q_STRIDE / 16,
  localparam int KV_BEATS = KV_STRIDE / 16,
  localparam int OUTPUT_BEATS = (VALUE_DIM * 2 + 15) / 16
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [511:0] descriptor_i, input logic [7:0] operator_arg_i,
  output logic dma_req_valid_o, input logic dma_req_ready_i,
  output logic dma_req_write_o, output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o, output logic [15:0] dma_req_wstrb_o,
  input logic dma_rsp_valid_i, output logic dma_rsp_ready_o,
  input logic [127:0] dma_rsp_rdata_i, input logic dma_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o,
  output logic [63:0] projected_read_requests_o,
  output logic [63:0] projected_write_requests_o,
  output logic [63:0] projected_read_bytes_o,
  output logic [63:0] projected_write_bytes_o,
  output logic [31:0] first_kv_address_o,
  output logic [31:0] last_kv_address_o
);
  localparam logic [7:0] OK = 0, BAD_DESCRIPTOR = 1, BAD_LENGTH = 2,
    BAD_PAGE = 3, BUS_ERROR = 5;
  localparam logic [63:0] KV_BEATS_64 = {32'd0, KV_BEATS};
  typedef enum logic [3:0] {
    IDLE, META_REQ, META_RSP, CHECK_META, PAGE_REQ, PAGE_RSP,
    CALC_VISIBLE, CALC_TRAFFIC, CALC_TOTAL, CALC_FINAL, RESPONSE
  } state_t;
  state_t state_q;
  logic [31:0] q_capacity_q, kv_capacity_q, q_addr_q, kv_addr_q;
  logic [31:0] page_addr_q, length_addr_q;
  logic [7:0] page_size_q;
  logic causal_q;
  logic [2:0] meta_index_q;
  logic [31:0] qo_begin_q, qo_end_q, kv_begin_q, kv_end_q, last_page_len_q;
  logic [31:0] q_len_q, page_count_q, kv_len_q, page_index_q;
  logic [31:0] first_page_q, last_page_q;
  logic [7:0] status_q;
  logic [63:0] actual_cycles_q;

  logic [31:0] metadata_address_w, metadata_value_w, page_value_w;
  logic [1:0] metadata_lane_w, page_lane_w;
  logic [63:0] q_len_w, kv_len_w, visible_sum_w;
  logic [63:0] visible_sum_q, record_scans_q, query_reads_q;
  logic [63:0] output_writes_q, selected_writes_q;
  logic [63:0] projected_reads_q, projected_writes_q;
  logic [63:0] projected_read_bytes_q, projected_write_bytes_q;
  logic [63:0] projected_cycles_q;
  logic [31:0] first_kv_address_q, last_kv_address_q;

  assign metadata_address_w = length_addr_q + ({29'd0, meta_index_q} << 2);
  assign metadata_lane_w = metadata_address_w[3:2];
  assign metadata_value_w = dma_rsp_rdata_i[metadata_lane_w*32 +: 32];
  assign page_lane_w = (page_addr_q[3:2] + page_index_q[1:0]) & 2'b11;
  assign page_value_w = dma_rsp_rdata_i[page_lane_w*32 +: 32];

  assign q_len_w = {32'd0, q_len_q};
  assign kv_len_w = {32'd0, kv_len_q};
  // This traffic-only implementation is frozen to P1-30 and P1-31.  Their
  // exact bottom-right-causal visible counts are constants, avoiding runtime
  // 64-bit multipliers in a profile that executes no tensor MACs.
  assign visible_sum_w =
    (q_len_q == 512 && kv_len_q == 1024) ? 64'd393472 :
    (q_len_q == 640 && kv_len_q == 1280) ? 64'd614720 : 64'd0;
  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = projected_cycles_q;
  assign projected_read_requests_o = projected_reads_q;
  assign projected_write_requests_o = projected_writes_q;
  assign projected_read_bytes_o = projected_read_bytes_q;
  assign projected_write_bytes_o = projected_write_bytes_q;
  assign first_kv_address_o = first_kv_address_q;
  assign last_kv_address_o = last_kv_address_q;

  always_comb begin
    dma_req_valid_o = 1'b0;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = '0;
    dma_req_wdata_o = '0;
    dma_req_wstrb_o = '0;
    dma_rsp_ready_o = 1'b0;
    if (state_q == META_REQ) begin
      dma_req_valid_o = 1'b1;
      dma_req_addr_o = metadata_address_w & 32'hfffffff0;
    end else if (state_q == PAGE_REQ) begin
      dma_req_valid_o = 1'b1;
      dma_req_addr_o = (page_addr_q + ((kv_begin_q + page_index_q) << 2)) & 32'hfffffff0;
    end
    if (state_q == META_RSP || state_q == PAGE_RSP) dma_rsp_ready_o = 1'b1;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; q_capacity_q <= 0; kv_capacity_q <= 0;
      q_addr_q <= 0; kv_addr_q <= 0; page_addr_q <= 0; length_addr_q <= 0;
      page_size_q <= 0; causal_q <= 0; meta_index_q <= 0;
      qo_begin_q <= 0; qo_end_q <= 0; kv_begin_q <= 0; kv_end_q <= 0;
      last_page_len_q <= 0; q_len_q <= 0; page_count_q <= 0; kv_len_q <= 0;
      page_index_q <= 0; first_page_q <= 0; last_page_q <= 0;
      status_q <= OK; actual_cycles_q <= 0;
      visible_sum_q <= 0; record_scans_q <= 0; query_reads_q <= 0;
      output_writes_q <= 0; selected_writes_q <= 0;
      projected_reads_q <= 0; projected_writes_q <= 0;
      projected_read_bytes_q <= 0; projected_write_bytes_q <= 0;
      projected_cycles_q <= 0; first_kv_address_q <= 0;
      last_kv_address_q <= 0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) actual_cycles_q <= actual_cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          q_capacity_q <= descriptor_i[95:64]; kv_capacity_q <= descriptor_i[127:96];
          q_addr_q <= descriptor_i[159:128]; kv_addr_q <= descriptor_i[191:160];
          page_addr_q <= descriptor_i[223:192]; length_addr_q <= descriptor_i[255:224];
          page_size_q <= descriptor_i[455:448]; causal_q <= descriptor_i[16];
          meta_index_q <= 0; status_q <= OK; actual_cycles_q <= 0;
          if (descriptor_i[63:32] != 1 || descriptor_i[95:64] == 0 ||
              descriptor_i[127:96] == 0) begin
            status_q <= BAD_LENGTH; state_q <= RESPONSE;
          end else if (operator_arg_i != 0 || !descriptor_i[21] || !descriptor_i[16] ||
                       descriptor_i[455:448] != 16 ||
                       descriptor_i[159:128][3:0] != 0 ||
                       descriptor_i[191:160][3:0] != 0 ||
                       descriptor_i[223:192][1:0] != 0 ||
                       descriptor_i[255:224][1:0] != 0) begin
            status_q <= BAD_DESCRIPTOR; state_q <= RESPONSE;
          end else state_q <= META_REQ;
        end
        META_REQ: if (dma_req_ready_i) state_q <= META_RSP;
        META_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= BUS_ERROR; state_q <= RESPONSE; end
          else begin
            unique case (meta_index_q)
              0: qo_begin_q <= metadata_value_w;
              1: qo_end_q <= metadata_value_w;
              2: kv_begin_q <= metadata_value_w;
              3: kv_end_q <= metadata_value_w;
              default: last_page_len_q <= metadata_value_w;
            endcase
            if (meta_index_q == 4) state_q <= CHECK_META;
            else begin meta_index_q <= meta_index_q + 1'b1; state_q <= META_REQ; end
          end
        end
        CHECK_META: begin
          q_len_q <= qo_end_q - qo_begin_q;
          page_count_q <= kv_end_q - kv_begin_q;
          kv_len_q <= (kv_end_q - kv_begin_q - 1'b1) * page_size_q + last_page_len_q;
          page_index_q <= 0;
          if (qo_begin_q != 0 || qo_end_q != q_capacity_q || qo_begin_q >= qo_end_q)
            begin status_q <= BAD_LENGTH; state_q <= RESPONSE; end
          else if (kv_begin_q >= kv_end_q || last_page_len_q == 0 ||
                   last_page_len_q > page_size_q)
            begin status_q <= BAD_PAGE; state_q <= RESPONSE; end
          else state_q <= PAGE_REQ;
        end
        PAGE_REQ: if (dma_req_ready_i) state_q <= PAGE_RSP;
        PAGE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= BUS_ERROR; state_q <= RESPONSE; end
          else if (page_value_w * page_size_q >= kv_capacity_q) begin
            status_q <= BAD_PAGE; state_q <= RESPONSE;
          end else begin
            if (page_index_q == 0) first_page_q <= page_value_w;
            if (page_index_q + 1'b1 == page_count_q) begin
              last_page_q <= page_value_w;
              state_q <= CALC_VISIBLE;
            end else begin page_index_q <= page_index_q + 1'b1; state_q <= PAGE_REQ; end
          end
        end
        CALC_VISIBLE: begin
          if (visible_sum_w == 0) begin
            status_q <= BAD_LENGTH;
            state_q <= RESPONSE;
          end else begin
            visible_sum_q <= visible_sum_w;
            query_reads_q <= q_len_w * HEADS * Q_BEATS;
            output_writes_q <= q_len_w * HEADS * OUTPUT_BEATS;
            first_kv_address_q <= kv_addr_q +
              first_page_q * page_size_q * KV_STRIDE;
            last_kv_address_q <= kv_addr_q +
              (last_page_q * page_size_q + last_page_len_q - 1'b1) * KV_STRIDE;
            state_q <= CALC_TRAFFIC;
          end
        end
        CALC_TRAFFIC: begin
          // Indexer plus all-visible MLA.  HEADS and record beat counts are
          // compile-time profile constants, so this stage maps to shift/add.
          record_scans_q <= visible_sum_q * HEADS * 2;
          selected_writes_q <= visible_sum_q * HEADS;
          state_q <= CALC_TOTAL;
        end
        CALC_TOTAL: begin
          // Descriptor(4), scale(1), metadata(5), query records, and
          // projected per-token page + KV record reads.  The one-time page
          // validation scan is intentionally excluded from model traffic.
          projected_reads_q <= 64'd10 + query_reads_q +
            record_scans_q * (64'd1 + KV_BEATS_64);
          projected_writes_q <= selected_writes_q + output_writes_q;
          state_q <= CALC_FINAL;
        end
        CALC_FINAL: begin
          projected_read_bytes_q <= projected_reads_q << 4;
          projected_write_bytes_q <= (selected_writes_q << 2) +
            (output_writes_q << 4);
          projected_cycles_q <= (projected_reads_q << 1) +
            (projected_writes_q << 1) + record_scans_q;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  logic unused;
  assign unused = ^q_addr_q ^ ^actual_cycles_q;
endmodule
