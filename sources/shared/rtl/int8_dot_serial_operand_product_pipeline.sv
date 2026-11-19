// SPDX-License-Identifier: Apache-2.0
// One-item-per-cycle INT8 dot product with separate operand and product cuts.
//
// The operand boundary prevents an upstream variable vector select from
// extending through the multiplier into product_q.  The product boundary
// retains the short 32-bit accumulation feedback loop of the B9 baseline.
module int8_dot_serial_operand_product_pipeline (
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
  logic signed [7:0] lhs_q, rhs_q;
  logic operand_valid_q, operand_last_q;
  logic signed [15:0] product_q;
  logic product_valid_q, product_last_q;
  logic signed [31:0] accumulator_q;
  logic accept_w;
  logic signed [31:0] accumulated_w;

  assign cmd_ready_o = state_q == IDLE;
  assign in_ready_o = state_q == DOT && accepted_q < length_q;
  assign rsp_valid_o = state_q == RESPONSE;
  assign accept_w = in_valid_i && in_ready_o;
  assign accumulated_w = accumulator_q +
    {{16{product_q[15]}}, product_q};

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      length_q <= '0;
      accepted_q <= '0;
      lhs_q <= '0;
      rhs_q <= '0;
      operand_valid_q <= 1'b0;
      operand_last_q <= 1'b0;
      product_q <= '0;
      product_valid_q <= 1'b0;
      product_last_q <= 1'b0;
      accumulator_q <= '0;
      result_o <= '0;
      length_error_o <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          length_q <= length_i;
          accepted_q <= '0;
          operand_valid_q <= 1'b0;
          operand_last_q <= 1'b0;
          product_valid_q <= 1'b0;
          product_last_q <= 1'b0;
          accumulator_q <= '0;
          result_o <= '0;
          length_error_o <= length_i == 0;
          state_q <= (length_i == 0) ? RESPONSE : DOT;
        end
        DOT: begin
          // Retire the product that was captured one cycle earlier.
          if (product_valid_q) begin
            accumulator_q <= accumulated_w;
            if (product_last_q) begin
              result_o <= accumulated_w;
              state_q <= RESPONSE;
            end
          end

          // Multiply only registered operands.  This is the isolated timing
          // change: upstream lane/index selection now ends at lhs_q/rhs_q.
          if (operand_valid_q) begin
            product_q <= lhs_q * rhs_q;
            product_valid_q <= 1'b1;
            product_last_q <= operand_last_q;
          end else begin
            product_valid_q <= 1'b0;
            product_last_q <= 1'b0;
          end

          if (accept_w) begin
            lhs_q <= lhs_i;
            rhs_q <= rhs_i;
            operand_valid_q <= 1'b1;
            operand_last_q <= accepted_q + 1'b1 == length_q;
            accepted_q <= accepted_q + 1'b1;
          end else begin
            operand_valid_q <= 1'b0;
            operand_last_q <= 1'b0;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
