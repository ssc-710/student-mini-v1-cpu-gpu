// SPDX-License-Identifier: Apache-2.0
// Simulation/synthesis seam used to test the shared P1/P2/P3 numeric rules.
module numeric_contract_top (
  input  logic signed [31:0] value_i,
  input  logic        [31:0] scale_i,
  input  logic        [31:0] fp32_i,
  input  logic signed [63:0] dot_a_i,
  input  logic signed [63:0] dot_b_i,
  output logic signed [15:0] q5_11_o,
  output logic               scale_valid_o,
  output logic        [15:0] bf16_o,
  output logic signed [31:0] dot_o
);
  int32_scale_to_q5_11 u_score (
    .value_i(value_i), .scale_i(scale_i), .q5_11_o(q5_11_o),
    .scale_valid_o(scale_valid_o)
  );
  bf16_rne u_bf16 (.fp32_i(fp32_i), .bf16_o(bf16_o));
  int8_dot #(.LANES(8), .ACC_WIDTH(32)) u_dot (
    .a_i(dot_a_i), .b_i(dot_b_i), .sum_o(dot_o)
  );
endmodule
