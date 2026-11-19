// SPDX-License-Identifier: Apache-2.0
// B23: bit-exact stable Top-K with a registered two-level insertion search.
// Four-entry groups compare in parallel; the following cycle selects the first
// winning group and commits the same stable shift as the B0 implementation.
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
  localparam int GROUP_SIZE = 4;
  localparam int GROUPS = (K_MAX + GROUP_SIZE - 1) / GROUP_SIZE;
  localparam int INDEX_WIDTH = $clog2(K_MAX);
  localparam logic [K_WIDTH-1:0] K_MAX_VALUE = K_WIDTH'(K_MAX);
  typedef enum logic [2:0] {IDLE, SCAN, COMMIT, OUTPUT} state_t;

  state_t state_q;
  logic [K_WIDTH-1:0] k_q, count_q, output_index_q;
  logic signed [15:0] score_q [0:K_MAX-1];
  logic [31:0] token_q [0:K_MAX-1];
  logic signed [15:0] candidate_score_q;
  logic [31:0] candidate_token_q;
  logic group_valid_w [0:GROUPS-1];
  logic [1:0] group_position_w [0:GROUPS-1];
  logic group_valid_q [0:GROUPS-1];
  logic [1:0] group_position_q [0:GROUPS-1];
  integer compare_group_index, compare_lane_index, compare_flat_index;
  integer select_group_index;
  integer commit_group, insert_position;
  integer sequential_index;

  always_comb begin
    for (compare_group_index = 0; compare_group_index < GROUPS; compare_group_index++) begin
      group_valid_w[compare_group_index] = 1'b0;
      group_position_w[compare_group_index] = '0;
      for (compare_lane_index = 0; compare_lane_index < GROUP_SIZE; compare_lane_index++) begin
        compare_flat_index = compare_group_index * GROUP_SIZE + compare_lane_index;
        if (!group_valid_w[compare_group_index] && compare_flat_index < K_MAX &&
            compare_flat_index < k_q &&
            ((compare_flat_index >= count_q) ||
             (candidate_score_i > score_q[compare_flat_index]) ||
             ((candidate_score_i == score_q[compare_flat_index]) &&
              (candidate_token_i < token_q[compare_flat_index])))) begin
          group_valid_w[compare_group_index] = 1'b1;
          group_position_w[compare_group_index] = 2'(compare_lane_index);
        end
      end
    end
  end

  always_comb begin
    commit_group = GROUPS;
    insert_position = K_MAX;
    for (select_group_index = 0; select_group_index < GROUPS; select_group_index++) begin
      if (commit_group == GROUPS && group_valid_q[select_group_index]) begin
        commit_group = select_group_index;
        insert_position = select_group_index * GROUP_SIZE +
                          integer'(group_position_q[select_group_index]);
      end
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
      state_q <= IDLE; k_q <= '0; count_q <= '0; output_index_q <= '0;
      candidate_score_q <= '0; candidate_token_q <= '0;
      for (sequential_index = 0; sequential_index < K_MAX; sequential_index++) begin
        score_q[sequential_index] <= '0; token_q[sequential_index] <= '0;
      end
      for (sequential_index = 0; sequential_index < GROUPS; sequential_index++) begin
        group_valid_q[sequential_index] <= '0;
        group_position_q[sequential_index] <= '0;
      end
    end else begin
      case (state_q)
        IDLE: if (start_valid_i && start_ready_o) begin
          k_q <= (k_i > K_MAX_VALUE) ? K_MAX_VALUE : k_i;
          count_q <= '0; output_index_q <= '0; state_q <= SCAN;
        end
        SCAN: begin
          if (candidate_valid_i && candidate_ready_o) begin
            candidate_score_q <= candidate_score_i;
            candidate_token_q <= candidate_token_i;
            for (sequential_index = 0; sequential_index < GROUPS; sequential_index++) begin
              group_valid_q[sequential_index] <= group_valid_w[sequential_index];
              group_position_q[sequential_index] <= group_position_w[sequential_index];
            end
            state_q <= COMMIT;
          end else if (finish_valid_i && finish_ready_o) begin
            output_index_q <= '0;
            state_q <= (count_q == 0) ? IDLE : OUTPUT;
          end
        end
        COMMIT: begin
          if (insert_position < K_MAX) begin
            for (sequential_index = K_MAX - 1; sequential_index > 0; sequential_index--) begin
              if ((sequential_index > insert_position) && (sequential_index < k_q)) begin
                score_q[sequential_index] <= score_q[sequential_index-1];
                token_q[sequential_index] <= token_q[sequential_index-1];
              end
            end
            score_q[insert_position] <= candidate_score_q;
            token_q[insert_position] <= candidate_token_q;
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
