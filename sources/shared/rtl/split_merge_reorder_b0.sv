// SPDX-License-Identifier: Apache-2.0
// Buffers four arbitrarily arriving split states, then applies the project
// contract: arithmetic merge order is always ascending split id.
module split_merge_reorder_b0 (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic partial_valid_i, output logic partial_ready_o,
  input logic [1:0] split_id_i,
  input logic signed [15:0] maximum_q11_i,
  input logic [47:0] denominator_q15_i,
  input logic signed [63:0] weighted_q15_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o,
  output logic signed [15:0] maximum_q11_o,
  output logic [47:0] denominator_q15_o,
  output logic signed [63:0] weighted_q15_o
);
  typedef enum logic [1:0] {IDLE, COLLECT, MERGE, RESPONSE} state_t;
  state_t state_q;
  logic [3:0] received_q;
  logic [2:0] count_q;
  logic [1:0] merge_index_q;
  logic signed [15:0] max_q [0:3];
  logic [47:0] sum_q [0:3];
  logic signed [63:0] weighted_q [0:3];
  logic signed [15:0] merged_max_q, merge_max_w;
  logic [47:0] merged_sum_q, merge_sum_w;
  logic signed [63:0] merged_weighted_q, merge_weighted_w;
  integer index;

  softmax_merge_q u_merge (
    .left_max_i(merged_max_q), .left_sum_i(merged_sum_q),
    .left_weighted_i(merged_weighted_q),
    .right_max_i(max_q[merge_index_q]), .right_sum_i(sum_q[merge_index_q]),
    .right_weighted_i(weighted_q[merge_index_q]),
    .merged_max_o(merge_max_w), .merged_sum_o(merge_sum_w),
    .merged_weighted_o(merge_weighted_w)
  );
  assign cmd_ready_o = state_q == IDLE;
  assign partial_ready_o = state_q == COLLECT;
  assign rsp_valid_o = state_q == RESPONSE;
  assign maximum_q11_o = merged_max_q;
  assign denominator_q15_o = merged_sum_q;
  assign weighted_q15_o = merged_weighted_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; received_q <= '0; count_q <= '0; merge_index_q <= '0;
      merged_max_q <= '0; merged_sum_q <= '0; merged_weighted_q <= '0;
      rsp_status_o <= '0;
      for (index = 0; index < 4; index = index + 1) begin
        max_q[index] <= '0; sum_q[index] <= '0; weighted_q[index] <= '0;
      end
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          received_q <= '0; count_q <= '0; rsp_status_o <= '0;
          state_q <= COLLECT;
        end
        COLLECT: if (partial_valid_i) begin
          if (received_q[split_id_i]) begin
            rsp_status_o <= 8'd1;
            state_q <= RESPONSE;
          end else begin
            received_q[split_id_i] <= 1'b1;
            max_q[split_id_i] <= maximum_q11_i;
            sum_q[split_id_i] <= denominator_q15_i;
            weighted_q[split_id_i] <= weighted_q15_i;
            count_q <= count_q + 1'b1;
            if (count_q == 3) begin
              merge_index_q <= 1;
              // The last arriving value may be split zero; bypass its input
              // because nonblocking array writes commit after this edge.
              merged_max_q <= split_id_i == 0 ? maximum_q11_i : max_q[0];
              merged_sum_q <= split_id_i == 0 ? denominator_q15_i : sum_q[0];
              merged_weighted_q <= split_id_i == 0 ? weighted_q15_i : weighted_q[0];
              state_q <= MERGE;
            end
          end
        end
        MERGE: begin
          merged_max_q <= merge_max_w;
          merged_sum_q <= merge_sum_w;
          merged_weighted_q <= merge_weighted_w;
          if (merge_index_q == 3) state_q <= RESPONSE;
          else merge_index_q <= merge_index_q + 1'b1;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
