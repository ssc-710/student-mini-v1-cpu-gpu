// SPDX-License-Identifier: Apache-2.0
// P1 descriptor/DMA shell for the frozen INT8 query/KV record layout.
//
// q_tokens is the total number of ragged queries and every query is evaluated
// for each compiled head.  Records are 16-byte aligned and padded to a
// 16-byte stride:
//   query = q_nope | q_pe | index_q
//   KV    = cKV     | kPE  | index_k
// length_addr points to qo_indptr[B+1], kv_indptr[B+1], last_page_len[B].
module p1_dma_operator_b13_beat_width #(
  parameter int HEADS = 4,
  parameter int NOPE_DIM = 8,
  parameter int ROPE_DIM = 4,
  parameter int INDEX_DIM = 8,
  parameter int VALUE_DIM = 8,
  parameter int K_MAX = 32,
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit PIPELINED_SCORE_SCALE = 1'b0,
  parameter bit PIPELINED_PAGE_VALIDATE = 1'b0,
  parameter bit PIPELINED_META_LENGTH = 1'b0,
  parameter bit PIPELINED_VISIBLE = 1'b1,
  localparam int Q_BYTES = NOPE_DIM + ROPE_DIM + INDEX_DIM,
  localparam int KV_BYTES = NOPE_DIM + ROPE_DIM + INDEX_DIM,
  localparam int Q_STRIDE = ((Q_BYTES + 15) / 16) * 16,
  localparam int KV_STRIDE = ((KV_BYTES + 15) / 16) * 16,
  localparam int Q_BEATS = Q_STRIDE / 16,
  localparam int KV_BEATS = KV_STRIDE / 16,
  localparam int Q_BEAT_WIDTH = Q_BEATS <= 1 ? 1 : $clog2(Q_BEATS),
  localparam int KV_BEAT_WIDTH = KV_BEATS <= 1 ? 1 : $clog2(KV_BEATS),
  localparam int K_WIDTH = $clog2(K_MAX + 1)
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic cmd_valid_i,
  output logic cmd_ready_o,
  input  logic [511:0] descriptor_i,
  input  logic [7:0] operator_arg_i,

  output logic dma_req_valid_o,
  input  logic dma_req_ready_i,
  output logic dma_req_write_o,
  output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o,
  output logic [15:0] dma_req_wstrb_o,
  input  logic dma_rsp_valid_i,
  output logic dma_rsp_ready_o,
  input  logic [127:0] dma_rsp_rdata_i,
  input  logic dma_rsp_error_i,

  output logic rsp_valid_o,
  input  logic rsp_ready_i,
  output logic [7:0] rsp_status_o,
  output logic [63:0] rsp_cycles_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_BAD_LENGTH = 8'd2;
  localparam logic [7:0] STATUS_BAD_PAGE = 8'd3;
  localparam logic [7:0] STATUS_NUMERIC_ERROR = 8'd4;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;

  typedef enum logic [5:0] {
    IDLE, SCALE_REQ, SCALE_RSP, CHECK_SCALE, META_REQ, META_RSP, CHECK_META,
    CHECK_META_LENGTH,
    QUERY_REQ, QUERY_RSP, PREP_VISIBLE, VISIBLE_SUBTRACT, VISIBLE_CLAMP,
    START_CORE, WAIT_CORE,
    PAGE_REQ, PAGE_RSP, PAGE_VALIDATE, KV_REQ, KV_RSP,
    DOT_START, DOT_FEED, DOT_WAIT, SCORE_START, SCORE_WAIT,
    FEED_CORE, CAPTURE_CORE,
    TOKEN_WRITE_REQ, TOKEN_WRITE_RSP, OUTPUT_WRITE_REQ, OUTPUT_WRITE_RSP,
    RESPONSE
  } state_t;
  state_t state_q;

  logic [31:0] batch_count_q, batch_q;
  logic [31:0] q_count_q, kv_capacity_q, q_addr_q, kv_addr_q, page_addr_q;
  logic [31:0] length_addr_q, aux0_addr_q, scale_addr_q, output_addr_q;
  logic [7:0] page_size_q, topk_q;
  logic causal_q;
  logic [31:0] qo_begin_q, qo_end_q, kv_begin_q, kv_end_q, last_page_len_q;
  logic [31:0] q_len_q, page_count_q, kv_len_q;
  logic [2:0] meta_index_q;
  logic [31:0] query_q, head_q, visible_q;
  logic [32:0] visible_sum_q, visible_candidate_q;
  logic visible_underflow_q;
  // B13 timing/area cut: these counters only encode [0, BEATS-1].  Keeping
  // them at 32 bits created a false-wide increment/control cone whose upper
  // bits became the measured endpoint after B12.
  logic [Q_BEAT_WIDTH-1:0] query_beat_q;
  logic [KV_BEAT_WIDTH-1:0] kv_beat_q;
  logic [31:0] requested_token_q, logical_page_q, page_offset_q, page_value_q;
  logic request_mla_q, request_error_q;
  logic [31:0] physical_page_q;
  logic [31:0] token_write_q, output_beat_q;
  logic [31:0] index_scale_q, mla_scale_q, value_scale_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;

  logic signed [7:0] query_record [0:Q_STRIDE-1];
  logic signed [7:0] kv_record [0:KV_STRIDE-1];

  logic core_cmd_valid, core_cmd_ready;
  logic core_mem_req_valid, core_mem_req_ready, core_mem_req_mla;
  logic [31:0] core_mem_req_token;
  logic core_mem_rsp_valid, core_mem_rsp_ready;
  logic signed [15:0] core_mem_index_score, core_mem_mla_score;
  logic signed [VALUE_DIM*8-1:0] core_mem_value;
  logic core_rsp_valid, core_rsp_ready;
  logic [7:0] core_rsp_status;
  logic [63:0] unused_core_cycles;
  logic signed [31:0] unused_core_q16;
  logic [15:0] unused_core_bf16;
  logic signed [VALUE_DIM*32-1:0] core_q16_vector;
  logic [VALUE_DIM*16-1:0] core_bf16_vector;
  logic [K_WIDTH-1:0] core_selected_count;
  logic [K_MAX*32-1:0] core_selected_tokens;

  p1_dsa_mla_b2_bf16_pipeline #(
    .K_MAX(K_MAX), .VALUE_DIM(VALUE_DIM),
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX)
  ) u_core (
    .clk_i, .rst_ni,
    .cmd_valid_i(core_cmd_valid), .cmd_ready_o(core_cmd_ready),
    .visible_count_i(visible_q), .topk_i(topk_q), .value_scale_i(value_scale_q),
    .mem_req_valid_o(core_mem_req_valid), .mem_req_ready_i(core_mem_req_ready),
    .mem_req_mla_o(core_mem_req_mla), .mem_req_token_o(core_mem_req_token),
    .mem_rsp_valid_i(core_mem_rsp_valid), .mem_rsp_ready_o(core_mem_rsp_ready),
    .mem_rsp_index_score_q11_i(core_mem_index_score),
    .mem_rsp_mla_score_q11_i(core_mem_mla_score), .mem_rsp_value_i(core_mem_value),
    .mem_rsp_error_i(request_error_q),
    .rsp_valid_o(core_rsp_valid), .rsp_ready_i(core_rsp_ready),
    .rsp_status_o(core_rsp_status), .rsp_cycles_o(unused_core_cycles),
    .output_q16_o(unused_core_q16), .output_bf16_o(unused_core_bf16),
    .output_q16_vector_o(core_q16_vector), .output_bf16_vector_o(core_bf16_vector),
    .selected_count_o(core_selected_count), .selected_tokens_o(core_selected_tokens)
  );

  logic dot_cmd_valid, dot_cmd_ready, dot_in_valid, dot_in_ready;
  logic [15:0] dot_length_q, dot_index_q;
  logic signed [7:0] dot_lhs, dot_rhs;
  logic dot_rsp_valid, dot_rsp_ready, dot_length_error;
  logic signed [31:0] dot_result;
  int8_dot_serial u_dot (
    .clk_i, .rst_ni, .cmd_valid_i(dot_cmd_valid), .cmd_ready_o(dot_cmd_ready),
    .length_i(dot_length_q), .in_valid_i(dot_in_valid), .in_ready_o(dot_in_ready),
    .lhs_i(dot_lhs), .rhs_i(dot_rhs), .rsp_valid_o(dot_rsp_valid),
    .rsp_ready_i(dot_rsp_ready), .result_o(dot_result), .length_error_o(dot_length_error)
  );

  logic signed [15:0] index_score_w, mla_score_w;
  logic index_scale_valid, mla_scale_valid, value_scale_valid;
  int32_scale_to_q5_11 u_index_scale (
    .value_i(dot_result), .scale_i(index_scale_q),
    .q5_11_o(index_score_w), .scale_valid_o(index_scale_valid));
  int32_scale_to_q5_11 u_mla_scale (
    .value_i(dot_result), .scale_i(mla_scale_q),
    .q5_11_o(mla_score_w), .scale_valid_o(mla_scale_valid));
  fp32_scale_check u_value_scale_check (
    .scale_i(value_scale_q), .valid_o(value_scale_valid));

  logic score_cmd_ready, score_rsp_valid, score_rsp_ready, score_scale_valid;
  logic signed [15:0] score_pipeline_q11;
  int32_scale_to_q5_11_pipeline u_score_pipeline (
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_SCORE_SCALE && state_q == SCORE_START),
    .cmd_ready_o(score_cmd_ready), .value_i(dot_result),
    .scale_i(request_mla_q ? mla_scale_q : index_scale_q),
    .rsp_valid_o(score_rsp_valid), .rsp_ready_i(score_rsp_ready),
    .q5_11_o(score_pipeline_q11), .scale_valid_o(score_scale_valid)
  );

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;
  assign core_cmd_valid = state_q == START_CORE;
  assign core_mem_req_ready = state_q == WAIT_CORE;
  assign core_mem_rsp_valid = state_q == FEED_CORE;
  assign core_rsp_ready = state_q == CAPTURE_CORE;
  assign dot_cmd_valid = state_q == DOT_START;
  assign dot_in_valid = state_q == DOT_FEED;
  assign dot_rsp_ready = state_q == DOT_WAIT;
  assign score_rsp_ready = state_q == SCORE_WAIT;

  integer value_lane;
  always_comb begin
    core_mem_value = '0;
    for (value_lane = 0; value_lane < VALUE_DIM; value_lane = value_lane + 1)
      core_mem_value[value_lane*8 +: 8] = kv_record[value_lane];
    if (request_mla_q) begin
      if (dot_index_q < NOPE_DIM) begin
        dot_lhs = query_record[dot_index_q];
        dot_rhs = kv_record[dot_index_q];
      end else begin
        dot_lhs = query_record[dot_index_q];
        dot_rhs = kv_record[dot_index_q];
      end
    end else begin
      dot_lhs = query_record[NOPE_DIM + ROPE_DIM + dot_index_q];
      dot_rhs = kv_record[NOPE_DIM + ROPE_DIM + dot_index_q];
    end
  end

  always_comb begin
    dma_req_valid_o = 1'b0;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = '0;
    dma_req_wdata_o = '0;
    dma_req_wstrb_o = '0;
    dma_rsp_ready_o = 1'b0;
    unique case (state_q)
      SCALE_REQ: begin dma_req_valid_o = 1'b1; dma_req_addr_o = scale_addr_q; end
      SCALE_RSP, META_RSP, QUERY_RSP, PAGE_RSP, KV_RSP,
      TOKEN_WRITE_RSP, OUTPUT_WRITE_RSP: dma_rsp_ready_o = 1'b1;
      META_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = meta_address_w & 32'hfffffff0;
      end
      QUERY_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = q_addr_q + ((query_q * HEADS + head_q) * Q_STRIDE) +
                         (query_beat_q << 4);
      end
      PAGE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = (page_addr_q + ((kv_begin_q + logical_page_q) << 2)) &
                         32'hfffffff0;
      end
      KV_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = kv_addr_q +
                         ((physical_page_q * page_size_q + page_offset_q) * KV_STRIDE) +
                         (kv_beat_q << 4);
      end
      TOKEN_WRITE_REQ: begin
        if (core_selected_count != 0) begin
          dma_req_valid_o = 1'b1;
          dma_req_write_o = 1'b1;
          dma_req_addr_o = (aux0_addr_q +
            ((((query_q * HEADS + head_q) * K_MAX) + token_write_q) << 2)) & 32'hfffffff0;
          dma_req_wdata_o = 128'(core_selected_tokens[token_write_q*32 +: 32]) <<
            (((aux0_addr_q[3:2] + token_write_q[1:0]) & 2'b11) * 32);
          dma_req_wstrb_o = 16'h000f <<
            ((((aux0_addr_q[3:2] + token_write_q[1:0]) & 2'b11) * 4));
        end
      end
      OUTPUT_WRITE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_write_o = 1'b1;
        dma_req_addr_o = output_addr_q +
          ((query_q * HEADS + head_q) * VALUE_DIM * 2) + (output_beat_q << 4);
        dma_req_wdata_o = core_bf16_vector >> (output_beat_q * 128);
        dma_req_wstrb_o = (VALUE_DIM * 2 - output_beat_q * 16 >= 16) ? 16'hffff :
          (16'hffff >> (16 - (VALUE_DIM * 2 - output_beat_q * 16)));
      end
      default: begin end
    endcase
  end

  logic [1:0] meta_word_w;
  logic [31:0] meta_value_w, meta_address_w, meta_linear_index_w;
  logic [31:0] page_value_w;
  always_comb begin
    unique case (meta_index_q)
      0: meta_linear_index_w = batch_q;
      1: meta_linear_index_w = batch_q + 1'b1;
      2: meta_linear_index_w = batch_count_q + 1'b1 + batch_q;
      3: meta_linear_index_w = batch_count_q + 2'd2 + batch_q;
      default: meta_linear_index_w = (batch_count_q + 1'b1) * 2 + batch_q;
    endcase
    meta_address_w = length_addr_q + (meta_linear_index_w << 2);
    meta_word_w = meta_address_w[3:2];
    meta_value_w = dma_rsp_rdata_i[meta_word_w*32 +: 32];
    page_value_w = dma_rsp_rdata_i[
      ((page_addr_q[3:2] + kv_begin_q[1:0] + logical_page_q[1:0]) & 2'b11)*32 +: 32
    ];
  end

  integer lane;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      batch_count_q <= '0; batch_q <= '0;
      q_count_q <= '0; kv_capacity_q <= '0; q_addr_q <= '0; kv_addr_q <= '0;
      page_addr_q <= '0; length_addr_q <= '0; aux0_addr_q <= '0;
      scale_addr_q <= '0; output_addr_q <= '0; page_size_q <= '0; topk_q <= '0;
      causal_q <= 1'b0; qo_begin_q <= '0; qo_end_q <= '0; kv_begin_q <= '0;
      kv_end_q <= '0; last_page_len_q <= '0; q_len_q <= '0; page_count_q <= '0;
      kv_len_q <= '0; meta_index_q <= '0; query_q <= '0; head_q <= '0;
      visible_q <= '0; visible_sum_q <= '0; visible_candidate_q <= '0;
      visible_underflow_q <= 1'b0; query_beat_q <= '0; kv_beat_q <= '0;
      requested_token_q <= '0; logical_page_q <= '0; page_offset_q <= '0;
      page_value_q <= '0;
      request_mla_q <= 1'b0; request_error_q <= 1'b0; physical_page_q <= '0;
      token_write_q <= '0; output_beat_q <= '0; index_scale_q <= '0;
      mla_scale_q <= '0; value_scale_q <= '0; status_q <= STATUS_OK;
      cycles_q <= '0; result_cycles_q <= '0; dot_length_q <= '0; dot_index_q <= '0;
      core_mem_index_score <= '0; core_mem_mla_score <= '0;
      for (lane = 0; lane < Q_STRIDE; lane = lane + 1) query_record[lane] <= '0;
      for (lane = 0; lane < KV_STRIDE; lane = lane + 1) kv_record[lane] <= '0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          batch_count_q <= descriptor_i[63:32];
          batch_q <= '0;
          q_count_q <= descriptor_i[95:64];
          kv_capacity_q <= descriptor_i[127:96];
          q_addr_q <= descriptor_i[159:128]; kv_addr_q <= descriptor_i[191:160];
          page_addr_q <= descriptor_i[223:192]; length_addr_q <= descriptor_i[255:224];
          aux0_addr_q <= descriptor_i[287:256]; scale_addr_q <= descriptor_i[383:352];
          output_addr_q <= descriptor_i[415:384]; page_size_q <= descriptor_i[455:448];
          topk_q <= operator_arg_i; causal_q <= descriptor_i[16];
          cycles_q <= '0; result_cycles_q <= '0; status_q <= STATUS_OK;
          meta_index_q <= '0; query_q <= '0; head_q <= '0;
          if (descriptor_i[63:32] == 0 || descriptor_i[95:64] == 0 ||
              descriptor_i[127:96] == 0) begin
            status_q <= STATUS_BAD_LENGTH; state_q <= RESPONSE;
          end else if (operator_arg_i == 0 || operator_arg_i > K_MAX ||
                       !((descriptor_i[455:448] == 1) ||
                         (descriptor_i[455:448] == 4) ||
                         (descriptor_i[455:448] == 16)) ||
                       descriptor_i[463:456] != 0 ||
                       descriptor_i[159:128][3:0] != 0 ||
                       descriptor_i[191:160][3:0] != 0 ||
                       descriptor_i[223:192][1:0] != 0 ||
                       descriptor_i[255:224][1:0] != 0 ||
                       descriptor_i[287:256][1:0] != 0 ||
                       descriptor_i[383:352][3:0] != 0 ||
                       descriptor_i[415:384][3:0] != 0) begin
            status_q <= STATUS_BAD_DESCRIPTOR; state_q <= RESPONSE;
          end else state_q <= SCALE_REQ;
        end
        SCALE_REQ: if (dma_req_ready_i) state_q <= SCALE_RSP;
        SCALE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else begin
            index_scale_q <= dma_rsp_rdata_i[31:0];
            mla_scale_q <= dma_rsp_rdata_i[63:32];
            value_scale_q <= dma_rsp_rdata_i[95:64];
            state_q <= CHECK_SCALE;
          end
        end
        CHECK_SCALE: begin
          if (!index_scale_valid || !mla_scale_valid || !value_scale_valid) begin
            status_q <= STATUS_NUMERIC_ERROR; state_q <= RESPONSE;
          end else state_q <= META_REQ;
        end
        META_REQ: if (dma_req_ready_i) state_q <= META_RSP;
        META_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else begin
            unique case (meta_index_q)
              0: qo_begin_q <= meta_value_w;
              1: qo_end_q <= meta_value_w;
              2: kv_begin_q <= meta_value_w;
              3: kv_end_q <= meta_value_w;
              4: last_page_len_q <= meta_value_w;
              default: begin end
            endcase
            if (meta_index_q == 4) state_q <= CHECK_META;
            else begin meta_index_q <= meta_index_q + 1'b1; state_q <= META_REQ; end
          end
        end
        CHECK_META: begin
          q_len_q <= qo_end_q - qo_begin_q;
          page_count_q <= kv_end_q - kv_begin_q;
          query_q <= qo_begin_q; head_q <= '0; query_beat_q <= '0;
          if (qo_begin_q > qo_end_q || qo_end_q > q_count_q || qo_begin_q == qo_end_q) begin
            status_q <= STATUS_BAD_LENGTH; state_q <= RESPONSE;
          end else if (kv_begin_q >= kv_end_q || last_page_len_q == 0 ||
                       last_page_len_q > page_size_q) begin
            status_q <= STATUS_BAD_PAGE; state_q <= RESPONSE;
          end else if (PIPELINED_META_LENGTH) begin
            // B11 timing cut: isolate the kv_indptr subtraction from the
            // page-size/last-page arithmetic measured on the B10 CTS path.
            state_q <= CHECK_META_LENGTH;
          end else begin
            kv_len_q <= (kv_end_q - kv_begin_q - 1'b1) * page_size_q + last_page_len_q;
            state_q <= QUERY_REQ;
          end
        end
        CHECK_META_LENGTH: begin
          kv_len_q <= (page_count_q - 1'b1) * page_size_q + last_page_len_q;
          state_q <= QUERY_REQ;
        end
        QUERY_REQ: if (dma_req_ready_i) state_q <= QUERY_RSP;
        QUERY_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else begin
            for (lane = 0; lane < 16; lane = lane + 1)
              query_record[query_beat_q*16 + lane] <= dma_rsp_rdata_i[lane*8 +: 8];
            if (query_beat_q + 1 == Q_BEATS) begin
              if (PIPELINED_VISIBLE) state_q <= PREP_VISIBLE;
              else begin
                if (causal_q) begin
                  if ((query_q - qo_begin_q + 1 + kv_len_q) <= q_len_q) visible_q <= 0;
                  else if ((query_q - qo_begin_q + 1 + kv_len_q - q_len_q) < kv_len_q)
                    visible_q <= query_q - qo_begin_q + 1 + kv_len_q - q_len_q;
                  else visible_q <= kv_len_q;
                end else visible_q <= kv_len_q;
                state_q <= START_CORE;
              end
            end else begin query_beat_q <= query_beat_q + 1'b1; state_q <= QUERY_REQ; end
          end
        end
        PREP_VISIBLE: begin
          // B12 timing cut, stage 1: form the unsigned exclusive-limit base.
          // Arithmetic, subtract/underflow detection and clamping each end at
          // a register boundary instead of one kv_len_q -> visible_q cone.
          visible_sum_q <= {1'b0, query_q - qo_begin_q + 1'b1} +
                           {1'b0, kv_len_q};
          state_q <= VISIBLE_SUBTRACT;
        end
        VISIBLE_SUBTRACT: begin
          if (visible_sum_q <= {1'b0, q_len_q}) begin
            visible_underflow_q <= 1'b1;
            visible_candidate_q <= '0;
          end else begin
            visible_underflow_q <= 1'b0;
            visible_candidate_q <= visible_sum_q - {1'b0, q_len_q};
          end
          state_q <= VISIBLE_CLAMP;
        end
        VISIBLE_CLAMP: begin
          if (!causal_q) visible_q <= kv_len_q;
          else if (visible_underflow_q) visible_q <= 0;
          else if (visible_candidate_q < {1'b0, kv_len_q})
            visible_q <= visible_candidate_q[31:0];
          else visible_q <= kv_len_q;
          state_q <= START_CORE;
        end
        START_CORE: if (core_cmd_ready) state_q <= WAIT_CORE;
        WAIT_CORE: begin
          if (core_rsp_valid) state_q <= CAPTURE_CORE;
          else if (core_mem_req_valid) begin
            requested_token_q <= core_mem_req_token;
            request_mla_q <= core_mem_req_mla;
            logical_page_q <= (page_size_q == 1) ? core_mem_req_token :
                              (page_size_q == 4) ? (core_mem_req_token >> 2) :
                              (core_mem_req_token >> 4);
            page_offset_q <= (page_size_q == 1) ? 0 :
                             (page_size_q == 4) ? (core_mem_req_token & 3) :
                             (core_mem_req_token & 15);
            request_error_q <= 1'b0;
            if (((page_size_q == 1) ? core_mem_req_token :
                 (page_size_q == 4) ? (core_mem_req_token >> 2) :
                 (core_mem_req_token >> 4)) >= page_count_q) begin
              request_error_q <= 1'b1; status_q <= STATUS_BAD_PAGE; state_q <= FEED_CORE;
            end else state_q <= PAGE_REQ;
          end
        end
        PAGE_REQ: if (dma_req_ready_i) state_q <= PAGE_RSP;
        PAGE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin
            request_error_q <= 1'b1; status_q <= STATUS_BUS_ERROR; state_q <= FEED_CORE;
          end else if (PIPELINED_PAGE_VALIDATE) begin
            // Cut the measured logical-page -> dynamic page-word select ->
            // validation -> KV launch path.  The selected value is stable
            // throughout the following validation cycle.
            page_value_q <= page_value_w;
            state_q <= PAGE_VALIDATE;
          end else if (page_value_w >= kv_capacity_q ||
                       page_value_w * page_size_q + page_offset_q >= kv_capacity_q) begin
            request_error_q <= 1'b1; status_q <= STATUS_BAD_PAGE; state_q <= FEED_CORE;
          end else begin
            physical_page_q <= page_value_w; kv_beat_q <= '0; state_q <= KV_REQ;
          end
        end
        PAGE_VALIDATE: begin
          if (page_value_q >= kv_capacity_q ||
              page_value_q * page_size_q + page_offset_q >= kv_capacity_q) begin
            request_error_q <= 1'b1; status_q <= STATUS_BAD_PAGE; state_q <= FEED_CORE;
          end else begin
            physical_page_q <= page_value_q; kv_beat_q <= '0; state_q <= KV_REQ;
          end
        end
        KV_REQ: if (dma_req_ready_i) state_q <= KV_RSP;
        KV_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin
            request_error_q <= 1'b1; status_q <= STATUS_BUS_ERROR; state_q <= FEED_CORE;
          end else begin
            for (lane = 0; lane < 16; lane = lane + 1)
              kv_record[kv_beat_q*16 + lane] <= dma_rsp_rdata_i[lane*8 +: 8];
            if (kv_beat_q + 1 == KV_BEATS) begin
              dot_length_q <= request_mla_q ? NOPE_DIM + ROPE_DIM : INDEX_DIM;
              dot_index_q <= '0; state_q <= DOT_START;
            end else begin kv_beat_q <= kv_beat_q + 1'b1; state_q <= KV_REQ; end
          end
        end
        DOT_START: if (dot_cmd_ready) state_q <= DOT_FEED;
        DOT_FEED: if (dot_in_ready) begin
          if (dot_index_q + 1'b1 == dot_length_q) state_q <= DOT_WAIT;
          else dot_index_q <= dot_index_q + 1'b1;
        end
        DOT_WAIT: if (dot_rsp_valid) begin
          if (dot_length_error || (request_mla_q ? !mla_scale_valid : !index_scale_valid)) begin
            request_error_q <= 1'b1; status_q <= STATUS_NUMERIC_ERROR;
            state_q <= FEED_CORE;
          end else if (PIPELINED_SCORE_SCALE) begin
            state_q <= SCORE_START;
          end else begin
            if (request_mla_q) core_mem_mla_score <= mla_score_w;
            else core_mem_index_score <= index_score_w;
            state_q <= FEED_CORE;
          end
        end
        SCORE_START: if (score_cmd_ready) state_q <= SCORE_WAIT;
        SCORE_WAIT: if (score_rsp_valid) begin
          if (!score_scale_valid) begin
            request_error_q <= 1'b1; status_q <= STATUS_NUMERIC_ERROR;
          end else if (request_mla_q) core_mem_mla_score <= score_pipeline_q11;
          else core_mem_index_score <= score_pipeline_q11;
          state_q <= FEED_CORE;
        end
        FEED_CORE: if (core_mem_rsp_ready) begin request_error_q <= 1'b0; state_q <= WAIT_CORE; end
        CAPTURE_CORE: begin
          if (core_rsp_status != STATUS_OK) begin
            status_q <= (status_q == STATUS_OK) ? core_rsp_status : status_q;
            result_cycles_q <= cycles_q + 1'b1; state_q <= RESPONSE;
          end else begin token_write_q <= '0; state_q <= TOKEN_WRITE_REQ; end
        end
        TOKEN_WRITE_REQ: begin
          if (core_selected_count == 0) begin output_beat_q <= '0; state_q <= OUTPUT_WRITE_REQ; end
          else if (dma_req_ready_i) state_q <= TOKEN_WRITE_RSP;
        end
        TOKEN_WRITE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else if (token_write_q + 1'b1 == core_selected_count) begin
            output_beat_q <= '0; state_q <= OUTPUT_WRITE_REQ;
          end else begin token_write_q <= token_write_q + 1'b1; state_q <= TOKEN_WRITE_REQ; end
        end
        OUTPUT_WRITE_REQ: if (dma_req_ready_i) state_q <= OUTPUT_WRITE_RSP;
        OUTPUT_WRITE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= STATUS_BUS_ERROR; state_q <= RESPONSE; end
          else if (output_beat_q + 1'b1 < ((VALUE_DIM * 2 + 15) / 16)) begin
            output_beat_q <= output_beat_q + 1'b1; state_q <= OUTPUT_WRITE_REQ;
          end else if (head_q + 1'b1 < HEADS) begin
            head_q <= head_q + 1'b1; query_beat_q <= '0; state_q <= QUERY_REQ;
          end else if (query_q + 1'b1 < qo_end_q) begin
            query_q <= query_q + 1'b1; head_q <= '0; query_beat_q <= '0; state_q <= QUERY_REQ;
          end else if (batch_q + 1'b1 < batch_count_q) begin
            batch_q <= batch_q + 1'b1;
            meta_index_q <= '0;
            state_q <= META_REQ;
          end else begin
            status_q <= STATUS_OK; result_cycles_q <= cycles_q + 1'b1; state_q <= RESPONSE;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  logic unused;
  assign unused = ^requested_token_q ^ ^core_q16_vector;
endmodule
