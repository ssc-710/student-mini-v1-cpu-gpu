// SPDX-License-Identifier: Apache-2.0
// One-item-per-cycle INT8 dot product with a registered multiply boundary.
module int8_dot_serial_pipelined (
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
  logic [15:0] length_q, accepted_q;
  logic signed [31:0] accumulator_q;
  logic signed [15:0] product_q;
  logic product_valid_q, product_last_q;
  logic accept_w;
  logic signed [31:0] accumulated_w;

  assign cmd_ready_o = state_q == IDLE;
  assign in_ready_o = state_q == DOT && accepted_q < length_q;
  assign rsp_valid_o = state_q == RESPONSE;
  assign accept_w = in_valid_i && in_ready_o;
  assign accumulated_w = accumulator_q + {{16{product_q[15]}}, product_q};

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      length_q <= '0;
      accepted_q <= '0;
      accumulator_q <= '0;
      product_q <= '0;
      product_valid_q <= 1'b0;
      product_last_q <= 1'b0;
      result_o <= '0;
      length_error_o <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          length_q <= length_i;
          accepted_q <= '0;
          accumulator_q <= '0;
          product_valid_q <= 1'b0;
          product_last_q <= 1'b0;
          result_o <= '0;
          length_error_o <= length_i == 0;
          state_q <= (length_i == 0) ? RESPONSE : DOT;
        end
        DOT: begin
          // Accumulate the prior accepted item while the multiplier captures
          // the next one.  The dependency loop is now only a 32-bit add.
          if (product_valid_q) begin
            accumulator_q <= accumulated_w;
            product_valid_q <= 1'b0;
            if (product_last_q) begin
              result_o <= accumulated_w;
              state_q <= RESPONSE;
            end
          end
          if (accept_w) begin
            product_q <= lhs_i * rhs_i;
            product_valid_q <= 1'b1;
            product_last_q <= accepted_q + 1'b1 == length_q;
            accepted_q <= accepted_q + 1'b1;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
