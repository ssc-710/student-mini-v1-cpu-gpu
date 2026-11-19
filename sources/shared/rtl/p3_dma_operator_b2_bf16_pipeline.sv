// SPDX-License-Identifier: Apache-2.0
// P3 descriptor/DMA shell around the serial routed-row expert datapath.
//
// Descriptor v1 mapping for P3:
//   batch       = number of 16-byte tile descriptors
//   q_tokens    = total routed rows
//   kv_tokens   = hidden dimension
//   q_addr      = row-major INT8 activations
//   length_addr = {row_begin,row_count,expert_id,flags} tile descriptors
//   aux0_addr   = one FP32 route weight per row
//   weight_addr = per-expert gate, up, down INT8 matrices
//   scale_addr  = input, gate, up, intermediate, down FP32 scales
//   output_addr = row-major BF16 routed-row output
//   config      = {8'd0, experts[7:0], intermediate[15:0]}
// flags[0] marks the shared expert; it is legal only at expert_id==experts.
module p3_dma_operator_b2_bf16_pipeline #(
  parameter int MAX_HIDDEN = 256,
  parameter int MAX_INTERMEDIATE = 64,
  parameter bit PIPELINED_SILU = 1'b0,
  parameter bit PIPELINED_SCALE_QUANTIZE = 1'b0,
  parameter bit PIPELINED_COMBINED_SCALES = 1'b0,
  parameter bit PIPELINED_ACTIVATION_PRODUCT = 1'b0,
  parameter bit PIPELINED_ROW_BASE = 1'b0,
  // Register the per-request matrix row product before composing a DMA
  // address.  This is distinct from PIPELINED_ADDRESS_BASES: the latter
  // covers descriptor/tile-static products, while this cut covers the
  // req_intermediate*hidden and req_hidden*intermediate products.
  parameter bit PIPELINED_WEIGHT_ROW_BASE = 1'b0,
  // Register the BF16 output row base in the existing per-row preparation
  // state so DMA writes do not recompute absolute_row*hidden*2.
  parameter bit PIPELINED_OUTPUT_ROW_BASE = 1'b0,
  // Default zero preserves the frozen B2/B3 implementation.  B4 registers
  // descriptor- and tile-static address products before the row scan.
  parameter bit PIPELINED_ADDRESS_BASES = 1'b0
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [511:0] descriptor_i,
  output logic dma_req_valid_o, input logic dma_req_ready_i,
  output logic dma_req_write_o, output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o, output logic [15:0] dma_req_wstrb_o,
  input logic dma_rsp_valid_i, output logic dma_rsp_ready_o,
  input logic [127:0] dma_rsp_rdata_i, input logic dma_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o,
  output logic tile_start_o, output logic weight_switch_o
);
  localparam logic [7:0] STATUS_OK = 8'd0;
  localparam logic [7:0] STATUS_BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] STATUS_NUMERIC_ERROR = 8'd4;
  localparam logic [7:0] STATUS_BUS_ERROR = 8'd5;

  typedef enum logic [4:0] {
    IDLE, SCALE0_REQ, SCALE0_RSP, SCALE1_REQ, SCALE1_RSP,
    TILE_REQ, TILE_RSP, ROUTE_REQ, ROUTE_RSP, START_ROW, WAIT_CORE,
    ACT_REQ, ACT_RSP, GATE_REQ, GATE_RSP, UP_REQ, UP_RSP,
    DOWN_REQ, DOWN_RSP, FEED_CORE, WRITE_REQ, WRITE_RSP, RESPONSE,
    PREP_MATRIX, PREP_SPAN, PREP_EXPERT_BASE, PREP_ROW_BASE,
    PREP_DOWN_ADDRESS
  } state_t;
  state_t state_q;

  logic [31:0] tile_count_q, total_rows_q, hidden_q, intermediate_q, experts_q;
  logic [31:0] q_addr_q, tile_addr_q, route_addr_q, weight_addr_q;
  logic [31:0] scale_addr_q, output_addr_q;
  logic [31:0] tile_index_q, row_in_tile_q, row_begin_q, row_count_q, expert_q;
  logic [31:0] tile_flags_q, absolute_row_q, previous_expert_q;
  logic previous_expert_valid_q;
  logic [31:0] input_scale_q, gate_scale_q, up_scale_q;
  logic [31:0] intermediate_scale_q, down_scale_q, route_weight_q;
  logic [31:0] data_address_q;
  logic [3:0] data_lane_q;
  logic signed [7:0] activation_q, gate_weight_q, up_weight_q, down_weight_q;
  logic req_down_q;
  logic [15:0] req_hidden_q, req_intermediate_q;
  logic [15:0] output_index_q, output_bf16_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q, result_cycles_q;

  logic core_cmd_valid, core_cmd_ready;
  logic core_data_req_valid, core_data_req_ready, core_data_req_down;
  logic [15:0] core_data_req_hidden, core_data_req_intermediate;
  logic core_data_rsp_valid, core_data_rsp_ready;
  logic core_output_valid, core_output_ready;
  logic [15:0] core_output_index, core_output_bf16;
  logic core_rsp_valid, core_rsp_ready;
  logic [7:0] core_rsp_status;
  logic [63:0] core_rsp_cycles;

  p3_expert_row_b2_bf16_pipeline #(
    .MAX_HIDDEN(MAX_HIDDEN), .MAX_INTERMEDIATE(MAX_INTERMEDIATE),
    .PIPELINED_SILU(PIPELINED_SILU),
    .PIPELINED_SCALE_QUANTIZE(PIPELINED_SCALE_QUANTIZE),
    .PIPELINED_COMBINED_SCALES(PIPELINED_COMBINED_SCALES),
    .PIPELINED_ACTIVATION_PRODUCT(PIPELINED_ACTIVATION_PRODUCT)
  ) u_core (
    .clk_i, .rst_ni, .cmd_valid_i(core_cmd_valid), .cmd_ready_o(core_cmd_ready),
    .hidden_i(hidden_q[15:0]), .intermediate_i(intermediate_q[15:0]),
    .input_scale_i(input_scale_q), .gate_scale_i(gate_scale_q),
    .up_scale_i(up_scale_q), .intermediate_scale_i(intermediate_scale_q),
    .down_scale_i(down_scale_q), .route_weight_i(route_weight_q),
    .data_req_valid_o(core_data_req_valid), .data_req_ready_i(core_data_req_ready),
    .data_req_down_o(core_data_req_down), .data_req_hidden_o(core_data_req_hidden),
    .data_req_intermediate_o(core_data_req_intermediate),
    .data_rsp_valid_i(core_data_rsp_valid), .data_rsp_ready_o(core_data_rsp_ready),
    .data_rsp_activation_i(activation_q), .data_rsp_gate_weight_i(gate_weight_q),
    .data_rsp_up_weight_i(up_weight_q), .data_rsp_down_weight_i(down_weight_q),
    .data_rsp_error_i(1'b0), .output_valid_o(core_output_valid),
    .output_ready_i(core_output_ready), .output_index_o(core_output_index),
    .output_bf16_o(core_output_bf16), .rsp_valid_o(core_rsp_valid),
    .rsp_ready_i(core_rsp_ready), .rsp_status_o(core_rsp_status),
    .rsp_cycles_o(core_rsp_cycles)
  );

  assign cmd_ready_o = state_q == IDLE;
  assign core_cmd_valid = state_q == START_ROW;
  assign core_data_req_ready = state_q == WAIT_CORE;
  assign core_data_rsp_valid = state_q == FEED_CORE;
  assign core_output_ready = state_q == WAIT_CORE;
  assign core_rsp_ready = state_q == WAIT_CORE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = result_cycles_q;

  logic [63:0] matrix_size_w, expert_span_w, expert_base_w;
  logic [63:0] matrix_size_q, expert_span_q, expert_base_q;
  logic [63:0] activation_row_base_q, output_row_base_q;
  logic [63:0] weight_row_offset_q, up_row_base_q;
  logic [63:0] gate_offset_w, up_offset_w;
  logic [63:0] activation_request_offset_w, down_request_offset_w;
  logic [31:0] output_element_address_w;
  always_comb begin
    matrix_size_w = PIPELINED_ADDRESS_BASES ? matrix_size_q :
      (hidden_q * intermediate_q);
    expert_span_w = PIPELINED_ADDRESS_BASES ? expert_span_q : matrix_size_w * 3;
    expert_base_w = PIPELINED_ADDRESS_BASES ? expert_base_q :
      weight_addr_q + expert_q * expert_span_w;
    gate_offset_w = req_intermediate_q * hidden_q + req_hidden_q;
    up_offset_w = matrix_size_w + gate_offset_w;
    activation_request_offset_w = PIPELINED_ROW_BASE ?
      activation_row_base_q + core_data_req_hidden :
      absolute_row_q * hidden_q + core_data_req_hidden;
    down_request_offset_w = (matrix_size_w * 2) +
      core_data_req_hidden * intermediate_q + core_data_req_intermediate;
    output_element_address_w = PIPELINED_OUTPUT_ROW_BASE ?
      output_row_base_q[31:0] + ({16'd0, output_index_q} << 1) :
      output_addr_q + absolute_row_q * hidden_q * 2 + output_index_q * 2;
  end

  always_comb begin
    dma_req_valid_o = 1'b0;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = 32'd0;
    dma_req_wdata_o = 128'd0;
    dma_req_wstrb_o = 16'd0;
    dma_rsp_ready_o = 1'b0;
    unique case (state_q)
      SCALE0_REQ: begin dma_req_valid_o = 1'b1; dma_req_addr_o = scale_addr_q; end
      SCALE1_REQ: begin dma_req_valid_o = 1'b1; dma_req_addr_o = scale_addr_q + 16; end
      TILE_REQ: begin dma_req_valid_o = 1'b1; dma_req_addr_o = tile_addr_q + (tile_index_q << 4); end
      ROUTE_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = (route_addr_q + (absolute_row_q << 2)) & 32'hfffffff0;
      end
      ACT_REQ, GATE_REQ, UP_REQ, DOWN_REQ: begin
        dma_req_valid_o = 1'b1;
        dma_req_addr_o = {data_address_q[31:4], 4'b0};
      end
      WRITE_REQ: begin
        dma_req_valid_o = 1'b1; dma_req_write_o = 1'b1;
        dma_req_addr_o = output_element_address_w & 32'hfffffff0;
        dma_req_wdata_o = {{112{1'b0}}, output_bf16_q} <<
          (output_element_address_w[3:0] * 8);
        dma_req_wstrb_o = 16'h0003 <<
          output_element_address_w[3:0];
      end
      SCALE0_RSP, SCALE1_RSP, TILE_RSP, ROUTE_RSP, ACT_RSP, GATE_RSP,
      UP_RSP, DOWN_RSP, WRITE_RSP: dma_rsp_ready_o = 1'b1;
      default: begin end
    endcase
  end

  task automatic fail_bus;
    begin
      status_q <= STATUS_BUS_ERROR;
      result_cycles_q <= cycles_q + 1'b1;
      state_q <= RESPONSE;
    end
  endtask

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; tile_count_q <= '0; total_rows_q <= '0; hidden_q <= '0;
      intermediate_q <= '0; experts_q <= '0; q_addr_q <= '0; tile_addr_q <= '0;
      route_addr_q <= '0; weight_addr_q <= '0; scale_addr_q <= '0; output_addr_q <= '0;
      tile_index_q <= '0; row_in_tile_q <= '0; row_begin_q <= '0; row_count_q <= '0;
      expert_q <= '0; tile_flags_q <= '0; absolute_row_q <= '0; previous_expert_q <= '0;
      previous_expert_valid_q <= 1'b0; input_scale_q <= '0; gate_scale_q <= '0;
      up_scale_q <= '0; intermediate_scale_q <= '0; down_scale_q <= '0;
      route_weight_q <= '0; data_address_q <= '0; data_lane_q <= '0;
      matrix_size_q <= '0; expert_span_q <= '0; expert_base_q <= '0;
      activation_row_base_q <= '0; output_row_base_q <= '0;
      weight_row_offset_q <= '0; up_row_base_q <= '0;
      activation_q <= '0; gate_weight_q <= '0; up_weight_q <= '0; down_weight_q <= '0;
      req_down_q <= 1'b0; req_hidden_q <= '0; req_intermediate_q <= '0;
      output_index_q <= '0; output_bf16_q <= '0; status_q <= STATUS_OK;
      cycles_q <= '0; result_cycles_q <= '0; tile_start_o <= 1'b0; weight_switch_o <= 1'b0;
    end else begin
      tile_start_o <= 1'b0;
      weight_switch_o <= 1'b0;
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          tile_count_q <= descriptor_i[63:32]; total_rows_q <= descriptor_i[95:64];
          hidden_q <= descriptor_i[127:96]; q_addr_q <= descriptor_i[159:128];
          tile_addr_q <= descriptor_i[255:224]; route_addr_q <= descriptor_i[287:256];
          weight_addr_q <= descriptor_i[351:320]; scale_addr_q <= descriptor_i[383:352];
          output_addr_q <= descriptor_i[415:384]; intermediate_q <= {16'd0, descriptor_i[463:448]};
          experts_q <= {24'd0, descriptor_i[471:464]}; tile_index_q <= '0;
          previous_expert_valid_q <= 1'b0; cycles_q <= '0; result_cycles_q <= '0;
          status_q <= STATUS_OK;
          if (descriptor_i[63:32] == 0 || descriptor_i[95:64] == 0 ||
              descriptor_i[127:96] == 0 || descriptor_i[127:96] > MAX_HIDDEN ||
              descriptor_i[463:448] == 0 || descriptor_i[463:448] > MAX_INTERMEDIATE ||
              descriptor_i[471:464] == 0 || descriptor_i[227:224] != 0 ||
              descriptor_i[257:256] != 0 || descriptor_i[355:352] != 0 ||
              descriptor_i[384] != 0) begin
            status_q <= STATUS_BAD_DESCRIPTOR; state_q <= RESPONSE;
          end else if (PIPELINED_ADDRESS_BASES) state_q <= PREP_MATRIX;
          else state_q <= SCALE0_REQ;
        end
        PREP_MATRIX: begin
          matrix_size_q <= $unsigned(hidden_q[15:0]) *
            $unsigned(intermediate_q[15:0]);
          state_q <= PREP_SPAN;
        end
        PREP_SPAN: begin
          expert_span_q <= (matrix_size_q << 1) + matrix_size_q;
          state_q <= SCALE0_REQ;
        end
        SCALE0_REQ: if (dma_req_ready_i) state_q <= SCALE0_RSP;
        SCALE0_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin
            input_scale_q <= dma_rsp_rdata_i[31:0]; gate_scale_q <= dma_rsp_rdata_i[63:32];
            up_scale_q <= dma_rsp_rdata_i[95:64]; intermediate_scale_q <= dma_rsp_rdata_i[127:96];
            state_q <= SCALE1_REQ;
          end
        end
        SCALE1_REQ: if (dma_req_ready_i) state_q <= SCALE1_RSP;
        SCALE1_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin down_scale_q <= dma_rsp_rdata_i[31:0]; state_q <= TILE_REQ; end
        end
        TILE_REQ: if (dma_req_ready_i) state_q <= TILE_RSP;
        TILE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin
            row_begin_q <= dma_rsp_rdata_i[31:0]; row_count_q <= dma_rsp_rdata_i[63:32];
            expert_q <= dma_rsp_rdata_i[95:64]; tile_flags_q <= dma_rsp_rdata_i[127:96];
            row_in_tile_q <= '0; absolute_row_q <= dma_rsp_rdata_i[31:0];
            if (dma_rsp_rdata_i[63:32] == 0) begin
              if (tile_index_q + 1'b1 == tile_count_q) begin
                result_cycles_q <= cycles_q + 1'b1; state_q <= RESPONSE;
              end else begin tile_index_q <= tile_index_q + 1'b1; state_q <= TILE_REQ; end
            end else if (dma_rsp_rdata_i[31:0] + dma_rsp_rdata_i[63:32] > total_rows_q ||
                         dma_rsp_rdata_i[95:64] > experts_q ||
                         (dma_rsp_rdata_i[95:64] == experts_q && !dma_rsp_rdata_i[96])) begin
              status_q <= STATUS_BAD_DESCRIPTOR; result_cycles_q <= cycles_q + 1'b1;
              state_q <= RESPONSE;
            end else begin
              tile_start_o <= 1'b1;
              weight_switch_o <= !previous_expert_valid_q || previous_expert_q != dma_rsp_rdata_i[95:64];
              previous_expert_q <= dma_rsp_rdata_i[95:64]; previous_expert_valid_q <= 1'b1;
              if (PIPELINED_ADDRESS_BASES) state_q <= PREP_EXPERT_BASE;
              else state_q <= ROUTE_REQ;
            end
          end
        end
        PREP_EXPERT_BASE: begin
          expert_base_q <= weight_addr_q +
            $unsigned(expert_q[7:0]) * expert_span_q;
          state_q <= ROUTE_REQ;
        end
        ROUTE_REQ: if (dma_req_ready_i) state_q <= ROUTE_RSP;
        ROUTE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin
            route_weight_q <= dma_rsp_rdata_i[((route_addr_q[3:2] + absolute_row_q[1:0]) & 3)*32 +: 32];
            state_q <= PIPELINED_ROW_BASE ? PREP_ROW_BASE : START_ROW;
          end
        end
        PREP_ROW_BASE: begin
          activation_row_base_q <= q_addr_q +
            $unsigned(absolute_row_q) * $unsigned(hidden_q);
          if (PIPELINED_OUTPUT_ROW_BASE) begin
            output_row_base_q <= output_addr_q +
              ($unsigned(absolute_row_q) * $unsigned(hidden_q) << 1);
          end
          state_q <= START_ROW;
        end
        START_ROW: if (core_cmd_ready) state_q <= WAIT_CORE;
        WAIT_CORE: begin
          if (core_data_req_valid) begin
            req_down_q <= core_data_req_down; req_hidden_q <= core_data_req_hidden;
            req_intermediate_q <= core_data_req_intermediate;
            if (PIPELINED_WEIGHT_ROW_BASE) begin
              weight_row_offset_q <= core_data_req_down ?
                ($unsigned(core_data_req_hidden) * $unsigned(intermediate_q)) :
                ($unsigned(core_data_req_intermediate) * $unsigned(hidden_q));
            end
            if (core_data_req_down) begin
              if (PIPELINED_WEIGHT_ROW_BASE) begin
                state_q <= PREP_DOWN_ADDRESS;
              end else begin
                data_address_q <= expert_base_w[31:0] + down_request_offset_w[31:0];
                data_lane_q <= (expert_base_w[3:0] + down_request_offset_w[3:0]) & 4'hf;
                state_q <= DOWN_REQ;
              end
            end else begin
              data_address_q <= PIPELINED_ROW_BASE ?
                activation_request_offset_w[31:0] :
                q_addr_q + activation_request_offset_w[31:0];
              data_lane_q <= PIPELINED_ROW_BASE ?
                activation_request_offset_w[3:0] :
                (q_addr_q[3:0] + activation_request_offset_w[3:0]) & 4'hf;
              state_q <= ACT_REQ;
            end
          end else if (core_output_valid) begin
            output_index_q <= core_output_index; output_bf16_q <= core_output_bf16;
            state_q <= WRITE_REQ;
          end else if (core_rsp_valid) begin
            if (core_rsp_status != STATUS_OK) begin
              status_q <= core_rsp_status; result_cycles_q <= cycles_q + core_rsp_cycles + 1'b1;
              state_q <= RESPONSE;
            end else if (row_in_tile_q + 1'b1 < row_count_q) begin
              row_in_tile_q <= row_in_tile_q + 1'b1; absolute_row_q <= absolute_row_q + 1'b1;
              state_q <= ROUTE_REQ;
            end else if (tile_index_q + 1'b1 < tile_count_q) begin
              tile_index_q <= tile_index_q + 1'b1; state_q <= TILE_REQ;
            end else begin
              result_cycles_q <= cycles_q + core_rsp_cycles + 1'b1; state_q <= RESPONSE;
            end
          end
        end
        PREP_DOWN_ADDRESS: begin
          data_address_q <= expert_base_w[31:0] + (matrix_size_w[31:0] << 1) +
            weight_row_offset_q[31:0] + req_intermediate_q;
          data_lane_q <= (expert_base_w[3:0] + (matrix_size_w[3:0] << 1) +
            weight_row_offset_q[3:0] + req_intermediate_q[3:0]) & 4'hf;
          state_q <= DOWN_REQ;
        end
        ACT_REQ: if (dma_req_ready_i) state_q <= ACT_RSP;
        ACT_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin
            activation_q <= dma_rsp_rdata_i[data_lane_q*8 +: 8];
            data_address_q <= expert_base_w[31:0] +
              (PIPELINED_WEIGHT_ROW_BASE ? weight_row_offset_q[31:0] + req_hidden_q :
               gate_offset_w[31:0]);
            data_lane_q <= (expert_base_w[3:0] +
              (PIPELINED_WEIGHT_ROW_BASE ? weight_row_offset_q[3:0] + req_hidden_q[3:0] :
               gate_offset_w[3:0])) & 4'hf;
            if (PIPELINED_WEIGHT_ROW_BASE) begin
              up_row_base_q <= expert_base_w + matrix_size_w + weight_row_offset_q;
            end
            state_q <= GATE_REQ;
          end
        end
        GATE_REQ: if (dma_req_ready_i) state_q <= GATE_RSP;
        GATE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin
            gate_weight_q <= dma_rsp_rdata_i[data_lane_q*8 +: 8];
            data_address_q <= PIPELINED_WEIGHT_ROW_BASE ?
              up_row_base_q[31:0] + req_hidden_q :
              expert_base_w[31:0] + up_offset_w[31:0];
            data_lane_q <= PIPELINED_WEIGHT_ROW_BASE ?
              (up_row_base_q[3:0] + req_hidden_q[3:0]) & 4'hf :
              (expert_base_w[3:0] + up_offset_w[3:0]) & 4'hf;
            state_q <= UP_REQ;
          end
        end
        UP_REQ: if (dma_req_ready_i) state_q <= UP_RSP;
        UP_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin up_weight_q <= dma_rsp_rdata_i[data_lane_q*8 +: 8]; state_q <= FEED_CORE; end
        end
        DOWN_REQ: if (dma_req_ready_i) state_q <= DOWN_RSP;
        DOWN_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus();
          else begin down_weight_q <= dma_rsp_rdata_i[data_lane_q*8 +: 8]; state_q <= FEED_CORE; end
        end
        FEED_CORE: if (core_data_rsp_ready) state_q <= WAIT_CORE;
        WRITE_REQ: if (dma_req_ready_i) state_q <= WRITE_RSP;
        WRITE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) fail_bus(); else state_q <= WAIT_CORE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
