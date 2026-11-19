// SPDX-License-Identifier: Apache-2.0
// Streaming stable Top-K: score descending, token id ascending on ties.
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
  typedef enum logic [1:0] {IDLE, SCAN, OUTPUT} state_t;
  localparam int INDEX_WIDTH = $clog2(K_MAX);
  localparam logic [K_WIDTH-1:0] K_MAX_VALUE = K_WIDTH'(K_MAX);
  state_t state_q;
  logic [K_WIDTH-1:0] k_q, count_q, output_index_q;
  logic signed [15:0] score_q [0:K_MAX-1];
  logic [31:0] token_q [0:K_MAX-1];
  integer insert_position;
  integer scan_index;
  integer sequential_index;

  always_comb begin
    insert_position = K_MAX;
    for (scan_index = 0; scan_index < K_MAX; scan_index = scan_index + 1) begin
      if ((insert_position == K_MAX) && (scan_index < k_q) &&
          ((scan_index >= count_q) ||
           (candidate_score_i > score_q[scan_index]) ||
           ((candidate_score_i == score_q[scan_index]) &&
            (candidate_token_i < token_q[scan_index]))))
        insert_position = scan_index;
    end
  end

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
      for (sequential_index = 0; sequential_index < K_MAX; sequential_index = sequential_index + 1) begin
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
          if (candidate_valid_i && candidate_ready_o && (insert_position < K_MAX)) begin
            for (sequential_index = K_MAX - 1; sequential_index > 0; sequential_index = sequential_index - 1) begin
              if ((sequential_index > insert_position) && (sequential_index < k_q)) begin
                score_q[sequential_index] <= score_q[sequential_index-1];
                token_q[sequential_index] <= token_q[sequential_index-1];
              end
            end
            score_q[insert_position] <= candidate_score_i;
            token_q[insert_position] <= candidate_token_i;
            if (count_q < k_q) count_q <= count_q + 1'b1;
          end
          if (finish_valid_i && finish_ready_o) begin
            output_index_q <= '0;
            state_q <= (count_q == 0) ? IDLE : OUTPUT;
          end
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
