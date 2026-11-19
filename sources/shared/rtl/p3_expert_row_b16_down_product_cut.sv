// SPDX-License-Identifier: Apache-2.0
// Bit-accurate serial P3 expert datapath for one routed row.
//
// The surrounding tile/DMA engine supplies one activation plus gate/up weight
// triplet per hidden element, then one down weight per intermediate element.
// This core performs the complete gate/up GEMM row, SiLU*up requantization,
// down GEMM row, route scaling and BF16-RNE output.  It intentionally trades
// throughput for a small, transparent B0 state machine.
module p3_expert_row_b16_down_product_cut #(
  parameter int MAX_HIDDEN = 256,
  parameter int MAX_INTERMEDIATE = 64,
  parameter bit PIPELINED_SILU = 1'b0,
  parameter bit PIPELINED_SCALE_QUANTIZE = 1'b0,
  parameter bit PIPELINED_COMBINED_SCALES = 1'b0,
  parameter bit PIPELINED_ACTIVATION_PRODUCT = 1'b0
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    cmd_valid_i,
  output logic                    cmd_ready_o,
  input  logic [15:0]             hidden_i,
  input  logic [15:0]             intermediate_i,
  input  logic [31:0]             input_scale_i,
  input  logic [31:0]             gate_scale_i,
  input  logic [31:0]             up_scale_i,
  input  logic [31:0]             intermediate_scale_i,
  input  logic [31:0]             down_scale_i,
  input  logic [31:0]             route_weight_i,

  output logic                    data_req_valid_o,
  input  logic                    data_req_ready_i,
  output logic                    data_req_down_o,
  output logic [15:0]             data_req_hidden_o,
  output logic [15:0]             data_req_intermediate_o,
  input  logic                    data_rsp_valid_i,
  output logic                    data_rsp_ready_o,
  input  logic signed [7:0]       data_rsp_activation_i,
  input  logic signed [7:0]       data_rsp_gate_weight_i,
  input  logic signed [7:0]       data_rsp_up_weight_i,
  input  logic signed [7:0]       data_rsp_down_weight_i,
  input  logic                    data_rsp_error_i,

  output logic                    output_valid_o,
  input  logic                    output_ready_i,
  output logic [15:0]             output_index_o,
  output logic [15:0]             output_bf16_o,
  output logic                    rsp_valid_o,
  input  logic                    rsp_ready_i,
  output logic [7:0]              rsp_status_o,
  output logic [63:0]             rsp_cycles_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_NUMERIC_ERROR = 8'd4;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;
  localparam int INTERMEDIATE_INDEX_WIDTH = $clog2(MAX_INTERMEDIATE);

  typedef enum logic [4:0] {
    IDLE, PREP_SCALE_0, PREP_SCALE_0_WAIT,
    PREP_SCALE_1, PREP_SCALE_1_WAIT, GATE_SCAN,
    QUANT_START, QUANT_WAIT, STORE_INTERMEDIATE, SILU_WAIT,
    ACTIVATE_LATCH, REQUANT_START, REQUANT_WAIT, DOWN_SCAN, DOWN_ACCUMULATE,
    LATCH_FINAL_ACC,
    FORMAT_START, FORMAT_WAIT, EMIT_OUTPUT, RESPONSE
  } state_t;
  state_t state_q;
  logic [15:0] hidden_q, intermediate_count_q;
  logic [15:0] hidden_index_q, intermediate_index_q, output_index_q;
  logic waiting_q;
  logic signed [31:0] gate_acc_q, up_acc_q, down_acc_q, final_acc_q;
  logic signed [7:0] intermediate_mem [0:MAX_INTERMEDIATE-1];
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;
  logic [31:0] gate_combined_q, up_combined_q;
  logic [31:0] output_scale_0_q, output_scale_q;

  logic signed [15:0] gate_product_w, up_product_w, down_product_w;
  logic signed [15:0] down_product_q;
  logic signed [31:0] gate_acc_next_w, up_acc_next_w, down_acc_next_w;
  assign gate_product_w = data_rsp_activation_i * data_rsp_gate_weight_i;
  assign up_product_w = data_rsp_activation_i * data_rsp_up_weight_i;
  assign down_product_w =
    intermediate_mem[intermediate_index_q[INTERMEDIATE_INDEX_WIDTH-1:0]] *
    data_rsp_down_weight_i;
  assign gate_acc_next_w = gate_acc_q + {{16{gate_product_w[15]}}, gate_product_w};
  assign up_acc_next_w = up_acc_q + {{16{up_product_w[15]}}, up_product_w};
  assign down_acc_next_w = down_acc_q + {{16{down_product_q[15]}}, down_product_q};

  logic input_scale_valid, gate_scale_valid, up_scale_valid;
  logic intermediate_scale_valid, down_scale_valid;
  fp32_scale_check u_input_check(.scale_i(input_scale_i), .valid_o(input_scale_valid));
  fp32_scale_check u_gate_check(.scale_i(gate_scale_i), .valid_o(gate_scale_valid));
  fp32_scale_check u_up_check(.scale_i(up_scale_i), .valid_o(up_scale_valid));
  fp32_scale_check u_intermediate_check(
    .scale_i(intermediate_scale_i), .valid_o(intermediate_scale_valid));
  fp32_scale_check u_down_check(.scale_i(down_scale_i), .valid_o(down_scale_valid));

  logic [31:0] gate_combined_w, up_combined_w;
  logic gate_mul_bad, up_mul_bad;
  fp32_positive_mul_rne u_gate_scale_mul(
    .a_i(input_scale_i), .b_i(gate_scale_i),
    .product_o(gate_combined_w), .invalid_o(gate_mul_bad));
  fp32_positive_mul_rne u_up_scale_mul(
    .a_i(input_scale_i), .b_i(up_scale_i),
    .product_o(up_combined_w), .invalid_o(up_mul_bad));

  logic gate_scale_pipe_ready, up_scale_pipe_ready, output_scale_0_pipe_ready;
  logic gate_scale_pipe_valid, up_scale_pipe_valid, output_scale_0_pipe_valid;
  logic [31:0] gate_scale_pipe_product, up_scale_pipe_product;
  logic [31:0] output_scale_0_pipe_product;
  logic gate_scale_pipe_bad, up_scale_pipe_bad, output_scale_0_pipe_bad;
  logic first_scale_group_valid_w;
  assign first_scale_group_valid_w = gate_scale_pipe_valid &&
    up_scale_pipe_valid && output_scale_0_pipe_valid;
  generate if (PIPELINED_COMBINED_SCALES) begin : g_combined_scale_pipelines
  fp32_positive_mul_rne_pipeline u_gate_scale_pipeline(
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_COMBINED_SCALES && state_q == PREP_SCALE_0),
    .cmd_ready_o(gate_scale_pipe_ready), .a_i(input_scale_i), .b_i(gate_scale_i),
    .rsp_valid_o(gate_scale_pipe_valid),
    .rsp_ready_i(state_q == PREP_SCALE_0_WAIT && first_scale_group_valid_w),
    .product_o(gate_scale_pipe_product), .invalid_o(gate_scale_pipe_bad));
  fp32_positive_mul_rne_pipeline u_up_scale_pipeline(
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_COMBINED_SCALES && state_q == PREP_SCALE_0),
    .cmd_ready_o(up_scale_pipe_ready), .a_i(input_scale_i), .b_i(up_scale_i),
    .rsp_valid_o(up_scale_pipe_valid),
    .rsp_ready_i(state_q == PREP_SCALE_0_WAIT && first_scale_group_valid_w),
    .product_o(up_scale_pipe_product), .invalid_o(up_scale_pipe_bad));
  fp32_positive_mul_rne_pipeline u_output_scale_0_pipeline(
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_COMBINED_SCALES && state_q == PREP_SCALE_0),
    .cmd_ready_o(output_scale_0_pipe_ready),
    .a_i(intermediate_scale_i), .b_i(down_scale_i),
    .rsp_valid_o(output_scale_0_pipe_valid),
    .rsp_ready_i(state_q == PREP_SCALE_0_WAIT && first_scale_group_valid_w),
    .product_o(output_scale_0_pipe_product), .invalid_o(output_scale_0_pipe_bad));
  end else begin : g_no_combined_scale_pipelines
    assign gate_scale_pipe_ready = 1'b0;
    assign up_scale_pipe_ready = 1'b0;
    assign output_scale_0_pipe_ready = 1'b0;
    assign gate_scale_pipe_valid = 1'b0;
    assign up_scale_pipe_valid = 1'b0;
    assign output_scale_0_pipe_valid = 1'b0;
    assign gate_scale_pipe_product = '0;
    assign up_scale_pipe_product = '0;
    assign output_scale_0_pipe_product = '0;
    assign gate_scale_pipe_bad = 1'b0;
    assign up_scale_pipe_bad = 1'b0;
    assign output_scale_0_pipe_bad = 1'b0;
  end endgenerate

  logic signed [15:0] gate_q11_w, up_q11_w, silu_q11_w;
  logic signed [15:0] gate_q11_q, up_q11_q;
  logic signed [15:0] silu_sync_w;
  logic signed [15:0] gate_source_w, up_source_w;
  logic signed [15:0] silu_selected_w, up_selected_w;
  logic silu_sync_valid;
  logic gate_q_valid, up_q_valid, requant_bad;
  logic requant_cmd_ready, requant_rsp_valid, requant_rsp_ready;
  logic signed [31:0] activated_q22_narrow_w;
  logic signed [47:0] activated_q22_w;
  logic signed [47:0] activated_q22_q;
  logic signed [7:0] intermediate_i8_w;
  assign gate_source_w = PIPELINED_SCALE_QUANTIZE ? gate_q11_q : gate_q11_w;
  assign up_source_w = PIPELINED_SCALE_QUANTIZE ? up_q11_q : up_q11_w;
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_gate_q(
    .value_i(gate_acc_q),
    .scale_i(PIPELINED_SCALE_QUANTIZE ? gate_combined_q : gate_combined_w),
    .q5_11_o(gate_q11_w), .scale_valid_o(gate_q_valid));
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_up_q(
    .value_i(up_acc_q),
    .scale_i(PIPELINED_SCALE_QUANTIZE ? up_combined_q : up_combined_w),
    .q5_11_o(up_q11_w), .scale_valid_o(up_q_valid));
  silu_q11 u_silu(.x_q11_i(gate_source_w), .silu_q11_o(silu_q11_w));
  silu_q11_sync u_silu_sync(
    .clk_i, .rst_ni,
    .valid_i((state_q == STORE_INTERMEDIATE) && PIPELINED_SILU &&
             (PIPELINED_SCALE_QUANTIZE || (gate_q_valid && up_q_valid))),
    .x_q11_i(gate_source_w), .valid_o(silu_sync_valid), .silu_q11_o(silu_sync_w));
  assign silu_selected_w = PIPELINED_SILU ? silu_sync_w : silu_q11_w;
  assign up_selected_w = PIPELINED_SILU ? up_q11_q : up_source_w;
  assign activated_q22_narrow_w = silu_selected_w * up_selected_w;
  assign activated_q22_w = {{16{activated_q22_narrow_w[31]}}, activated_q22_narrow_w};
  q22_requantize_int8_radix16 u_requant(
    .clk_i, .rst_ni,
    .cmd_valid_i(state_q == REQUANT_START), .cmd_ready_o(requant_cmd_ready),
    .value_q22_i(PIPELINED_ACTIVATION_PRODUCT ? activated_q22_q : activated_q22_w),
    .scale_i(intermediate_scale_i),
    .rsp_valid_o(requant_rsp_valid), .rsp_ready_i(requant_rsp_ready),
    .value_i8_o(intermediate_i8_w), .invalid_scale_o(requant_bad));
  assign requant_rsp_ready = state_q == REQUANT_WAIT;

  logic gate_quant_cmd_ready, up_quant_cmd_ready;
  logic gate_quant_rsp_valid, up_quant_rsp_valid;
  logic gate_quant_rsp_ready, up_quant_rsp_ready;
  logic gate_quant_scale_valid, up_quant_scale_valid;
  logic signed [15:0] gate_quant_q11, up_quant_q11;
  int32_scale_to_q5_11_pipeline #(
    .REQUIRE_PROJECT_SCALE_RANGE(1'b0)
  ) u_gate_quant_pipeline (
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_SCALE_QUANTIZE && state_q == QUANT_START),
    .cmd_ready_o(gate_quant_cmd_ready), .value_i(gate_acc_q),
    .scale_i(gate_combined_q), .rsp_valid_o(gate_quant_rsp_valid),
    .rsp_ready_i(gate_quant_rsp_ready), .q5_11_o(gate_quant_q11),
    .scale_valid_o(gate_quant_scale_valid)
  );
  int32_scale_to_q5_11_pipeline #(
    .REQUIRE_PROJECT_SCALE_RANGE(1'b0)
  ) u_up_quant_pipeline (
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_SCALE_QUANTIZE && state_q == QUANT_START),
    .cmd_ready_o(up_quant_cmd_ready), .value_i(up_acc_q),
    .scale_i(up_combined_q), .rsp_valid_o(up_quant_rsp_valid),
    .rsp_ready_i(up_quant_rsp_ready), .q5_11_o(up_quant_q11),
    .scale_valid_o(up_quant_scale_valid)
  );
  assign gate_quant_rsp_ready = state_q == QUANT_WAIT &&
                                gate_quant_rsp_valid && up_quant_rsp_valid;
  assign up_quant_rsp_ready = gate_quant_rsp_ready;

  logic [31:0] output_scale_0_w, output_scale_w;
  logic output_mul_0_bad, output_mul_bad;
  logic formatter_cmd_ready, formatter_rsp_valid, formatter_rsp_ready;
  logic formatter_bad;
  logic [15:0] formatter_bf16;
  fp32_positive_mul_rne u_output_scale_0(
    .a_i(intermediate_scale_i), .b_i(down_scale_i),
    .product_o(output_scale_0_w), .invalid_o(output_mul_0_bad));
  fp32_positive_mul_rne u_output_scale_1(
    .a_i(PIPELINED_SCALE_QUANTIZE ? output_scale_0_q : output_scale_0_w),
    .b_i(route_weight_i),
    .product_o(output_scale_w), .invalid_o(output_mul_bad));
  logic output_scale_pipe_ready, output_scale_pipe_valid, output_scale_pipe_bad;
  logic [31:0] output_scale_pipe_product;
  generate if (PIPELINED_COMBINED_SCALES) begin : g_output_scale_pipeline
  fp32_positive_mul_rne_pipeline u_output_scale_pipeline(
    .clk_i, .rst_ni,
    .cmd_valid_i(PIPELINED_COMBINED_SCALES && state_q == PREP_SCALE_1),
    .cmd_ready_o(output_scale_pipe_ready),
    .a_i(output_scale_0_q), .b_i(route_weight_i),
    .rsp_valid_o(output_scale_pipe_valid),
    .rsp_ready_i(state_q == PREP_SCALE_1_WAIT),
    .product_o(output_scale_pipe_product), .invalid_o(output_scale_pipe_bad));
  end else begin : g_no_output_scale_pipeline
    assign output_scale_pipe_ready = 1'b0;
    assign output_scale_pipe_valid = 1'b0;
    assign output_scale_pipe_bad = 1'b0;
    assign output_scale_pipe_product = '0;
  end endgenerate
  int32_times_fp32_to_bf16_pipeline u_output_bf16(
    .clk_i, .rst_ni,
    .cmd_valid_i(state_q == FORMAT_START),
    .cmd_ready_o(formatter_cmd_ready),
    .value_i(final_acc_q),
    .scale_i(PIPELINED_SCALE_QUANTIZE ? output_scale_q : output_scale_w),
    .rsp_valid_o(formatter_rsp_valid),
    .rsp_ready_i(formatter_rsp_ready),
    .bf16_o(formatter_bf16), .invalid_scale_o(formatter_bad));
  assign formatter_rsp_ready = state_q == FORMAT_WAIT;

  logic numeric_inputs_valid_w;
  assign numeric_inputs_valid_w = input_scale_valid && gate_scale_valid &&
    up_scale_valid && intermediate_scale_valid && down_scale_valid &&
    (PIPELINED_SCALE_QUANTIZE ||
      (!gate_mul_bad && !up_mul_bad && !output_mul_0_bad && !output_mul_bad)) &&
    !route_weight_i[31] && route_weight_i <= 32'h3f800000;

  assign cmd_ready_o = state_q == IDLE;
  assign data_req_valid_o = (state_q == GATE_SCAN || state_q == DOWN_SCAN) && !waiting_q;
  assign data_req_down_o = state_q == DOWN_SCAN;
  assign data_req_hidden_o = (state_q == GATE_SCAN) ? hidden_index_q : output_index_q;
  assign data_req_intermediate_o = intermediate_index_q;
  assign data_rsp_ready_o = waiting_q && (state_q == GATE_SCAN || state_q == DOWN_SCAN);
  assign output_valid_o = state_q == EMIT_OUTPUT;
  assign output_index_o = output_index_q;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;

  integer reset_index;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      hidden_q <= '0; intermediate_count_q <= '0;
      hidden_index_q <= '0; intermediate_index_q <= '0; output_index_q <= '0;
      waiting_q <= 1'b0;
      gate_acc_q <= '0; up_acc_q <= '0; down_acc_q <= '0; final_acc_q <= '0;
      down_product_q <= '0;
      gate_q11_q <= '0; up_q11_q <= '0;
      activated_q22_q <= '0;
      gate_combined_q <= '0; up_combined_q <= '0;
      output_scale_0_q <= '0; output_scale_q <= '0;
      output_bf16_o <= '0; status_q <= STATUS_OK;
      cycles_q <= '0; result_cycles_q <= '0;
      for (reset_index = 0; reset_index < MAX_INTERMEDIATE; reset_index++)
        intermediate_mem[reset_index] <= '0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          hidden_q <= hidden_i;
          intermediate_count_q <= intermediate_i;
          hidden_index_q <= '0; intermediate_index_q <= '0; output_index_q <= '0;
          waiting_q <= 1'b0;
          gate_acc_q <= '0; up_acc_q <= '0; down_acc_q <= '0;
          output_bf16_o <= '0; status_q <= STATUS_OK;
          cycles_q <= '0; result_cycles_q <= '0;
          if (hidden_i == 0 || hidden_i > 16'(MAX_HIDDEN) ||
              intermediate_i == 0 || intermediate_i > 16'(MAX_INTERMEDIATE)) begin
            status_q <= STATUS_BAD_DESCRIPTOR;
            state_q <= RESPONSE;
          end else if (!numeric_inputs_valid_w) begin
            status_q <= STATUS_NUMERIC_ERROR;
            state_q <= RESPONSE;
          end else if (PIPELINED_SCALE_QUANTIZE) state_q <= PREP_SCALE_0;
          else state_q <= GATE_SCAN;
        end
        PREP_SCALE_0: begin
          if (PIPELINED_COMBINED_SCALES) begin
            if (gate_scale_pipe_ready && up_scale_pipe_ready &&
                output_scale_0_pipe_ready)
              state_q <= PREP_SCALE_0_WAIT;
          end else if (gate_mul_bad || up_mul_bad || output_mul_0_bad) begin
            status_q <= STATUS_NUMERIC_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else begin
            gate_combined_q <= gate_combined_w;
            up_combined_q <= up_combined_w;
            output_scale_0_q <= output_scale_0_w;
            state_q <= PREP_SCALE_1;
          end
        end
        PREP_SCALE_0_WAIT: begin
          if (first_scale_group_valid_w) begin
            if (gate_scale_pipe_bad || up_scale_pipe_bad || output_scale_0_pipe_bad) begin
              status_q <= STATUS_NUMERIC_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              gate_combined_q <= gate_scale_pipe_product;
              up_combined_q <= up_scale_pipe_product;
              output_scale_0_q <= output_scale_0_pipe_product;
              state_q <= PREP_SCALE_1;
            end
          end
        end
        PREP_SCALE_1: begin
          if (PIPELINED_COMBINED_SCALES) begin
            if (output_scale_pipe_ready) state_q <= PREP_SCALE_1_WAIT;
          end else if (output_mul_bad) begin
            status_q <= STATUS_NUMERIC_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else begin
            output_scale_q <= output_scale_w;
            state_q <= GATE_SCAN;
          end
        end
        PREP_SCALE_1_WAIT: begin
          if (output_scale_pipe_valid) begin
            if (output_scale_pipe_bad) begin
              status_q <= STATUS_NUMERIC_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              output_scale_q <= output_scale_pipe_product;
              state_q <= GATE_SCAN;
            end
          end
        end
        GATE_SCAN: begin
          if (data_req_valid_o && data_req_ready_i) waiting_q <= 1'b1;
          if (data_rsp_valid_i && data_rsp_ready_o) begin
            waiting_q <= 1'b0;
            if (data_rsp_error_i) begin
              status_q <= STATUS_BUS_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              gate_acc_q <= gate_acc_next_w;
              up_acc_q <= up_acc_next_w;
              if (hidden_index_q + 1'b1 == hidden_q)
                state_q <= PIPELINED_SCALE_QUANTIZE ? QUANT_START : STORE_INTERMEDIATE;
              else hidden_index_q <= hidden_index_q + 1'b1;
            end
          end
        end
        QUANT_START: begin
          if (gate_quant_cmd_ready && up_quant_cmd_ready) state_q <= QUANT_WAIT;
        end
        QUANT_WAIT: begin
          if (gate_quant_rsp_valid && up_quant_rsp_valid) begin
            if (!gate_quant_scale_valid || !up_quant_scale_valid) begin
              status_q <= STATUS_NUMERIC_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              gate_q11_q <= gate_quant_q11;
              up_q11_q <= up_quant_q11;
              state_q <= STORE_INTERMEDIATE;
            end
          end
        end
        STORE_INTERMEDIATE: begin
          if (!PIPELINED_SCALE_QUANTIZE && (!gate_q_valid || !up_q_valid)) begin
            status_q <= STATUS_NUMERIC_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (PIPELINED_SILU) begin
            up_q11_q <= up_source_w;
            state_q <= SILU_WAIT;
          end else begin
            state_q <= REQUANT_START;
          end
        end
        SILU_WAIT: begin
          if (silu_sync_valid)
            state_q <= PIPELINED_ACTIVATION_PRODUCT ? ACTIVATE_LATCH : REQUANT_START;
        end
        ACTIVATE_LATCH: begin
          activated_q22_q <= activated_q22_w;
          state_q <= REQUANT_START;
        end
        REQUANT_START: begin
          if (requant_cmd_ready) state_q <= REQUANT_WAIT;
        end
        REQUANT_WAIT: begin
          if (requant_rsp_valid) begin
            if (requant_bad) begin
              status_q <= STATUS_NUMERIC_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              intermediate_mem[intermediate_index_q[INTERMEDIATE_INDEX_WIDTH-1:0]] <=
                intermediate_i8_w;
              if (intermediate_index_q + 1'b1 == intermediate_count_q) begin
                intermediate_index_q <= '0;
                output_index_q <= '0;
                down_acc_q <= '0;
                state_q <= DOWN_SCAN;
              end else begin
                intermediate_index_q <= intermediate_index_q + 1'b1;
                hidden_index_q <= '0;
                gate_acc_q <= '0;
                up_acc_q <= '0;
                state_q <= GATE_SCAN;
              end
            end
          end
        end
        DOWN_SCAN: begin
          if (data_req_valid_o && data_req_ready_i) waiting_q <= 1'b1;
          if (data_rsp_valid_i && data_rsp_ready_o) begin
            waiting_q <= 1'b0;
            if (data_rsp_error_i) begin
              status_q <= STATUS_BUS_ERROR;
              result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              // B16 timing cut: capture the memory-selected product first.
              // The following state performs only the sign extension and add,
              // removing index -> memory mux -> multiply -> accumulator.
              down_product_q <= down_product_w;
              state_q <= DOWN_ACCUMULATE;
            end
          end
        end
        DOWN_ACCUMULATE: begin
          down_acc_q <= down_acc_next_w;
          if (intermediate_index_q + 1'b1 == intermediate_count_q) begin
            final_acc_q <= down_acc_next_w;
            state_q <= LATCH_FINAL_ACC;
          end else begin
            intermediate_index_q <= intermediate_index_q + 1'b1;
            state_q <= DOWN_SCAN;
          end
        end
        LATCH_FINAL_ACC: begin
          if (route_weight_i == 0) begin
            output_bf16_o <= 16'd0;
            state_q <= EMIT_OUTPUT;
          end else begin
            state_q <= FORMAT_START;
          end
        end
        FORMAT_START: if (formatter_cmd_ready) state_q <= FORMAT_WAIT;
        FORMAT_WAIT: if (formatter_rsp_valid) begin
          output_bf16_o <= formatter_bf16;
          if (formatter_bad) status_q <= STATUS_NUMERIC_ERROR;
          state_q <= EMIT_OUTPUT;
        end
        EMIT_OUTPUT: if (output_valid_o && output_ready_i) begin
          if (status_q != STATUS_OK || output_index_q + 1'b1 == hidden_q) begin
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else begin
            output_index_q <= output_index_q + 1'b1;
            intermediate_index_q <= '0;
            down_acc_q <= '0;
            state_q <= DOWN_SCAN;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
