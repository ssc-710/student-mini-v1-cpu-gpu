// SPDX-License-Identifier: Apache-2.0
// Candidate-local compatibility wrapper for the conservative bit-serial B0
// timing foundation.  Omit all other int32_scale_to_q5_11_pipeline modules.
module int32_scale_to_q5_11_pipeline #(
  parameter bit REQUIRE_PROJECT_SCALE_RANGE = 1'b1
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [31:0] value_i, input logic [31:0] scale_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [15:0] q5_11_o, output logic scale_valid_o
);
  int32_scale_to_q5_11_serial #(
    .REQUIRE_PROJECT_SCALE_RANGE(REQUIRE_PROJECT_SCALE_RANGE)
  ) u_serial (.*);
endmodule
