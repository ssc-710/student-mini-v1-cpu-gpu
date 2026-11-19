// SPDX-License-Identifier: Apache-2.0
// P3 B0 post-GEMM numeric slice for one intermediate lane and one output
// lane.  INT32 gate/up accumulators are scaled, SiLU-gated, requantized to
// INT8, multiplied by the down weight, route-scaled and written as BF16.
// Matrix traversal, descriptor/DMA and tile scheduling surround this seam.
module p3_post_gemm_b0 (
  input  logic signed [31:0] gate_acc_i,
  input  logic signed [31:0] up_acc_i,
  input  logic signed  [7:0] down_weight_i,
  input  logic        [31:0] input_scale_i,
  input  logic        [31:0] gate_scale_i,
  input  logic        [31:0] up_scale_i,
  input  logic        [31:0] intermediate_scale_i,
  input  logic        [31:0] down_scale_i,
  input  logic        [31:0] route_weight_i,
  output logic signed  [7:0] intermediate_i8_o,
  output logic        [15:0] output_bf16_o,
  output logic               numeric_error_o
);
  logic [31:0] gate_combined, up_combined, down_combined_0, down_combined;
  logic bad_gate_mul, bad_up_mul, bad_down_mul_0, bad_down_mul;
  fp32_positive_mul_rne u_gate_scale(
    .a_i(input_scale_i), .b_i(gate_scale_i), .product_o(gate_combined),
    .invalid_o(bad_gate_mul));
  fp32_positive_mul_rne u_up_scale(
    .a_i(input_scale_i), .b_i(up_scale_i), .product_o(up_combined),
    .invalid_o(bad_up_mul));
  fp32_positive_mul_rne u_down_scale0(
    .a_i(intermediate_scale_i), .b_i(down_scale_i),
    .product_o(down_combined_0), .invalid_o(bad_down_mul_0));
  fp32_positive_mul_rne u_down_scale1(
    .a_i(down_combined_0), .b_i(route_weight_i),
    .product_o(down_combined), .invalid_o(bad_down_mul));

  logic signed [15:0] gate_q11, up_q11, silu_q11_value;
  logic bad_gate_scale, bad_up_scale, bad_intermediate_scale, bad_output_scale;
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_gate_q(
    .value_i(gate_acc_i), .scale_i(gate_combined), .q5_11_o(gate_q11),
    .scale_valid_o(bad_gate_scale));
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_up_q(
    .value_i(up_acc_i), .scale_i(up_combined), .q5_11_o(up_q11),
    .scale_valid_o(bad_up_scale));
  silu_q11 u_silu(.x_q11_i(gate_q11), .silu_q11_o(silu_q11_value));

  logic signed [31:0] activated_q22_narrow;
  logic signed [47:0] activated_q22;
  assign activated_q22_narrow = silu_q11_value * up_q11;
  assign activated_q22 = {{16{activated_q22_narrow[31]}}, activated_q22_narrow};
  q22_requantize_int8 u_requant(
    .value_q22_i(activated_q22), .scale_i(intermediate_scale_i),
    .value_i8_o(intermediate_i8_o), .invalid_scale_o(bad_intermediate_scale));

  logic signed [31:0] down_acc;
  assign down_acc = intermediate_i8_o * down_weight_i;
  logic [15:0] scaled_output_bf16;
  int32_times_fp32_to_bf16 u_output(
    .value_i(down_acc), .scale_i(down_combined), .bf16_o(scaled_output_bf16),
    .invalid_scale_o(bad_output_scale));
  assign output_bf16_o = (route_weight_i == 0) ? 16'd0 : scaled_output_bf16;
  assign numeric_error_o = bad_gate_mul || bad_up_mul || bad_down_mul_0 ||
                           bad_down_mul || !bad_gate_scale || !bad_up_scale ||
                           bad_intermediate_scale ||
                           ((route_weight_i != 0) && bad_output_scale) ||
                           route_weight_i[31] || route_weight_i > 32'h3f800000;
endmodule
