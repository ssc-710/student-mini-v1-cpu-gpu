// SPDX-License-Identifier: Apache-2.0
// Scalar-value Split-KV B0 numeric core.  Tokens are requested in contiguous
// [begin,end) intervals, each split builds an online-softmax state, states are
// merged in ascending split-id order, and o/d uses the shared serial divider.
module p2_split_kv_b4_divider_finalize #(
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit RADIX16_MERGE = 1'b0
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    cmd_valid_i,
  output logic                    cmd_ready_o,
  input  logic [31:0]             cache_len_i,
  input  logic [3:0]              splits_i,
  input  logic [7:0]              page_size_i,
  input  logic [31:0]             value_scale_i,

  output logic                    token_req_valid_o,
  input  logic                    token_req_ready_i,
  output logic [31:0]             token_index_o,
  output logic [3:0]              split_id_o,
  input  logic                    token_rsp_valid_i,
  output logic                    token_rsp_ready_o,
  input  logic signed [15:0]      token_rsp_score_q11_i,
  input  logic signed [7:0]       token_rsp_value_i,
  input  logic                    token_rsp_error_i,

  output logic                    rsp_valid_o,
  input  logic                    rsp_ready_i,
  output logic [7:0]              rsp_status_o,
  output logic [63:0]             rsp_cycles_o,
  output logic signed [31:0]      output_q16_o,
  output logic [15:0]             output_bf16_o,
  output logic signed [15:0]      merged_max_q11_o,
  output logic [47:0]             merged_sum_q15_o,
  output logic signed [63:0]      merged_weighted_q15_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_BAD_LENGTH = 8'd2;
  localparam logic [7:0] STATUS_NUMERIC_ERROR = 8'd4;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;

  typedef enum logic [3:0] {
    IDLE, SCAN, LOCAL_UPDATE, STORE_PARTIAL, BEGIN_MERGE, MERGE,
    MERGE_WAIT, START_DIVIDE, WAIT_DIVIDE, RESPONSE
  } state_t;
  state_t state_q;
  logic [31:0] length_q, chunk_q, token_q, split_begin_q, split_end_q;
  logic [3:0] splits_q;
  logic [2:0] split_q, merge_index_q;
  logic waiting_q;
  logic local_valid_q;
  logic signed [15:0] local_max_q;
  logic [47:0] local_sum_q;
  logic signed [63:0] local_weighted_q;
  logic signed [15:0] partial_max_q [0:7];
  logic [47:0] partial_sum_q [0:7];
  logic signed [63:0] partial_weighted_q [0:7];
  logic signed [15:0] merged_max_q;
  logic [47:0] merged_sum_q;
  logic signed [63:0] merged_weighted_q;
  logic signed [31:0] output_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;
  integer reset_index;

  logic next_local_valid;
  logic signed [15:0] next_local_max;
  logic [47:0] next_local_sum;
  logic signed [63:0] next_local_weighted;
  logic online_req_ready, online_rsp_valid, online_rsp_ready;
  generate
    if (PIPELINED_SOFTMAX) begin : g_pipelined_online
      online_softmax_step_sync_product_pipeline u_online (
        .clk_i, .rst_ni,
        .req_valid_i(state_q == SCAN && waiting_q && token_rsp_valid_i &&
                     token_rsp_ready_o && !token_rsp_error_i),
        .req_ready_o(online_req_ready),
        .state_valid_i(local_valid_q), .maximum_q11_i(local_max_q),
        .denominator_q15_i(local_sum_q), .weighted_q15_i(local_weighted_q),
        .score_q11_i(token_rsp_score_q11_i), .value_i(token_rsp_value_i),
        .rsp_valid_o(online_rsp_valid), .rsp_ready_i(online_rsp_ready),
        .state_valid_o(next_local_valid), .maximum_q11_o(next_local_max),
        .denominator_q15_o(next_local_sum),
        .weighted_q15_o(next_local_weighted)
      );
    end else begin : g_combinational_online
      online_softmax_step u_online (
        .state_valid_i(local_valid_q), .maximum_q11_i(local_max_q),
        .denominator_q15_i(local_sum_q), .weighted_q15_i(local_weighted_q),
        .score_q11_i(token_rsp_score_q11_i), .value_i(token_rsp_value_i),
        .state_valid_o(next_local_valid), .maximum_q11_o(next_local_max),
        .denominator_q15_o(next_local_sum),
        .weighted_q15_o(next_local_weighted)
      );
      assign online_req_ready = 1'b1;
      assign online_rsp_valid = 1'b0;
    end
  endgenerate
  assign online_rsp_ready = PIPELINED_SOFTMAX && state_q == LOCAL_UPDATE;

  logic signed [15:0] merge_max;
  logic [47:0] merge_sum;
  logic signed [63:0] merge_weighted;
  logic merge_req_ready, merge_rsp_valid, merge_rsp_ready;
  generate
    if (PIPELINED_SOFTMAX) begin : g_pipelined_merge
      if (RADIX16_MERGE) begin : g_radix16
        softmax_merge_q_radix16 u_merge (
          .clk_i, .rst_ni, .req_valid_i(state_q == MERGE),
          .req_ready_o(merge_req_ready),
          .left_max_i(merged_max_q), .left_sum_i(merged_sum_q),
          .left_weighted_i(merged_weighted_q),
          .right_max_i(partial_max_q[merge_index_q]),
          .right_sum_i(partial_sum_q[merge_index_q]),
          .right_weighted_i(partial_weighted_q[merge_index_q]),
          .rsp_valid_o(merge_rsp_valid), .rsp_ready_i(merge_rsp_ready),
          .merged_max_o(merge_max), .merged_sum_o(merge_sum),
          .merged_weighted_o(merge_weighted)
        );
      end else begin : g_wide_product
        softmax_merge_q_sync u_merge (
          .clk_i, .rst_ni, .req_valid_i(state_q == MERGE),
          .req_ready_o(merge_req_ready),
          .left_max_i(merged_max_q), .left_sum_i(merged_sum_q),
          .left_weighted_i(merged_weighted_q),
          .right_max_i(partial_max_q[merge_index_q]),
          .right_sum_i(partial_sum_q[merge_index_q]),
          .right_weighted_i(partial_weighted_q[merge_index_q]),
          .rsp_valid_o(merge_rsp_valid), .rsp_ready_i(merge_rsp_ready),
          .merged_max_o(merge_max), .merged_sum_o(merge_sum),
          .merged_weighted_o(merge_weighted)
        );
      end
    end else begin : g_combinational_merge
      softmax_merge_q u_merge (
        .left_max_i(merged_max_q), .left_sum_i(merged_sum_q),
        .left_weighted_i(merged_weighted_q),
        .right_max_i(partial_max_q[merge_index_q]),
        .right_sum_i(partial_sum_q[merge_index_q]),
        .right_weighted_i(partial_weighted_q[merge_index_q]),
        .merged_max_o(merge_max), .merged_sum_o(merge_sum),
        .merged_weighted_o(merge_weighted)
      );
      assign merge_req_ready = 1'b1;
      assign merge_rsp_valid = 1'b0;
    end
  endgenerate
  assign merge_rsp_ready = PIPELINED_SOFTMAX && state_q == MERGE_WAIT;

  logic divider_cmd_ready, divider_rsp_valid, divider_rsp_ready;
  logic signed [31:0] divider_quotient;
  logic divider_zero, divider_saturated;
  fixed_divider_rne_finalize_pipeline #(
    .NUM_WIDTH(64), .DEN_WIDTH(48), .OUT_WIDTH(32), .FRAC_BITS(16)
  ) u_divider (
    .clk_i, .rst_ni,
    .cmd_valid_i(state_q == START_DIVIDE), .cmd_ready_o(divider_cmd_ready),
    .numerator_i(merged_weighted_q), .denominator_i(merged_sum_q),
    .rsp_valid_o(divider_rsp_valid), .rsp_ready_i(divider_rsp_ready),
    .quotient_o(divider_quotient), .divide_by_zero_o(divider_zero),
    .saturated_o(divider_saturated)
  );
  assign divider_rsp_ready = state_q == WAIT_DIVIDE;

  logic [32:0] chunk_value_wide, next_split_end_wide;
  always_comb begin
    unique case (splits_i)
      4'd1: chunk_value_wide = {1'b0, cache_len_i};
      4'd2: chunk_value_wide = ({1'b0, cache_len_i} + 33'd1) >> 1;
      4'd4: chunk_value_wide = ({1'b0, cache_len_i} + 33'd3) >> 2;
      4'd8: chunk_value_wide = ({1'b0, cache_len_i} + 33'd7) >> 3;
      default: chunk_value_wide = 33'd0;
    endcase
  end
  assign next_split_end_wide = {1'b0, split_end_q} + {1'b0, chunk_q};

  assign cmd_ready_o = state_q == IDLE;
  assign token_req_valid_o = state_q == SCAN && !waiting_q;
  assign token_index_o = token_q;
  assign split_id_o = {1'b0, split_q};
  assign token_rsp_ready_o = state_q == SCAN && waiting_q &&
                             (!PIPELINED_SOFTMAX || online_req_ready);
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;
  assign output_q16_o = output_q;
  assign merged_max_q11_o = merged_max_q;
  assign merged_sum_q15_o = merged_sum_q;
  assign merged_weighted_q15_o = merged_weighted_q;

  logic [31:0] output_scale_adjusted;
  logic output_scale_mul_bad, output_scale_valid, output_bf16_bad;
  fp32_scale_check u_value_scale_check(
    .scale_i(value_scale_i), .valid_o(output_scale_valid));
  fp32_positive_mul_rne u_output_scale_adjust(
    .a_i(value_scale_i), .b_i(32'h37800000),
    .product_o(output_scale_adjusted), .invalid_o(output_scale_mul_bad));
  int32_times_fp32_to_bf16 u_bf16_write(
    .value_i(output_q), .scale_i(output_scale_adjusted),
    .bf16_o(output_bf16_o), .invalid_scale_o(output_bf16_bad));

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      length_q <= '0; chunk_q <= '0; token_q <= '0;
      split_begin_q <= '0; split_end_q <= '0;
      splits_q <= '0; split_q <= '0; merge_index_q <= '0;
      waiting_q <= 1'b0; local_valid_q <= 1'b0;
      local_max_q <= '0; local_sum_q <= '0; local_weighted_q <= '0;
      merged_max_q <= '0; merged_sum_q <= '0; merged_weighted_q <= '0;
      output_q <= '0; status_q <= STATUS_OK; cycles_q <= '0; result_cycles_q <= '0;
      for (reset_index = 0; reset_index < 8; reset_index = reset_index + 1) begin
        partial_max_q[reset_index] <= '0;
        partial_sum_q[reset_index] <= '0;
        partial_weighted_q[reset_index] <= '0;
      end
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          length_q <= cache_len_i;
          splits_q <= splits_i;
          split_q <= '0;
          merge_index_q <= '0;
          cycles_q <= '0;
          result_cycles_q <= '0;
          output_q <= '0;
          waiting_q <= 1'b0;
          local_valid_q <= 1'b0;
          status_q <= STATUS_OK;
          if (!output_scale_valid || output_scale_mul_bad) begin
            status_q <= STATUS_NUMERIC_ERROR;
            state_q <= RESPONSE;
          end else if (!((page_size_i == 1) || (page_size_i == 16)) ||
              !((splits_i == 1) || (splits_i == 2) || (splits_i == 4) || (splits_i == 8))) begin
            status_q <= STATUS_BAD_DESCRIPTOR;
            state_q <= RESPONSE;
          end else if (cache_len_i == 0 || {28'd0, splits_i} > cache_len_i) begin
            status_q <= STATUS_BAD_LENGTH;
            state_q <= RESPONSE;
          end else begin
            chunk_q <= chunk_value_wide[31:0];
            token_q <= 0;
            split_begin_q <= 0;
            split_end_q <= (chunk_value_wide > {1'b0, cache_len_i}) ?
                           cache_len_i : chunk_value_wide[31:0];
            state_q <= SCAN;
          end
        end
        SCAN: begin
          if (token_req_valid_o && token_req_ready_i) waiting_q <= 1'b1;
          if (token_rsp_valid_i && token_rsp_ready_o) begin
            waiting_q <= 1'b0;
            if (token_rsp_error_i) begin
              status_q <= STATUS_BUS_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else if (PIPELINED_SOFTMAX) begin
              state_q <= LOCAL_UPDATE;
            end else begin
              local_valid_q <= next_local_valid;
              local_max_q <= next_local_max;
              local_sum_q <= next_local_sum;
              local_weighted_q <= next_local_weighted;
              if (token_q + 1'b1 == split_end_q) state_q <= STORE_PARTIAL;
              else token_q <= token_q + 1'b1;
            end
          end
        end
        LOCAL_UPDATE: if (online_rsp_valid) begin
          local_valid_q <= next_local_valid;
          local_max_q <= next_local_max;
          local_sum_q <= next_local_sum;
          local_weighted_q <= next_local_weighted;
          if (token_q + 1'b1 == split_end_q) state_q <= STORE_PARTIAL;
          else begin
            token_q <= token_q + 1'b1;
            state_q <= SCAN;
          end
        end
        STORE_PARTIAL: begin
          partial_max_q[split_q] <= local_max_q;
          partial_sum_q[split_q] <= local_sum_q;
          partial_weighted_q[split_q] <= local_weighted_q;
          if (split_end_q == length_q) begin
            // ceil(L/splits) can make the final configured interval empty
            // (for example L=33,splits=8).  Stop at the first interval that
            // reaches L and merge only the non-empty partials.
            splits_q <= {1'b0, split_q} + 1'b1;
            state_q <= BEGIN_MERGE;
          end else begin
            split_q <= split_q + 1'b1;
            split_begin_q <= split_end_q;
            token_q <= split_end_q;
            split_end_q <= (next_split_end_wide > {1'b0, length_q}) ?
                           length_q : next_split_end_wide[31:0];
            local_valid_q <= 1'b0;
            local_max_q <= '0;
            local_sum_q <= '0;
            local_weighted_q <= '0;
            state_q <= SCAN;
          end
        end
        BEGIN_MERGE: begin
          merged_max_q <= partial_max_q[0];
          merged_sum_q <= partial_sum_q[0];
          merged_weighted_q <= partial_weighted_q[0];
          merge_index_q <= 1;
          state_q <= (splits_q == 1) ? START_DIVIDE : MERGE;
        end
        MERGE: begin
          if (PIPELINED_SOFTMAX) begin
            if (merge_req_ready) state_q <= MERGE_WAIT;
          end else begin
            merged_max_q <= merge_max;
            merged_sum_q <= merge_sum;
            merged_weighted_q <= merge_weighted;
            if ({1'b0, merge_index_q} + 1'b1 == splits_q) state_q <= START_DIVIDE;
            else merge_index_q <= merge_index_q + 1'b1;
          end
        end
        MERGE_WAIT: if (merge_rsp_valid) begin
          merged_max_q <= merge_max;
          merged_sum_q <= merge_sum;
          merged_weighted_q <= merge_weighted;
          if ({1'b0, merge_index_q} + 1'b1 == splits_q) state_q <= START_DIVIDE;
          else begin
            merge_index_q <= merge_index_q + 1'b1;
            state_q <= MERGE;
          end
        end
        START_DIVIDE: if (divider_cmd_ready) state_q <= WAIT_DIVIDE;
        WAIT_DIVIDE: if (divider_rsp_valid) begin
          output_q <= divider_quotient;
          if (divider_zero || divider_saturated) status_q <= STATUS_BAD_DESCRIPTOR;
          result_cycles_q <= cycles_q + 1'b1;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule




