// SPDX-License-Identifier: Apache-2.0
// Timing wrapper for the bit-exact B1b Split-KV core.
//
// The measured B1b post-route path crossed the combinational integer/FP32 to
// BF16 writer.  Keep the already-proved scan, merge and divide implementation,
// but consume its registered Q16 quotient through the multi-cycle serial BF16
// formatter.  The wrapped core remains in RESPONSE until this wrapper's
// response is accepted, so neither payload nor command ownership can change.
module p2_split_kv_b3_serial_output #(
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  parameter bit RADIX16_MERGE = 1'b0
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    cmd_valid_i,
  output logic                    cmd_ready_o,
  input  logic [31:0]             cache_len_i,
  input  logic [3:0]              splits_i,
  input  logic [7:0]              page_size_i,
  input  logic [31:0]             value_scale_i,
  output logic                    token_req_valid_o,
  input  logic                    token_req_ready_i,
  output logic [31:0]             token_index_o,
  output logic [3:0]              split_id_o,
  input  logic                    token_rsp_valid_i,
  output logic                    token_rsp_ready_o,
  input  logic signed [15:0]      token_rsp_score_q11_i,
  input  logic signed [7:0]       token_rsp_value_i,
  input  logic                    token_rsp_error_i,
  output logic                    rsp_valid_o,
  input  logic                    rsp_ready_i,
  output logic [7:0]              rsp_status_o,
  output logic [63:0]             rsp_cycles_o,
  output logic signed [31:0]      output_q16_o,
  output logic [15:0]             output_bf16_o,
  output logic signed [15:0]      merged_max_q11_o,
  output logic [47:0]             merged_sum_q15_o,
  output logic signed [63:0]      merged_weighted_q15_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;

  typedef enum logic [1:0] {RUN_CORE, START_FORMAT, WAIT_FORMAT, RESPONSE} state_t;
  state_t state_q;

  logic core_cmd_ready, core_rsp_valid, core_rsp_ready;
  logic [7:0] core_rsp_status;
  logic [63:0] core_rsp_cycles;
  logic signed [31:0] core_output_q16;
  logic [15:0] unused_core_bf16;
  logic [63:0] format_cycles_q, result_cycles_q;
  logic [7:0] result_status_q;
  logic [15:0] result_bf16_q;

  p2_split_kv_b3_product_pipeline #(
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX),
    .RADIX16_MERGE(RADIX16_MERGE)
  ) u_core (
    .clk_i, .rst_ni,
    .cmd_valid_i(cmd_valid_i && state_q == RUN_CORE),
    .cmd_ready_o(core_cmd_ready),
    .cache_len_i, .splits_i, .page_size_i, .value_scale_i,
    .token_req_valid_o, .token_req_ready_i, .token_index_o, .split_id_o,
    .token_rsp_valid_i, .token_rsp_ready_o, .token_rsp_score_q11_i,
    .token_rsp_value_i, .token_rsp_error_i,
    .rsp_valid_o(core_rsp_valid), .rsp_ready_i(core_rsp_ready),
    .rsp_status_o(core_rsp_status), .rsp_cycles_o(core_rsp_cycles),
    .output_q16_o(core_output_q16), .output_bf16_o(unused_core_bf16),
    .merged_max_q11_o, .merged_sum_q15_o, .merged_weighted_q15_o
  );

  logic [31:0] output_scale_adjusted_w;
  logic output_scale_bad_w;
  fp32_positive_mul_rne u_output_scale_adjust (
    .a_i(value_scale_i), .b_i(32'h37800000),
    .product_o(output_scale_adjusted_w), .invalid_o(output_scale_bad_w)
  );

  logic formatter_cmd_ready, formatter_rsp_valid, formatter_rsp_ready;
  logic [15:0] formatter_bf16;
  logic formatter_invalid;
  int32_times_fp32_to_bf16_serial u_formatter (
    .clk_i, .rst_ni,
    .cmd_valid_i(state_q == START_FORMAT), .cmd_ready_o(formatter_cmd_ready),
    .value_i(core_output_q16), .scale_i(output_scale_adjusted_w),
    .rsp_valid_o(formatter_rsp_valid), .rsp_ready_i(formatter_rsp_ready),
    .bf16_o(formatter_bf16), .invalid_scale_o(formatter_invalid)
  );
  assign formatter_rsp_ready = state_q == WAIT_FORMAT;

  assign cmd_ready_o = state_q == RUN_CORE && core_cmd_ready;
  assign core_rsp_ready = state_q == RESPONSE && rsp_ready_i;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = result_status_q;
  assign rsp_cycles_o = result_cycles_q;
  assign output_q16_o = core_output_q16;
  assign output_bf16_o = result_bf16_q;

  logic unused;
  assign unused = ^{unused_core_bf16, output_scale_bad_w, formatter_invalid};

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= RUN_CORE;
      format_cycles_q <= '0;
      result_cycles_q <= '0;
      result_status_q <= STATUS_OK;
      result_bf16_q <= '0;
    end else begin
      if (state_q == START_FORMAT || state_q == WAIT_FORMAT)
        format_cycles_q <= format_cycles_q + 1'b1;
      unique case (state_q)
        RUN_CORE: if (core_rsp_valid) begin
          format_cycles_q <= '0;
          result_status_q <= core_rsp_status;
          result_cycles_q <= core_rsp_cycles;
          if (core_rsp_status == STATUS_OK) state_q <= START_FORMAT;
          else state_q <= RESPONSE;
        end
        START_FORMAT: if (formatter_cmd_ready) state_q <= WAIT_FORMAT;
        WAIT_FORMAT: if (formatter_rsp_valid) begin
          result_bf16_q <= formatter_bf16;
          result_cycles_q <= core_rsp_cycles + format_cycles_q + 1'b1;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= RUN_CORE;
        default: state_q <= RUN_CORE;
      endcase
    end
  end
endmodule


