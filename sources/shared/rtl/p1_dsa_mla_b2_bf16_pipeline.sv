// SPDX-License-Identifier: Apache-2.0
// P1 B2 timing wrapper.  The frozen B1c core produces the bit-exact q16
// vector; one formatter per value lane converts the complete vector in
// parallel and registers it before the descriptor/DMA shell can observe it.
module p1_dsa_mla_b2_bf16_pipeline #(
  parameter int K_MAX = 32,
  parameter int VALUE_DIM = 1,
  parameter bit PIPELINED_SOFTMAX = 1'b0,
  localparam int K_WIDTH = $clog2(K_MAX + 1)
) (
  input  logic                         clk_i,
  input  logic                         rst_ni,
  input  logic                         cmd_valid_i,
  output logic                         cmd_ready_o,
  input  logic [31:0]                  visible_count_i,
  input  logic [7:0]                   topk_i,
  input  logic [31:0]                  value_scale_i,
  output logic                         mem_req_valid_o,
  input  logic                         mem_req_ready_i,
  output logic                         mem_req_mla_o,
  output logic [31:0]                  mem_req_token_o,
  input  logic                         mem_rsp_valid_i,
  output logic                         mem_rsp_ready_o,
  input  logic signed [15:0]           mem_rsp_index_score_q11_i,
  input  logic signed [15:0]           mem_rsp_mla_score_q11_i,
  input  logic signed [VALUE_DIM*8-1:0] mem_rsp_value_i,
  input  logic                         mem_rsp_error_i,
  output logic                         rsp_valid_o,
  input  logic                         rsp_ready_i,
  output logic [7:0]                   rsp_status_o,
  output logic [63:0]                  rsp_cycles_o,
  output logic signed [31:0]           output_q16_o,
  output logic [15:0]                  output_bf16_o,
  output logic signed [VALUE_DIM*32-1:0] output_q16_vector_o,
  output logic [VALUE_DIM*16-1:0]      output_bf16_vector_o,
  output logic [K_WIDTH-1:0]           selected_count_o,
  output logic [K_MAX*32-1:0]          selected_tokens_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  typedef enum logic [1:0] {RUN_CORE, START_FORMAT, WAIT_FORMAT, RESPONSE} state_t;
  state_t state_q;

  logic core_cmd_ready, core_rsp_valid, core_rsp_ready;
  logic [7:0] core_rsp_status;
  logic [63:0] core_rsp_cycles;
  logic signed [VALUE_DIM*32-1:0] core_q16_vector;
  logic signed [31:0] core_q16;
  logic [15:0] unused_core_bf16;
  logic [VALUE_DIM*16-1:0] unused_core_bf16_vector;
  logic [31:0] adjusted_scale_w, adjusted_scale_q;
  logic adjusted_scale_bad;
  logic [7:0] status_q;
  logic [63:0] result_cycles_q, format_cycles_q;

  fp32_positive_mul_rne u_output_scale_adjust (
    .a_i(value_scale_i), .b_i(32'h37800000),
    .product_o(adjusted_scale_w), .invalid_o(adjusted_scale_bad)
  );

  p1_dsa_mla_b1_product_pipeline #(
    .K_MAX(K_MAX), .VALUE_DIM(VALUE_DIM),
    .PIPELINED_SOFTMAX(PIPELINED_SOFTMAX)
  ) u_core (
    .clk_i, .rst_ni,
    .cmd_valid_i(cmd_valid_i && state_q == RUN_CORE),
    .cmd_ready_o(core_cmd_ready), .visible_count_i, .topk_i, .value_scale_i,
    .mem_req_valid_o, .mem_req_ready_i, .mem_req_mla_o, .mem_req_token_o,
    .mem_rsp_valid_i, .mem_rsp_ready_o, .mem_rsp_index_score_q11_i,
    .mem_rsp_mla_score_q11_i, .mem_rsp_value_i, .mem_rsp_error_i,
    .rsp_valid_o(core_rsp_valid), .rsp_ready_i(core_rsp_ready),
    .rsp_status_o(core_rsp_status), .rsp_cycles_o(core_rsp_cycles),
    .output_q16_o(core_q16), .output_bf16_o(unused_core_bf16),
    .output_q16_vector_o(core_q16_vector),
    .output_bf16_vector_o(unused_core_bf16_vector),
    .selected_count_o, .selected_tokens_o
  );

  logic formatter_cmd_ready [0:VALUE_DIM-1];
  logic formatter_rsp_valid [0:VALUE_DIM-1];
  logic formatter_rsp_ready;
  logic [15:0] formatter_bf16 [0:VALUE_DIM-1];
  logic formatter_bad [0:VALUE_DIM-1];
  // Give every physical formatter a local, registered launch bit.  Driving
  // all formatter input registers directly from the encoded outer state made
  // START_FORMAT a chip-wide high-fanout timing path at the 64-lane profile.
  logic [VALUE_DIM-1:0] formatter_launch_q;
  logic all_formatter_cmd_ready, all_formatter_rsp_valid, any_formatter_bad;
  genvar lane;
  generate for (lane = 0; lane < VALUE_DIM; lane++) begin : g_formatter
    int32_times_fp32_to_bf16_pipeline u_formatter (
      .clk_i, .rst_ni,
      .cmd_valid_i(formatter_launch_q[lane]),
      .cmd_ready_o(formatter_cmd_ready[lane]),
      .value_i(core_q16_vector[lane*32 +: 32]),
      .scale_i(adjusted_scale_q),
      .rsp_valid_o(formatter_rsp_valid[lane]),
      .rsp_ready_i(formatter_rsp_ready),
      .bf16_o(formatter_bf16[lane]),
      .invalid_scale_o(formatter_bad[lane])
    );
  end endgenerate

  integer reduce_lane;
  always_comb begin
    all_formatter_cmd_ready = 1'b1;
    all_formatter_rsp_valid = 1'b1;
    any_formatter_bad = 1'b0;
    for (reduce_lane = 0; reduce_lane < VALUE_DIM; reduce_lane++) begin
      all_formatter_cmd_ready &= formatter_cmd_ready[reduce_lane];
      all_formatter_rsp_valid &= formatter_rsp_valid[reduce_lane];
      any_formatter_bad |= formatter_bad[reduce_lane];
    end
  end

  assign cmd_ready_o = state_q == RUN_CORE && core_cmd_ready;
  assign core_rsp_ready = state_q == RESPONSE && rsp_ready_i;
  assign formatter_rsp_ready = state_q == WAIT_FORMAT && all_formatter_rsp_valid;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;
  assign output_q16_o = core_q16;
  assign output_q16_vector_o = core_q16_vector;
  assign output_bf16_o = output_bf16_vector_o[15:0];

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= RUN_CORE;
      adjusted_scale_q <= '0;
      status_q <= STATUS_OK;
      result_cycles_q <= '0;
      format_cycles_q <= '0;
      output_bf16_vector_o <= '0;
      formatter_launch_q <= '0;
    end else begin
      if (cmd_valid_i && cmd_ready_o) begin
        adjusted_scale_q <= adjusted_scale_w;
        status_q <= STATUS_OK;
        result_cycles_q <= '0;
        format_cycles_q <= '0;
        output_bf16_vector_o <= '0;
      end
      if (state_q == START_FORMAT && all_formatter_cmd_ready)
        formatter_launch_q <= '0;
      if (state_q == START_FORMAT || state_q == WAIT_FORMAT)
        format_cycles_q <= format_cycles_q + 1'b1;
      unique case (state_q)
        RUN_CORE: if (core_rsp_valid) begin
          status_q <= core_rsp_status;
          result_cycles_q <= core_rsp_cycles;
          if (core_rsp_status != STATUS_OK)
            state_q <= RESPONSE;
          else begin
            formatter_launch_q <= '1;
            state_q <= START_FORMAT;
          end
        end
        START_FORMAT: if (all_formatter_cmd_ready) state_q <= WAIT_FORMAT;
        WAIT_FORMAT: if (all_formatter_rsp_valid) begin
          for (int capture_lane = 0; capture_lane < VALUE_DIM; capture_lane++)
            output_bf16_vector_o[capture_lane*16 +: 16] <=
              formatter_bf16[capture_lane];
          if (any_formatter_bad) status_q <= 8'd4;
          result_cycles_q <= core_rsp_cycles + format_cycles_q + 1'b1;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= RUN_CORE;
        default: state_q <= RUN_CORE;
      endcase
    end
  end

  logic unused_adjusted_scale_bad;
  assign unused_adjusted_scale_bad = adjusted_scale_bad;
endmodule
