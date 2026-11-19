// SPDX-License-Identifier: Apache-2.0
// Conservative B0 timing foundation for stable Top-K.
//
// Unlike the B23 grouped search, this implementation examines exactly one
// stored slot per search step.  It preserves score-descending/token-ascending
// ordering and the original streaming handshake, but deliberately trades
// latency for short register-to-register paths.  The selected array slot is
// first captured in FETCH and compared in SEARCH on the following cycle; this
// prevents the K_MAX-way read mux and the score/token comparison from forming
// one physical path.  The subsequent shift remains a one-position registered
// move, so this is not a throughput optimisation that can be claimed by a
// promotion candidate.
module stable_topk #(
  parameter int K_MAX = 32,
  parameter int K_WIDTH = $clog2(K_MAX + 1)
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    start_valid_i,
  output logic                    start_ready_o,
  input  logic [K_WIDTH-1:0]      k_i,
  input  logic                    candidate_valid_i,
  output logic                    candidate_ready_o,
  input  logic signed [15:0]      candidate_score_i,
  input  logic [31:0]             candidate_token_i,
  input  logic                    finish_valid_i,
  output logic                    finish_ready_o,
  output logic                    result_valid_o,
  input  logic                    result_ready_i,
  output logic signed [15:0]      result_score_o,
  output logic [31:0]             result_token_o,
  output logic                    result_last_o
);
  typedef enum logic [2:0] {IDLE, SCAN, FETCH, SEARCH, COMMIT, OUTPUT} state_t;
  localparam int INDEX_WIDTH = $clog2(K_MAX);
  localparam logic [K_WIDTH-1:0] K_MAX_VALUE = K_WIDTH'(K_MAX);

  state_t state_q;
  logic [K_WIDTH-1:0] k_q, count_q, output_index_q;
  logic [K_WIDTH-1:0] search_index_q, insert_position_q;
  logic signed [15:0] candidate_score_q;
  logic [31:0] candidate_token_q;
  logic signed [15:0] selected_score_q;
  logic [31:0] selected_token_q;
  logic signed [15:0] score_q [0:K_MAX-1];
  logic [31:0] token_q [0:K_MAX-1];
  integer sequential_index;

  assign start_ready_o = state_q == IDLE;
  assign candidate_ready_o = state_q == SCAN;
  assign finish_ready_o = state_q == SCAN;
  assign result_valid_o = state_q == OUTPUT;
  assign result_score_o = score_q[output_index_q[INDEX_WIDTH-1:0]];
  assign result_token_o = token_q[output_index_q[INDEX_WIDTH-1:0]];
  assign result_last_o = result_valid_o && (output_index_q + 1'b1 == count_q);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      k_q <= '0;
      count_q <= '0;
      output_index_q <= '0;
      search_index_q <= '0;
      insert_position_q <= K_MAX_VALUE;
      candidate_score_q <= '0;
      candidate_token_q <= '0;
      selected_score_q <= '0;
      selected_token_q <= '0;
      for (sequential_index = 0; sequential_index < K_MAX; sequential_index++) begin
        score_q[sequential_index] <= '0;
        token_q[sequential_index] <= '0;
      end
    end else begin
      case (state_q)
        IDLE: if (start_valid_i && start_ready_o) begin
          k_q <= (k_i > K_MAX_VALUE) ? K_MAX_VALUE : k_i;
          count_q <= '0;
          output_index_q <= '0;
          state_q <= SCAN;
        end
        SCAN: begin
          if (candidate_valid_i && candidate_ready_o) begin
            candidate_score_q <= candidate_score_i;
            candidate_token_q <= candidate_token_i;
            search_index_q <= '0;
            insert_position_q <= K_MAX_VALUE;
            state_q <= FETCH;
          end else if (finish_valid_i && finish_ready_o) begin
            output_index_q <= '0;
            state_q <= (count_q == 0) ? IDLE : OUTPUT;
          end
        end
        FETCH: begin
          selected_score_q <= score_q[search_index_q[INDEX_WIDTH-1:0]];
          selected_token_q <= token_q[search_index_q[INDEX_WIDTH-1:0]];
          state_q <= SEARCH;
        end
        SEARCH: begin
          if (search_index_q >= k_q) begin
            insert_position_q <= K_MAX_VALUE;
            state_q <= COMMIT;
          end else if ((search_index_q >= count_q) ||
                       (candidate_score_q > selected_score_q) ||
                       ((candidate_score_q == selected_score_q) &&
                        (candidate_token_q < selected_token_q))) begin
            insert_position_q <= search_index_q;
            state_q <= COMMIT;
          end else if (search_index_q + 1'b1 >= k_q) begin
            insert_position_q <= K_MAX_VALUE;
            state_q <= COMMIT;
          end else begin
            search_index_q <= search_index_q + 1'b1;
            state_q <= FETCH;
          end
        end
        COMMIT: begin
          if (insert_position_q < K_MAX_VALUE) begin
            for (sequential_index = K_MAX - 1; sequential_index > 0; sequential_index--) begin
              if ((sequential_index > insert_position_q) && (sequential_index < k_q)) begin
                score_q[sequential_index] <= score_q[sequential_index-1];
                token_q[sequential_index] <= token_q[sequential_index-1];
              end
            end
            score_q[insert_position_q[INDEX_WIDTH-1:0]] <= candidate_score_q;
            token_q[insert_position_q[INDEX_WIDTH-1:0]] <= candidate_token_q;
            if (count_q < k_q) count_q <= count_q + 1'b1;
          end
          state_q <= SCAN;
        end
        OUTPUT: if (result_valid_o && result_ready_i) begin
          if (result_last_o) state_q <= IDLE;
          else output_index_q <= output_index_q + 1'b1;
        end
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
