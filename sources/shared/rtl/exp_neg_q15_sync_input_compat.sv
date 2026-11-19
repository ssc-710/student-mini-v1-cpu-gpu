// SPDX-License-Identifier: Apache-2.0
// Candidate-local replacement for exp_neg_q15_sync.  Compile this file and
// exp_neg_q15_sync_input_pipeline.sv instead of exp_neg_q15_sync.sv.
module exp_neg_q15_sync (
  input logic clk_i, input logic rst_ni,
  input logic valid_i, input logic signed [15:0] x_q11_i,
  output logic valid_o, output logic [15:0] exp_q15_o
);
  exp_neg_q15_sync_input_pipeline u_pipeline (.*);
endmodule
