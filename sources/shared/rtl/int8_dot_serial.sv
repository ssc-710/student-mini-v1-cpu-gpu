// SPDX-License-Identifier: Apache-2.0
// One-multiply-per-cycle signed INT8 dot product.
//
// The command freezes the vector length.  Input payload is accepted only on
// in_valid_i && in_ready_o; gaps and downstream response backpressure are
// therefore lossless.  The accumulator is exact INT32 for every frozen course
// profile (the largest supported dimension is 7168).
module int8_dot_serial (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    cmd_valid_i,
  output logic                    cmd_ready_o,
  input  logic [15:0]             length_i,
  input  logic                    in_valid_i,
  output logic                    in_ready_o,
  input  logic signed [7:0]       lhs_i,
  input  logic signed [7:0]       rhs_i,
  output logic                    rsp_valid_o,
  input  logic                    rsp_ready_i,
  output logic signed [31:0]      result_o,
  output logic                    length_error_o
);
  typedef enum logic [1:0] {IDLE, DOT, RESPONSE} state_t;
  state_t state_q;
  logic [15:0] length_q, index_q;
  logic signed [31:0] accumulator_q;
  logic signed [15:0] product_w;
  logic signed [31:0] next_accumulator_w;

  assign product_w = lhs_i * rhs_i;
  assign next_accumulator_w = accumulator_q +
    {{16{product_w[15]}}, product_w};
  assign cmd_ready_o = state_q == IDLE;
  assign in_ready_o = state_q == DOT;
  assign rsp_valid_o = state_q == RESPONSE;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      length_q <= '0;
      index_q <= '0;
      accumulator_q <= '0;
      result_o <= '0;
      length_error_o <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          length_q <= length_i;
          index_q <= '0;
          accumulator_q <= '0;
          result_o <= '0;
          length_error_o <= length_i == 0;
          state_q <= (length_i == 0) ? RESPONSE : DOT;
        end
        DOT: if (in_valid_i && in_ready_o) begin
          accumulator_q <= next_accumulator_w;
          if (index_q + 1'b1 == length_q) begin
            result_o <= next_accumulator_w;
            state_q <= RESPONSE;
          end else index_q <= index_q + 1'b1;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
