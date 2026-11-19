// SPDX-License-Identifier: Apache-2.0
// Scalar-value P1 B0 numeric core: sequential Indexer scan, stable Top-K,
// selected-token-only MLA scan, Online Softmax, then serial RNE o/d.
module p1_dsa_mla_b0 #(
  parameter int K_MAX = 32,
  parameter int VALUE_DIM = 1,
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  localparam int K_WIDTH = $clog2(K_MAX + 1)
) (
  input  logic                         clk_i,
  input  logic                         rst_ni,
  input  logic                         cmd_valid_i,
  output logic                         cmd_ready_o,
  input  logic [31:0]                  visible_count_i,
  input  logic [7:0]                   topk_i,
  input  logic [31:0]                  value_scale_i,

  output logic                         mem_req_valid_o,
  input  logic                         mem_req_ready_i,
  output logic                         mem_req_mla_o,
  output logic [31:0]                  mem_req_token_o,
  input  logic                         mem_rsp_valid_i,
  output logic                         mem_rsp_ready_o,
  input  logic signed [15:0]           mem_rsp_index_score_q11_i,
  input  logic signed [15:0]           mem_rsp_mla_score_q11_i,
  input  logic signed [VALUE_DIM*8-1:0] mem_rsp_value_i,
  input  logic                         mem_rsp_error_i,

  output logic                         rsp_valid_o,
  input  logic                         rsp_ready_i,
  output logic [7:0]                   rsp_status_o,
  output logic [63:0]                  rsp_cycles_o,
  output logic signed [31:0]           output_q16_o,
  output logic [15:0]                  output_bf16_o,
  output logic signed [VALUE_DIM*32-1:0] output_q16_vector_o,
  output logic [VALUE_DIM*16-1:0]      output_bf16_vector_o,
  output logic [K_WIDTH-1:0]           selected_count_o,
  output logic [K_MAX*32-1:0]          selected_tokens_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_BAD_LENGTH = 8'd2;
  localparam logic [7:0] STATUS_NUMERIC_ERROR = 8'd4;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;
  localparam logic [7:0] K_MAX_U8 = 8'(K_MAX);

  typedef enum logic [3:0] {
    IDLE, START_TOPK, INDEX_SCAN, FINISH_TOPK, COLLECT_TOPK,
    MLA_SCAN, MLA_UPDATE, START_DIVIDE, WAIT_DIVIDE, RESPONSE
  } state_t;
  state_t state_q;
  logic [31:0] visible_q, index_token_q;
  logic [K_WIDTH-1:0] effective_k_q, selected_count_q, mla_index_q;
  logic waiting_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;
  logic signed [31:0] output_q [0:VALUE_DIM-1];

  logic topk_start_ready, topk_candidate_ready, topk_finish_ready;
  logic topk_result_valid, topk_result_ready, topk_result_last;
  logic signed [15:0] topk_result_score;
  logic [31:0] topk_result_token;
  stable_topk #(.K_MAX(K_MAX)) u_topk (
    .clk_i, .rst_ni,
    .start_valid_i(state_q == START_TOPK), .start_ready_o(topk_start_ready),
    .k_i(effective_k_q),
    .candidate_valid_i(state_q == INDEX_SCAN && waiting_q && mem_rsp_valid_i &&
                       !mem_rsp_error_i),
    .candidate_ready_o(topk_candidate_ready),
    .candidate_score_i(mem_rsp_index_score_q11_i),
    .candidate_token_i(index_token_q),
    .finish_valid_i(state_q == FINISH_TOPK), .finish_ready_o(topk_finish_ready),
    .result_valid_o(topk_result_valid), .result_ready_i(topk_result_ready),
    .result_score_o(topk_result_score), .result_token_o(topk_result_token),
    .result_last_o(topk_result_last)
  );
  assign topk_result_ready = state_q == COLLECT_TOPK;

  logic local_valid_q;
  logic signed [15:0] local_max_q;
  logic [47:0] local_sum_q;
  logic signed [63:0] local_weighted_q [0:VALUE_DIM-1];
  logic next_local_valid [0:VALUE_DIM-1];
  logic signed [15:0] next_local_max [0:VALUE_DIM-1];
  logic [47:0] next_local_sum [0:VALUE_DIM-1];
  logic signed [63:0] next_local_weighted [0:VALUE_DIM-1];
  logic online_req_ready [0:VALUE_DIM-1];
  logic online_rsp_valid [0:VALUE_DIM-1];
  logic online_rsp_ready;
  logic all_online_req_ready, all_online_rsp_valid;

  logic divider_cmd_ready [0:VALUE_DIM-1];
  logic divider_rsp_valid [0:VALUE_DIM-1];
  logic divider_rsp_ready;
  logic signed [31:0] divider_quotient [0:VALUE_DIM-1];
  logic divider_zero [0:VALUE_DIM-1];
  logic divider_saturated [0:VALUE_DIM-1];
  logic all_divider_cmd_ready, all_divider_rsp_valid;
  logic any_divider_error;

  genvar value_lane;
  generate for (value_lane = 0; value_lane < VALUE_DIM; value_lane++) begin : g_value_lane
    if (PIPELINED_SOFTMAX) begin : g_pipelined_online
      online_softmax_step_sync u_online (
        .clk_i, .rst_ni,
        .req_valid_i(state_q == MLA_SCAN && waiting_q && mem_rsp_valid_i &&
                     mem_rsp_ready_o && !mem_rsp_error_i),
        .req_ready_o(online_req_ready[value_lane]),
        .state_valid_i(local_valid_q), .maximum_q11_i(local_max_q),
        .denominator_q15_i(local_sum_q),
        .weighted_q15_i(local_weighted_q[value_lane]),
        .score_q11_i(mem_rsp_mla_score_q11_i),
        .value_i(mem_rsp_value_i[value_lane*8 +: 8]),
        .rsp_valid_o(online_rsp_valid[value_lane]),
        .rsp_ready_i(online_rsp_ready),
        .state_valid_o(next_local_valid[value_lane]),
        .maximum_q11_o(next_local_max[value_lane]),
        .denominator_q15_o(next_local_sum[value_lane]),
        .weighted_q15_o(next_local_weighted[value_lane])
      );
    end else begin : g_combinational_online
      online_softmax_step u_online (
        .state_valid_i(local_valid_q), .maximum_q11_i(local_max_q),
        .denominator_q15_i(local_sum_q),
        .weighted_q15_i(local_weighted_q[value_lane]),
        .score_q11_i(mem_rsp_mla_score_q11_i),
        .value_i(mem_rsp_value_i[value_lane*8 +: 8]),
        .state_valid_o(next_local_valid[value_lane]),
        .maximum_q11_o(next_local_max[value_lane]),
        .denominator_q15_o(next_local_sum[value_lane]),
        .weighted_q15_o(next_local_weighted[value_lane])
      );
      assign online_req_ready[value_lane] = 1'b1;
      assign online_rsp_valid[value_lane] = 1'b0;
    end
    fixed_divider_rne #(
      .NUM_WIDTH(64), .DEN_WIDTH(48), .OUT_WIDTH(32), .FRAC_BITS(16)
    ) u_divider (
      .clk_i, .rst_ni,
      .cmd_valid_i(state_q == START_DIVIDE),
      .cmd_ready_o(divider_cmd_ready[value_lane]),
      .numerator_i(local_weighted_q[value_lane]), .denominator_i(local_sum_q),
      .rsp_valid_o(divider_rsp_valid[value_lane]), .rsp_ready_i(divider_rsp_ready),
      .quotient_o(divider_quotient[value_lane]),
      .divide_by_zero_o(divider_zero[value_lane]),
      .saturated_o(divider_saturated[value_lane])
    );
    assign output_q16_vector_o[value_lane*32 +: 32] = output_q[value_lane];
  end endgenerate

  integer reduce_lane;
  always_comb begin
    all_online_req_ready = 1'b1;
    all_online_rsp_valid = 1'b1;
    all_divider_cmd_ready = 1'b1;
    all_divider_rsp_valid = 1'b1;
    any_divider_error = 1'b0;
    for (reduce_lane = 0; reduce_lane < VALUE_DIM; reduce_lane = reduce_lane + 1) begin
      all_online_req_ready &= online_req_ready[reduce_lane];
      all_online_rsp_valid &= online_rsp_valid[reduce_lane];
      all_divider_cmd_ready &= divider_cmd_ready[reduce_lane];
      all_divider_rsp_valid &= divider_rsp_valid[reduce_lane];
      any_divider_error |= divider_zero[reduce_lane] | divider_saturated[reduce_lane];
    end
  end
  assign online_rsp_ready = PIPELINED_SOFTMAX &&
                            state_q == MLA_UPDATE && all_online_rsp_valid;
  assign divider_rsp_ready = state_q == WAIT_DIVIDE && all_divider_rsp_valid;

  assign cmd_ready_o = state_q == IDLE;
  assign mem_req_valid_o = (state_q == INDEX_SCAN || state_q == MLA_SCAN) && !waiting_q;
  assign mem_req_mla_o = state_q == MLA_SCAN;
  assign mem_req_token_o = (state_q == MLA_SCAN) ?
                           selected_tokens_o[mla_index_q*32 +: 32] : index_token_q;
  assign mem_rsp_ready_o = waiting_q &&
                           (((state_q == INDEX_SCAN) && topk_candidate_ready) ||
                            ((state_q == MLA_SCAN) &&
                             (!PIPELINED_SOFTMAX || all_online_req_ready)));
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;
  assign output_q16_o = output_q[0];
  assign selected_count_o = selected_count_q;

  logic [31:0] output_scale_adjusted;
  logic output_scale_mul_bad, output_scale_bad;
  logic output_bf16_bad [0:VALUE_DIM-1];
  fp32_scale_check u_value_scale_check(
    .scale_i(value_scale_i), .valid_o(output_scale_bad));
  fp32_positive_mul_rne u_output_scale_adjust(
    .a_i(value_scale_i), .b_i(32'h37800000),
    .product_o(output_scale_adjusted), .invalid_o(output_scale_mul_bad));
  generate for (value_lane = 0; value_lane < VALUE_DIM; value_lane++) begin : g_bf16_lane
    int32_times_fp32_to_bf16 u_bf16_write(
      .value_i(output_q[value_lane]), .scale_i(output_scale_adjusted),
      .bf16_o(output_bf16_vector_o[value_lane*16 +: 16]),
      .invalid_scale_o(output_bf16_bad[value_lane]));
  end endgenerate
  assign output_bf16_o = output_bf16_vector_o[15:0];

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      visible_q <= '0; index_token_q <= '0; effective_k_q <= '0;
      selected_count_q <= '0; mla_index_q <= '0; selected_tokens_o <= '0;
      waiting_q <= 1'b0; status_q <= STATUS_OK;
      cycles_q <= '0; result_cycles_q <= '0;
      local_valid_q <= 1'b0; local_max_q <= '0;
      local_sum_q <= '0;
      for (int lane = 0; lane < VALUE_DIM; lane++) begin
        output_q[lane] <= '0;
        local_weighted_q[lane] <= '0;
      end
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          visible_q <= visible_count_i;
          index_token_q <= '0;
          selected_count_q <= '0;
          mla_index_q <= '0;
          selected_tokens_o <= '0;
          waiting_q <= 1'b0;
          cycles_q <= '0;
          result_cycles_q <= '0;
          for (int lane = 0; lane < VALUE_DIM; lane++) begin
            output_q[lane] <= '0;
            local_weighted_q[lane] <= '0;
          end
          status_q <= STATUS_OK;
          local_valid_q <= 1'b0;
          local_max_q <= '0; local_sum_q <= '0;
          if (!output_scale_bad || output_scale_mul_bad) begin
            status_q <= STATUS_NUMERIC_ERROR;
            state_q <= RESPONSE;
          end else if (topk_i == 0) begin
            status_q <= STATUS_BAD_DESCRIPTOR;
            state_q <= RESPONSE;
          end else if (visible_count_i == 0) begin
            // Bottom-right causal alignment legitimately gives early queries
            // an empty visible prefix when q_len > kv_len.  The mathematical
            // result is the all-zero value vector, not a malformed command.
            result_cycles_q <= 64'd1;
            state_q <= RESPONSE;
          end else begin
            if (visible_count_i < topk_i && visible_count_i < K_MAX)
              effective_k_q <= visible_count_i[K_WIDTH-1:0];
            else if (topk_i > K_MAX_U8)
              effective_k_q <= K_WIDTH'(K_MAX);
            else effective_k_q <= topk_i[K_WIDTH-1:0];
            state_q <= START_TOPK;
          end
        end
        START_TOPK: if (topk_start_ready) state_q <= INDEX_SCAN;
        INDEX_SCAN: begin
          if (mem_req_valid_o && mem_req_ready_i) waiting_q <= 1'b1;
          if (mem_rsp_valid_i && mem_rsp_ready_o) begin
            waiting_q <= 1'b0;
            if (mem_rsp_error_i) begin
              status_q <= STATUS_BUS_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else if (index_token_q + 1'b1 == visible_q) begin
              state_q <= FINISH_TOPK;
            end else index_token_q <= index_token_q + 1'b1;
          end
        end
        FINISH_TOPK: if (topk_finish_ready) state_q <= COLLECT_TOPK;
        COLLECT_TOPK: if (topk_result_valid) begin
          selected_tokens_o[selected_count_q*32 +: 32] <= topk_result_token;
          selected_count_q <= selected_count_q + 1'b1;
          if (topk_result_last) begin
            mla_index_q <= '0;
            state_q <= MLA_SCAN;
          end
        end
        MLA_SCAN: begin
          if (mem_req_valid_o && mem_req_ready_i) waiting_q <= 1'b1;
          if (mem_rsp_valid_i && mem_rsp_ready_o) begin
            waiting_q <= 1'b0;
            if (mem_rsp_error_i) begin
              status_q <= STATUS_BUS_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else if (PIPELINED_SOFTMAX) begin
              state_q <= MLA_UPDATE;
            end else begin
              local_valid_q <= next_local_valid[0];
              local_max_q <= next_local_max[0];
              local_sum_q <= next_local_sum[0];
              for (int lane = 0; lane < VALUE_DIM; lane++)
                local_weighted_q[lane] <= next_local_weighted[lane];
              if (mla_index_q + 1'b1 == selected_count_q) state_q <= START_DIVIDE;
              else mla_index_q <= mla_index_q + 1'b1;
            end
          end
        end
        MLA_UPDATE: if (all_online_rsp_valid) begin
          local_valid_q <= next_local_valid[0];
          local_max_q <= next_local_max[0];
          local_sum_q <= next_local_sum[0];
          for (int lane = 0; lane < VALUE_DIM; lane++)
            local_weighted_q[lane] <= next_local_weighted[lane];
          if (mla_index_q + 1'b1 == selected_count_q) state_q <= START_DIVIDE;
          else begin
            mla_index_q <= mla_index_q + 1'b1;
            state_q <= MLA_SCAN;
          end
        end
        START_DIVIDE: if (all_divider_cmd_ready) state_q <= WAIT_DIVIDE;
        WAIT_DIVIDE: if (all_divider_rsp_valid) begin
          for (int lane = 0; lane < VALUE_DIM; lane++)
            output_q[lane] <= divider_quotient[lane];
          if (any_divider_error) status_q <= STATUS_BAD_DESCRIPTOR;
          result_cycles_q <= cycles_q + 1'b1;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  logic unused_topk_score;
  assign unused_topk_score = ^topk_result_score;
endmodule
