// SPDX-License-Identifier: Apache-2.0
// P2 descriptor/DMA shell around the scalar Split-KV numeric core.
//
// Descriptor v1 mapping used here:
//   q_tokens   = number of valid uint32 block-table entries
//   kv_tokens  = cache length
//   kv_addr    = base of 16-byte token records {value[7:0], score_q11[15:0]}
//   page_addr  = base of packed uint32 physical page ids
//   scale_addr = {score_scale, value_scale, ...}; value_scale is word 1
//   output_addr= BF16 result destination
//   config[15:0]=page size, config[23:16]=splits (descriptor v1)
module p2_dma_operator_b1_output_cut #(
  parameter bit PIPELINED_SOFTMAX = 1'b0
) (
  input  logic         clk_i,
  input  logic         rst_ni,
  input  logic         cmd_valid_i,
  output logic         cmd_ready_o,
  input  logic [511:0] descriptor_i,

  output logic         dma_req_valid_o,
  input  logic         dma_req_ready_i,
  output logic         dma_req_write_o,
  output logic [31:0]  dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o,
  output logic [15:0]  dma_req_wstrb_o,
  input  logic         dma_rsp_valid_i,
  output logic         dma_rsp_ready_o,
  input  logic [127:0] dma_rsp_rdata_i,
  input  logic         dma_rsp_error_i,

  output logic         rsp_valid_o,
  input  logic         rsp_ready_i,
  output logic [7:0]   rsp_status_o,
  output logic [63:0]  rsp_cycles_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_BAD_LENGTH = 8'd2;
  localparam logic [7:0] STATUS_BAD_PAGE = 8'd3;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;

  typedef enum logic [4:0] {
    IDLE, TRACE_INIT, LOAD_SCALE_REQ, LOAD_SCALE_RSP, LOAD_LENGTH_REQ, LOAD_LENGTH_RSP,
    START_CORE, WAIT_TOKEN,
    PAGE_REQ, PAGE_RSP, KV_REQ, KV_RSP, FEED_CORE,
    WRITE_REQ, WRITE_RSP, RESPONSE
  } state_t;
  state_t state_q;

  logic [31:0] cache_len_q, page_count_q, kv_addr_q, page_addr_q;
  logic [31:0] scale_addr_q, output_addr_q, value_scale_q;
  logic [31:0] length_addr_q, page_base_q;
  logic [31:0] batch_count_q, batch_index_q;
  logic [7:0] page_size_q;
  logic [3:0] splits_q;
  logic [31:0] token_q, page_entry_q, physical_page_q, kv_record_addr_q;
  logic [1:0] page_word_q;
  logic signed [15:0] score_q;
  logic signed [7:0] value_q;
  logic core_token_error_q;
  logic trace_mode_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;

  logic core_cmd_valid, core_cmd_ready;
  logic core_token_req_valid, core_token_req_ready;
  logic [31:0] core_token_index;
  logic [3:0] unused_split_id;
  logic core_token_rsp_valid, core_token_rsp_ready;
  logic core_rsp_valid, core_rsp_ready;
  logic [7:0] core_rsp_status;
  logic [63:0] core_rsp_cycles;
  logic signed [31:0] unused_output_q16;
  logic [15:0] core_output_bf16;
  logic signed [15:0] unused_max;
  logic [47:0] unused_sum;
  logic signed [63:0] unused_weighted;

  p2_split_kv_b1_output_cut #(.PIPELINED_SOFTMAX(PIPELINED_SOFTMAX)) u_core (
    .clk_i, .rst_ni,
    .cmd_valid_i(core_cmd_valid), .cmd_ready_o(core_cmd_ready),
    .cache_len_i(cache_len_q), .splits_i(splits_q),
    .page_size_i(page_size_q), .value_scale_i(value_scale_q),
    .token_req_valid_o(core_token_req_valid), .token_req_ready_i(core_token_req_ready),
    .token_index_o(core_token_index), .split_id_o(unused_split_id),
    .token_rsp_valid_i(core_token_rsp_valid), .token_rsp_ready_o(core_token_rsp_ready),
    .token_rsp_score_q11_i(score_q), .token_rsp_value_i(value_q),
    .token_rsp_error_i(core_token_error_q),
    .rsp_valid_o(core_rsp_valid), .rsp_ready_i(core_rsp_ready),
    .rsp_status_o(core_rsp_status), .rsp_cycles_o(core_rsp_cycles),
    .output_q16_o(unused_output_q16), .output_bf16_o(core_output_bf16),
    .merged_max_q11_o(unused_max), .merged_sum_q15_o(unused_sum),
    .merged_weighted_q15_o(unused_weighted)
  );

  assign cmd_ready_o = state_q == IDLE;
  assign core_cmd_valid = state_q == START_CORE;
  assign core_token_req_ready = state_q == WAIT_TOKEN;
  assign core_token_rsp_valid = state_q == FEED_CORE;
  assign core_rsp_ready = state_q == WAIT_TOKEN;

  always_comb begin
    dma_req_valid_o = 1'b0;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = 32'd0;
    dma_req_wdata_o = 128'd0;
    dma_req_wstrb_o = 16'd0;
    dma_rsp_ready_o = 1'b0;
    unique case (state_q)
      LOAD_SCALE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = {scale_addr_q[31:4], 4'b0};
      end
      LOAD_SCALE_RSP: dma_rsp_ready_o = 1'b1;
      LOAD_LENGTH_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = (length_addr_q + (batch_index_q << 2)) & 32'hfffffff0;
      end
      LOAD_LENGTH_RSP: dma_rsp_ready_o = 1'b1;
      PAGE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = {page_entry_q[31:2], 2'b0} & 32'hfffffff0;
      end
      PAGE_RSP: dma_rsp_ready_o = 1'b1;
      KV_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = kv_record_addr_q;
      end
      KV_RSP: dma_rsp_ready_o = 1'b1;
      WRITE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_write_o = 1'b1;
        dma_req_addr_o = {output_addr_q[31:4], 4'b0};
        dma_req_wdata_o = {{112{1'b0}}, core_output_bf16} <<
                          ((output_addr_q[3:0] + batch_index_q[3:0] * 2) * 8);
        dma_req_wstrb_o = 16'h0003 << (output_addr_q[3:0] + batch_index_q[3:0] * 2);
      end
      WRITE_RSP: dma_rsp_ready_o = 1'b1;
      default: begin end
    endcase
  end

  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;

  logic [31:0] logical_page_w, page_offset_w;
  logic [1:0] length_word_w;
  logic [31:0] pages_used_w;
  logic [31:0] next_trace_page_w;
  always_comb begin
    length_word_w = length_addr_q[3:2] + batch_index_q[1:0];
    pages_used_w = (page_size_q == 1) ? cache_len_q :
                   ((cache_len_q + 32'd15) >> 4);
    next_trace_page_w = (token_q + 1'b1) >> 4;
    if (page_size_q == 1) begin
      logical_page_w = core_token_index;
      page_offset_w = 0;
    end else begin
      logical_page_w = core_token_index >> 4;
      page_offset_w = core_token_index & 32'hf;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      cache_len_q <= '0; page_count_q <= '0; kv_addr_q <= '0; page_addr_q <= '0;
      scale_addr_q <= '0; output_addr_q <= '0; value_scale_q <= '0;
      length_addr_q <= '0; page_base_q <= '0;
      batch_count_q <= '0; batch_index_q <= '0;
      page_size_q <= '0; splits_q <= '0; token_q <= '0; page_entry_q <= '0;
      physical_page_q <= '0; kv_record_addr_q <= '0; page_word_q <= '0;
      score_q <= '0; value_q <= '0; status_q <= STATUS_OK;
      core_token_error_q <= 1'b0;
      trace_mode_q <= 1'b0;
      cycles_q <= '0; result_cycles_q <= '0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          cache_len_q <= descriptor_i[127:96];
          page_count_q <= descriptor_i[95:64];
          batch_count_q <= descriptor_i[63:32];
          batch_index_q <= '0;
          page_base_q <= '0;
          kv_addr_q <= descriptor_i[191:160];
          page_addr_q <= descriptor_i[223:192];
          length_addr_q <= descriptor_i[255:224];
          scale_addr_q <= descriptor_i[383:352];
          output_addr_q <= descriptor_i[415:384];
          splits_q <= descriptor_i[467:464];
          page_size_q <= descriptor_i[455:448];
          cycles_q <= '0;
          result_cycles_q <= '0;
          status_q <= STATUS_OK;
          core_token_error_q <= 1'b0;
          trace_mode_q <= descriptor_i[31:24] != 0;
          if (descriptor_i[63:32] == 0 ||
              (descriptor_i[63:32] == 1 &&
               (descriptor_i[127:96] == 0 ||
                {28'd0, descriptor_i[467:464]} > descriptor_i[127:96]))) begin
            status_q <= STATUS_BAD_LENGTH;
            state_q <= RESPONSE;
          end else if (!((descriptor_i[467:464] == 1) ||
                         (descriptor_i[467:464] == 2) ||
                         (descriptor_i[467:464] == 4) ||
                         (descriptor_i[467:464] == 8)) ||
                       descriptor_i[471:468] != 0 ||
                       !((descriptor_i[455:448] == 1) ||
                         (descriptor_i[455:448] == 16)) ||
                       descriptor_i[463:456] != 0 ||
                       descriptor_i[191:160][3:0] != 0 ||
                       descriptor_i[223:192][1:0] != 0 ||
                       (descriptor_i[63:32] > 1 && descriptor_i[255:224][1:0] != 0) ||
                       descriptor_i[383:352][3:0] != 0 ||
                       descriptor_i[415:384][0] != 0) begin
            status_q <= STATUS_BAD_DESCRIPTOR;
            state_q <= RESPONSE;
          end else if (descriptor_i[31:24] != 0) state_q <= TRACE_INIT;
          else state_q <= LOAD_SCALE_REQ;
        end
        TRACE_INIT: begin
          token_q <= '0;
          page_entry_q <= page_addr_q;
          page_word_q <= page_addr_q[3:2];
          if (batch_count_q != 1 || page_size_q != 16 ||
              page_count_q < ((cache_len_q + 32'd15) >> 4)) begin
            status_q <= (cache_len_q == 0) ? STATUS_BAD_LENGTH : STATUS_BAD_PAGE;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else state_q <= PAGE_REQ;
        end
        LOAD_SCALE_REQ: if (dma_req_ready_i) state_q <= LOAD_SCALE_RSP;
        LOAD_SCALE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else begin
            value_scale_q <= dma_rsp_rdata_i[63:32];
            if (batch_count_q > 1) state_q <= LOAD_LENGTH_REQ;
            else state_q <= START_CORE;
          end
        end
        LOAD_LENGTH_REQ: if (dma_req_ready_i) state_q <= LOAD_LENGTH_RSP;
        LOAD_LENGTH_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else begin
            cache_len_q <= dma_rsp_rdata_i[length_word_w*32 +: 32];
            if (dma_rsp_rdata_i[length_word_w*32 +: 32] == 0 ||
                {28'd0, splits_q} > dma_rsp_rdata_i[length_word_w*32 +: 32]) begin
              status_q <= STATUS_BAD_LENGTH;
              state_q <= RESPONSE;
            end else state_q <= START_CORE;
          end
        end
        START_CORE: if (core_cmd_ready) state_q <= WAIT_TOKEN;
        WAIT_TOKEN: begin
          if (core_token_req_valid) begin
            token_q <= core_token_index;
            page_entry_q <= page_addr_q + ((page_base_q + logical_page_w) << 2);
            page_word_q <= (page_addr_q[3:2] + page_base_q[1:0] + logical_page_w[1:0]);
            if (page_base_q + logical_page_w >= page_count_q) begin
              status_q <= STATUS_BAD_PAGE;
              core_token_error_q <= 1'b1;
              score_q <= '0;
              value_q <= '0;
              state_q <= FEED_CORE;
            end else state_q <= PAGE_REQ;
          end else if (core_rsp_valid) begin
            if (status_q == STATUS_OK) status_q <= core_rsp_status;
            if (status_q == STATUS_OK && core_rsp_status == STATUS_OK) state_q <= WRITE_REQ;
            else state_q <= RESPONSE;
          end
        end
        PAGE_REQ: if (dma_req_ready_i) state_q <= PAGE_RSP;
        PAGE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i && trace_mode_q) begin
            status_q <= STATUS_BUS_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (dma_rsp_error_i) begin
            status_q <= STATUS_BUS_ERROR;
            core_token_error_q <= 1'b1;
            score_q <= '0;
            value_q <= '0;
            state_q <= FEED_CORE;
          end
          else begin
            physical_page_q <= dma_rsp_rdata_i[page_word_q*32 +: 32];
            if (dma_rsp_rdata_i[page_word_q*32 +: 32] == 32'hffffffff) begin
              status_q <= STATUS_BAD_PAGE;
              if (trace_mode_q) begin
                result_cycles_q <= cycles_q + 1'b1;
                state_q <= RESPONSE;
              end else begin
                core_token_error_q <= 1'b1;
                score_q <= '0;
                value_q <= '0;
                state_q <= FEED_CORE;
              end
            end else begin
              kv_record_addr_q <= kv_addr_q +
                ((((page_size_q == 1) ? dma_rsp_rdata_i[page_word_q*32 +: 32] :
                    (dma_rsp_rdata_i[page_word_q*32 +: 32] << 4)) +
                   ((page_size_q == 1) ? 32'd0 : {28'd0, token_q[3:0]})) << 4);
              state_q <= KV_REQ;
            end
          end
        end
        KV_REQ: if (dma_req_ready_i) state_q <= KV_RSP;
        KV_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i && trace_mode_q) begin
            status_q <= STATUS_BUS_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (dma_rsp_error_i) begin
            status_q <= STATUS_BUS_ERROR;
            core_token_error_q <= 1'b1;
            score_q <= '0;
            value_q <= '0;
            state_q <= FEED_CORE;
          end
          else if (trace_mode_q) begin
            if (token_q + 1'b1 == cache_len_q) begin
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              token_q <= token_q + 1'b1;
              page_entry_q <= page_addr_q + (next_trace_page_w << 2);
              page_word_q <= page_addr_q[3:2] + next_trace_page_w[1:0];
              state_q <= PAGE_REQ;
            end
          end else begin
            score_q <= dma_rsp_rdata_i[15:0];
            value_q <= dma_rsp_rdata_i[23:16];
            state_q <= FEED_CORE;
          end
        end
        FEED_CORE: if (core_token_rsp_ready) state_q <= WAIT_TOKEN;
        WRITE_REQ: if (dma_req_ready_i) state_q <= WRITE_RSP;
        WRITE_RSP: if (dma_rsp_valid_i) begin
          result_cycles_q <= cycles_q + core_rsp_cycles + 1'b1;
          if (dma_rsp_error_i) begin
            status_q <= STATUS_BUS_ERROR;
            state_q <= RESPONSE;
          end else if (batch_index_q + 1'b1 < batch_count_q) begin
            page_base_q <= page_base_q + pages_used_w;
            batch_index_q <= batch_index_q + 1'b1;
            state_q <= LOAD_LENGTH_REQ;
          end else state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
