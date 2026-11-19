// Candidate-local compatibility name.  The B0 timing wrapper expects the
// serial formatter interface; R1 supplies the bit-exact multi-stage formatter
// behind that unchanged handshake, reducing format service cycles without
// enabling the later Radix-16 algorithm.
module int32_times_fp32_to_bf16_serial (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [31:0] value_i,
  input logic [31:0] scale_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [15:0] bf16_o,
  output logic invalid_scale_o
);
  int32_times_fp32_to_bf16_pipeline u_pipeline (.*);
endmodule
