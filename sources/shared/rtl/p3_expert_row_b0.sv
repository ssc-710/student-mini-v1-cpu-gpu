// SPDX-License-Identifier: Apache-2.0
// Bit-accurate serial P3 expert datapath for one routed row.
//
// The surrounding tile/DMA engine supplies one activation plus gate/up weight
// triplet per hidden element, then one down weight per intermediate element.
// This core performs the complete gate/up GEMM row, SiLU*up requantization,
// down GEMM row, route scaling and BF16-RNE output.  It intentionally trades
// throughput for a small, transparent B0 state machine.
module p3_expert_row_b0 #(
  parameter int MAX_HIDDEN = 256,
  parameter int MAX_INTERMEDIATE = 64,
  parameter bit PIPELINED_SILU = 1'b0
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

  typedef enum logic [2:0] {
    IDLE, GATE_SCAN, STORE_INTERMEDIATE, SILU_WAIT,
    DOWN_SCAN, EMIT_OUTPUT, RESPONSE
  } state_t;
  state_t state_q;
  logic [15:0] hidden_q, intermediate_count_q;
  logic [15:0] hidden_index_q, intermediate_index_q, output_index_q;
  logic waiting_q;
  logic signed [31:0] gate_acc_q, up_acc_q, down_acc_q;
  logic signed [7:0] intermediate_mem [0:MAX_INTERMEDIATE-1];
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;

  logic signed [15:0] gate_product_w, up_product_w, down_product_w;
  logic signed [31:0] gate_acc_next_w, up_acc_next_w, down_acc_next_w;
  assign gate_product_w = data_rsp_activation_i * data_rsp_gate_weight_i;
  assign up_product_w = data_rsp_activation_i * data_rsp_up_weight_i;
  assign down_product_w =
    intermediate_mem[intermediate_index_q[INTERMEDIATE_INDEX_WIDTH-1:0]] *
    data_rsp_down_weight_i;
  assign gate_acc_next_w = gate_acc_q + {{16{gate_product_w[15]}}, gate_product_w};
  assign up_acc_next_w = up_acc_q + {{16{up_product_w[15]}}, up_product_w};
  assign down_acc_next_w = down_acc_q + {{16{down_product_w[15]}}, down_product_w};

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

  logic signed [15:0] gate_q11_w, up_q11_w, silu_q11_w;
  logic signed [15:0] silu_sync_w, up_q11_q;
  logic signed [15:0] silu_selected_w, up_selected_w;
  logic silu_sync_valid;
  logic gate_q_valid, up_q_valid, requant_bad;
  logic signed [31:0] activated_q22_narrow_w;
  logic signed [47:0] activated_q22_w;
  logic signed [7:0] intermediate_i8_w;
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_gate_q(
    .value_i(gate_acc_q), .scale_i(gate_combined_w),
    .q5_11_o(gate_q11_w), .scale_valid_o(gate_q_valid));
  int32_scale_to_q5_11 #(.REQUIRE_PROJECT_SCALE_RANGE(1'b0)) u_up_q(
    .value_i(up_acc_q), .scale_i(up_combined_w),
    .q5_11_o(up_q11_w), .scale_valid_o(up_q_valid));
  silu_q11 u_silu(.x_q11_i(gate_q11_w), .silu_q11_o(silu_q11_w));
  silu_q11_sync u_silu_sync(
    .clk_i, .rst_ni,
    .valid_i((state_q == STORE_INTERMEDIATE) && PIPELINED_SILU &&
             gate_q_valid && up_q_valid),
    .x_q11_i(gate_q11_w), .valid_o(silu_sync_valid), .silu_q11_o(silu_sync_w));
  assign silu_selected_w = PIPELINED_SILU ? silu_sync_w : silu_q11_w;
  assign up_selected_w = PIPELINED_SILU ? up_q11_q : up_q11_w;
  assign activated_q22_narrow_w = silu_selected_w * up_selected_w;
  assign activated_q22_w = {{16{activated_q22_narrow_w[31]}}, activated_q22_narrow_w};
  q22_requantize_int8 u_requant(
    .value_q22_i(activated_q22_w), .scale_i(intermediate_scale_i),
    .value_i8_o(intermediate_i8_w), .invalid_scale_o(requant_bad));

  logic [31:0] output_scale_0_w, output_scale_w;
  logic output_mul_0_bad, output_mul_bad, output_bf16_bad;
  logic [15:0] output_bf16_w;
  fp32_positive_mul_rne u_output_scale_0(
    .a_i(intermediate_scale_i), .b_i(down_scale_i),
    .product_o(output_scale_0_w), .invalid_o(output_mul_0_bad));
  fp32_positive_mul_rne u_output_scale_1(
    .a_i(output_scale_0_w), .b_i(route_weight_i),
    .product_o(output_scale_w), .invalid_o(output_mul_bad));
  int32_times_fp32_to_bf16 u_output_bf16(
    .value_i(down_acc_next_w), .scale_i(output_scale_w),
    .bf16_o(output_bf16_w), .invalid_scale_o(output_bf16_bad));

  logic numeric_inputs_valid_w;
  assign numeric_inputs_valid_w = input_scale_valid && gate_scale_valid &&
    up_scale_valid && intermediate_scale_valid && down_scale_valid &&
    !gate_mul_bad && !up_mul_bad && !output_mul_0_bad && !output_mul_bad &&
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
      gate_acc_q <= '0; up_acc_q <= '0; down_acc_q <= '0;
      up_q11_q <= '0;
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
          end else state_q <= GATE_SCAN;
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
              if (hidden_index_q + 1'b1 == hidden_q) state_q <= STORE_INTERMEDIATE;
              else hidden_index_q <= hidden_index_q + 1'b1;
            end
          end
        end
        STORE_INTERMEDIATE: begin
          if (!gate_q_valid || !up_q_valid || requant_bad) begin
            status_q <= STATUS_NUMERIC_ERROR;
            result_cycles_q <= cycles_q + 1'b1;
            state_q <= RESPONSE;
          end else if (PIPELINED_SILU) begin
            up_q11_q <= up_q11_w;
            state_q <= SILU_WAIT;
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
        SILU_WAIT: begin
          if (silu_sync_valid) begin
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
              down_acc_q <= down_acc_next_w;
              if (intermediate_index_q + 1'b1 == intermediate_count_q) begin
                output_bf16_o <= (route_weight_i == 0) ? 16'd0 : output_bf16_w;
                if ((route_weight_i != 0) && output_bf16_bad)
                  status_q <= STATUS_NUMERIC_ERROR;
                state_q <= EMIT_OUTPUT;
              end else intermediate_index_q <= intermediate_index_q + 1'b1;
            end
          end
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
