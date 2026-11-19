// SPDX-License-Identifier: Apache-2.0
// Bit-exact registered version of fp32_positive_mul_rne.  The 24x24
// significand product is split into two 12x24 products so no state transition
// contains the full multiplier followed by normalization and RNE.
module fp32_positive_mul_rne_pipeline (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  logic        cmd_valid_i,
  output logic        cmd_ready_o,
  input  logic [31:0] a_i,
  input  logic [31:0] b_i,
  output logic        rsp_valid_o,
  input  logic        rsp_ready_i,
  output logic [31:0] product_o,
  output logic        invalid_o
);
  typedef enum logic [2:0] {IDLE, MULTIPLY, COMBINE, FORMAT, RESPONSE} state_t;
  state_t state_q;

  logic [7:0] a_exp_q, b_exp_q;
  logic [23:0] a_sig_q, b_sig_q;
  logic [35:0] low_product_q, high_product_q;
  logic [47:0] raw_q;
  logic [31:0] result_q;
  logic invalid_q;

  logic [23:0] kept_w;
  logic [24:0] rounded_w;
  logic guard_w, sticky_w;
  logic signed [10:0] exponent_w, final_exponent_w;

  always_comb begin
    if (raw_q[47]) begin
      kept_w = raw_q[47:24];
      guard_w = raw_q[23];
      sticky_w = |raw_q[22:0];
      exponent_w = $signed({3'd0, a_exp_q}) +
                   $signed({3'd0, b_exp_q}) - 11'sd126;
    end else begin
      kept_w = raw_q[46:23];
      guard_w = raw_q[22];
      sticky_w = |raw_q[21:0];
      exponent_w = $signed({3'd0, a_exp_q}) +
                   $signed({3'd0, b_exp_q}) - 11'sd127;
    end
    rounded_w = {1'b0, kept_w} +
                {24'd0, guard_w && (sticky_w || kept_w[0])};
    final_exponent_w = exponent_w + (rounded_w[24] ? 11'sd1 : 11'sd0);
  end

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign product_o = result_q;
  assign invalid_o = invalid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      a_exp_q <= '0;
      b_exp_q <= '0;
      a_sig_q <= '0;
      b_sig_q <= '0;
      low_product_q <= '0;
      high_product_q <= '0;
      raw_q <= '0;
      result_q <= '0;
      invalid_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          a_exp_q <= a_i[30:23];
          b_exp_q <= b_i[30:23];
          a_sig_q <= {1'b1, a_i[22:0]};
          b_sig_q <= {1'b1, b_i[22:0]};
          result_q <= '0;
          invalid_q <= a_i[31] || b_i[31] ||
                       a_i[30:23] == 8'hff || b_i[30:23] == 8'hff ||
                       (a_i[30:23] == 0 && a_i[22:0] != 0) ||
                       (b_i[30:23] == 0 && b_i[22:0] != 0);
          if (a_i[31] || b_i[31] ||
              a_i[30:23] == 8'hff || b_i[30:23] == 8'hff ||
              (a_i[30:23] == 0 && a_i[22:0] != 0) ||
              (b_i[30:23] == 0 && b_i[22:0] != 0) ||
              a_i[30:23] == 0 || b_i[30:23] == 0)
            state_q <= RESPONSE;
          else
            state_q <= MULTIPLY;
        end
        MULTIPLY: begin
          low_product_q <= a_sig_q[11:0] * b_sig_q;
          high_product_q <= a_sig_q[23:12] * b_sig_q;
          state_q <= COMBINE;
        end
        COMBINE: begin
          raw_q <= {high_product_q, 12'd0} +
                   {{12{1'b0}}, low_product_q};
          state_q <= FORMAT;
        end
        FORMAT: begin
          if (final_exponent_w >= 255) begin
            result_q <= 32'h7f7fffff;
            invalid_q <= 1'b1;
          end else if (final_exponent_w <= 0) begin
            result_q <= 32'd0;
            invalid_q <= 1'b1;
          end else if (rounded_w[24]) begin
            result_q <= {1'b0, final_exponent_w[7:0], rounded_w[23:1]};
          end else begin
            result_q <= {1'b0, final_exponent_w[7:0], rounded_w[22:0]};
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
