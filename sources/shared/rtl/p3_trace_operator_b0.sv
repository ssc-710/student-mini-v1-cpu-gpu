// SPDX-License-Identifier: Apache-2.0
// Traffic-only P3 profile for the two frozen DeepSeek-scale GEMM traces.
//
// Descriptor v1 cannot encode 256 in its eight-bit expert field.  Only when
// TRAFFIC_ONLY is set, encoded zero means 256.  This module reads every real
// 16-byte tile descriptor, proves continuous row coverage and legal experts,
// and reports a checked traffic/cycle projection.  It never claims to execute
// the huge element-wise GEMMs.
module p3_trace_operator_b0 #(
  parameter bit TRACE_DOWN = 1'b0
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
  output logic [63:0] projected_read_requests_o,
  output logic [63:0] projected_write_requests_o,
  output logic [63:0] projected_read_bytes_o,
  output logic [63:0] projected_write_bytes_o,
  output logic [63:0] projected_mac_count_o,
  output logic [31:0] weight_switches_o,
  output logic [31:0] first_weight_address_o,
  output logic [31:0] last_weight_address_o
);
  localparam logic [7:0] OK = 0, BAD_DESCRIPTOR = 1,
    BAD_LENGTH = 2, BUS_ERROR = 5;
  localparam logic [63:0] MATRIX_BYTES = 64'd14680064;
  localparam logic [63:0] EXPERT_SPAN = 64'd44040192;
  localparam logic [63:0] GATEUP_ACTIVATION_BEATS = 64'd3670016;
  localparam logic [63:0] GATEUP_WEIGHT_BEATS = 64'd7516192768;
  localparam logic [63:0] GATEUP_OUTPUT_BEATS = 64'd524288;
  localparam logic [63:0] GATEUP_MACS = 64'd120259084288;
  localparam logic [63:0] GATEUP_WRITE_BYTES = 64'd8388608;
  localparam logic [63:0] DOWN_ACTIVATION_BEATS = 64'd524288;
  localparam logic [63:0] DOWN_WEIGHT_BEATS = 64'd3758096384;
  localparam logic [63:0] DOWN_OUTPUT_BEATS = 64'd3670016;
  localparam logic [63:0] DOWN_MACS = 64'd60129542144;
  localparam logic [63:0] DOWN_WRITE_BYTES = 64'd58720256;
  typedef enum logic [2:0] {
    IDLE, TILE_REQ, TILE_RSP, CALC_BASE, CALC_TRAFFIC, CALC_FINAL, RESPONSE
  } state_t;
  state_t state_q;

  logic [31:0] tile_count_q, rows_q, hidden_q, intermediate_q;
  logic [31:0] tile_addr_q, weight_addr_q;
  logic [31:0] tile_index_q, covered_rows_q;
  logic [31:0] previous_expert_q;
  logic [7:0] first_expert_q, last_expert_q;
  logic previous_valid_q;
  logic [31:0] switches_q;
  logic [7:0] status_q;

  logic [31:0] row_begin_w, row_count_w, expert_w, flags_w;
  logic [63:0] first_weight_address_w, last_weight_address_w;
  logic [63:0] matrix_bytes_q, expert_span_q;
  logic [63:0] activation_beats_q, weight_beats_q, output_beats_q, macs_q;
  logic [63:0] projected_reads_q, projected_writes_q;
  logic [63:0] projected_read_bytes_q, projected_write_bytes_q;
  logic [63:0] projected_cycles_q;
  logic [31:0] first_weight_address_q, last_weight_address_q;
  assign row_begin_w = dma_rsp_rdata_i[31:0];
  assign row_count_w = dma_rsp_rdata_i[63:32];
  assign expert_w = dma_rsp_rdata_i[95:64];
  assign flags_w = dma_rsp_rdata_i[127:96];

  // The traffic-only profile accepts exactly rows=4096, hidden=7168 and
  // intermediate=2048.  Materialize those frozen projections as constants:
  // retaining runtime multiplier cones here would measure an implementation
  // that the trace contract neither needs nor executes.
  assign first_weight_address_w = {32'd0, weight_addr_q} +
    first_expert_q * EXPERT_SPAN + (TRACE_DOWN ? (MATRIX_BYTES << 1) : 0);
  assign last_weight_address_w = {32'd0, weight_addr_q} +
    last_expert_q * EXPERT_SPAN +
    (TRACE_DOWN ? EXPERT_SPAN : (MATRIX_BYTES << 1)) - 1'b1;

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = projected_cycles_q;
  assign projected_read_requests_o = projected_reads_q;
  assign projected_write_requests_o = projected_writes_q;
  assign projected_read_bytes_o = projected_read_bytes_q;
  assign projected_write_bytes_o = projected_write_bytes_q;
  assign projected_mac_count_o = macs_q;
  assign weight_switches_o = switches_q;
  assign first_weight_address_o = first_weight_address_q;
  assign last_weight_address_o = last_weight_address_q;

  always_comb begin
    dma_req_valid_o = state_q == TILE_REQ;
    dma_req_write_o = 1'b0;
    dma_req_addr_o = tile_addr_q + (tile_index_q << 4);
    dma_req_wdata_o = '0;
    dma_req_wstrb_o = '0;
    dma_rsp_ready_o = state_q == TILE_RSP;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; tile_count_q <= 0; rows_q <= 0; hidden_q <= 0;
      intermediate_q <= 0; tile_addr_q <= 0; weight_addr_q <= 0;
      tile_index_q <= 0; covered_rows_q <= 0; previous_expert_q <= 0;
      first_expert_q <= 0; last_expert_q <= 0; previous_valid_q <= 0;
      switches_q <= 0; status_q <= OK;
      matrix_bytes_q <= 0; expert_span_q <= 0; activation_beats_q <= 0;
      weight_beats_q <= 0; output_beats_q <= 0; macs_q <= 0;
      projected_reads_q <= 0; projected_writes_q <= 0;
      projected_read_bytes_q <= 0; projected_write_bytes_q <= 0;
      projected_cycles_q <= 0; first_weight_address_q <= 0;
      last_weight_address_q <= 0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          tile_count_q <= descriptor_i[63:32];
          rows_q <= descriptor_i[95:64];
          hidden_q <= descriptor_i[127:96];
          tile_addr_q <= descriptor_i[255:224];
          weight_addr_q <= descriptor_i[351:320];
          intermediate_q <= {16'd0, descriptor_i[463:448]};
          tile_index_q <= 0; covered_rows_q <= 0; previous_valid_q <= 0;
          switches_q <= 0; status_q <= OK;
          if (descriptor_i[63:32] == 0 || descriptor_i[95:64] != 4096 ||
              descriptor_i[127:96] != 7168 || descriptor_i[463:448] != 2048)
            begin status_q <= BAD_LENGTH; state_q <= RESPONSE; end
          else if (!descriptor_i[21] || descriptor_i[471:464] != 0 ||
                   descriptor_i[255:224][3:0] != 0 ||
                   descriptor_i[351:320][3:0] != 0)
            begin status_q <= BAD_DESCRIPTOR; state_q <= RESPONSE; end
          else state_q <= TILE_REQ;
        end
        TILE_REQ: if (dma_req_ready_i) state_q <= TILE_RSP;
        TILE_RSP: if (dma_rsp_valid_i) begin
          if (dma_rsp_error_i) begin status_q <= BUS_ERROR; state_q <= RESPONSE; end
          else if (row_count_w == 0 || row_begin_w != covered_rows_q ||
                   row_begin_w + row_count_w > rows_q || expert_w >= 256 || flags_w != 0)
            begin status_q <= BAD_DESCRIPTOR; state_q <= RESPONSE; end
          else begin
            if (!previous_valid_q) begin
              first_expert_q <= expert_w[7:0]; switches_q <= 1;
            end else if (expert_w != previous_expert_q) switches_q <= switches_q + 1'b1;
            previous_valid_q <= 1'b1; previous_expert_q <= expert_w;
            last_expert_q <= expert_w[7:0]; covered_rows_q <= covered_rows_q + row_count_w;
            if (tile_index_q + 1'b1 == tile_count_q) state_q <= CALC_BASE;
            else begin tile_index_q <= tile_index_q + 1'b1; state_q <= TILE_REQ; end
          end
        end
        CALC_BASE: begin
          if (covered_rows_q != rows_q) begin
            status_q <= BAD_LENGTH;
            state_q <= RESPONSE;
          end else begin
            matrix_bytes_q <= MATRIX_BYTES;
            expert_span_q <= EXPERT_SPAN;
            activation_beats_q <= TRACE_DOWN ? DOWN_ACTIVATION_BEATS : GATEUP_ACTIVATION_BEATS;
            weight_beats_q <= TRACE_DOWN ? DOWN_WEIGHT_BEATS : GATEUP_WEIGHT_BEATS;
            output_beats_q <= TRACE_DOWN ? DOWN_OUTPUT_BEATS : GATEUP_OUTPUT_BEATS;
            macs_q <= TRACE_DOWN ? DOWN_MACS : GATEUP_MACS;
            projected_write_bytes_q <= TRACE_DOWN ? DOWN_WRITE_BYTES : GATEUP_WRITE_BYTES;
            state_q <= CALC_TRAFFIC;
          end
        end
        CALC_TRAFFIC: begin
          projected_reads_q <= 64'd6 + {32'd0, tile_count_q} +
            activation_beats_q + weight_beats_q;
          projected_writes_q <= output_beats_q;
          first_weight_address_q <= first_weight_address_w[31:0];
          last_weight_address_q <= last_weight_address_w[31:0];
          state_q <= CALC_FINAL;
        end
        CALC_FINAL: begin
          projected_read_bytes_q <= projected_reads_q << 4;
          projected_cycles_q <= (projected_reads_q << 1) +
            (projected_writes_q << 1) + macs_q;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
