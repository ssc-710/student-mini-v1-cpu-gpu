// SPDX-License-Identifier: Apache-2.0
// Small synchronous read-reuse buffer for the single-outstanding 128-bit DMA seam.
// Requests and responses remain strictly ordered.  Writes bypass the buffer and
// invalidate a matching cached line, so the module never changes architectural
// memory semantics.  One registered hit response also decouples compute from the
// dispatcher while recently used read lines remain resident.
module dma_128_read_reuse_buffer #(
  parameter int unsigned SET_BITS = 1,
  parameter int unsigned WAYS = 4
) (
  input  logic         clk_i,
  input  logic         rst_ni,
  input  logic         flush_i,

  input  logic         client_req_valid_i,
  output logic         client_req_ready_o,
  input  logic         client_req_write_i,
  input  logic [31:0]  client_req_addr_i,
  input  logic [127:0] client_req_wdata_i,
  input  logic [15:0]  client_req_wstrb_i,
  output logic         client_rsp_valid_o,
  input  logic         client_rsp_ready_i,
  output logic [127:0] client_rsp_rdata_o,
  output logic         client_rsp_error_o,

  output logic         dma_req_valid_o,
  input  logic         dma_req_ready_i,
  output logic         dma_req_write_o,
  output logic [31:0]  dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o,
  output logic [15:0]  dma_req_wstrb_o,
  input  logic         dma_rsp_valid_i,
  output logic         dma_rsp_ready_o,
  input  logic [127:0] dma_rsp_rdata_i,
  input  logic         dma_rsp_error_i
);
  localparam int unsigned SETS = 1 << SET_BITS;
  localparam int unsigned TAG_BITS = 28 - SET_BITS;
  localparam int unsigned WAY_BITS = (WAYS <= 1) ? 1 : $clog2(WAYS);
  localparam logic [WAY_BITS-1:0] LAST_WAY = WAY_BITS'(WAYS - 1);

  typedef enum logic [1:0] {READY, EXTERNAL_RESPONSE, HIT_RESPONSE} state_t;
  state_t state_q;
  logic valid_q [0:SETS-1][0:WAYS-1];
  logic [TAG_BITS-1:0] tag_q [0:SETS-1][0:WAYS-1];
  logic [127:0] data_q [0:SETS-1][0:WAYS-1];
  logic [WAY_BITS-1:0] replace_q [0:SETS-1];
  logic pending_read_q;
  logic [SET_BITS-1:0] pending_set_q;
  logic [TAG_BITS-1:0] pending_tag_q;
  logic [127:0] hit_data_q;

  logic [SET_BITS-1:0] request_set_w;
  logic [TAG_BITS-1:0] request_tag_w;
  logic request_hit_w;
  logic [127:0] request_hit_data_w;
  integer lookup_way;
  always_comb begin
    request_set_w = client_req_addr_i[4 +: SET_BITS];
    request_tag_w = client_req_addr_i[31 -: TAG_BITS];
    request_hit_w = 1'b0;
    request_hit_data_w = '0;
    for (lookup_way = 0; lookup_way < WAYS; lookup_way = lookup_way + 1) begin
      if (!request_hit_w && valid_q[request_set_w][lookup_way] &&
          tag_q[request_set_w][lookup_way] == request_tag_w) begin
        request_hit_w = 1'b1;
        request_hit_data_w = data_q[request_set_w][lookup_way];
      end
    end
  end

  always_comb begin
    client_req_ready_o = 1'b0;
    client_rsp_valid_o = 1'b0;
    client_rsp_rdata_o = '0;
    client_rsp_error_o = 1'b0;
    dma_req_valid_o = 1'b0;
    dma_req_write_o = client_req_write_i;
    dma_req_addr_o = client_req_addr_i;
    dma_req_wdata_o = client_req_wdata_i;
    dma_req_wstrb_o = client_req_wstrb_i;
    dma_rsp_ready_o = 1'b0;
    unique case (state_q)
      READY: begin
        if (client_req_valid_i && !client_req_write_i && request_hit_w) begin
          client_req_ready_o = 1'b1;
        end else begin
          client_req_ready_o = dma_req_ready_i;
          dma_req_valid_o = client_req_valid_i;
        end
      end
      EXTERNAL_RESPONSE: begin
        client_rsp_valid_o = dma_rsp_valid_i;
        client_rsp_rdata_o = dma_rsp_rdata_i;
        client_rsp_error_o = dma_rsp_error_i;
        dma_rsp_ready_o = client_rsp_ready_i;
      end
      HIT_RESPONSE: begin
        client_rsp_valid_o = 1'b1;
        client_rsp_rdata_o = hit_data_q;
      end
      default: begin end
    endcase
  end

  integer reset_set, reset_way;
  logic [WAY_BITS-1:0] fill_way;
  always_comb fill_way = replace_q[pending_set_q];
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= READY;
      pending_read_q <= 1'b0;
      pending_set_q <= '0;
      pending_tag_q <= '0;
      hit_data_q <= '0;
      for (reset_set = 0; reset_set < SETS; reset_set = reset_set + 1) begin
        replace_q[reset_set] <= '0;
        for (reset_way = 0; reset_way < WAYS; reset_way = reset_way + 1) begin
          valid_q[reset_set][reset_way] <= 1'b0;
          tag_q[reset_set][reset_way] <= '0;
          data_q[reset_set][reset_way] <= '0;
        end
      end
    end else if (flush_i) begin
      state_q <= READY;
      pending_read_q <= 1'b0;
      for (reset_set = 0; reset_set < SETS; reset_set = reset_set + 1) begin
        replace_q[reset_set] <= '0;
        for (reset_way = 0; reset_way < WAYS; reset_way = reset_way + 1)
          valid_q[reset_set][reset_way] <= 1'b0;
      end
    end else begin
      unique case (state_q)
        READY: if (client_req_valid_i && client_req_ready_o) begin
          if (!client_req_write_i && request_hit_w) begin
            hit_data_q <= request_hit_data_w;
            state_q <= HIT_RESPONSE;
          end else begin
            pending_read_q <= !client_req_write_i;
            pending_set_q <= request_set_w;
            pending_tag_q <= request_tag_w;
            if (client_req_write_i) begin
              for (reset_way = 0; reset_way < WAYS; reset_way = reset_way + 1)
                if (valid_q[request_set_w][reset_way] &&
                    tag_q[request_set_w][reset_way] == request_tag_w)
                  valid_q[request_set_w][reset_way] <= 1'b0;
            end
            state_q <= EXTERNAL_RESPONSE;
          end
        end
        EXTERNAL_RESPONSE: if (dma_rsp_valid_i && client_rsp_ready_i) begin
          if (pending_read_q && !dma_rsp_error_i) begin
            valid_q[pending_set_q][fill_way] <= 1'b1;
            tag_q[pending_set_q][fill_way] <= pending_tag_q;
            data_q[pending_set_q][fill_way] <= dma_rsp_rdata_i;
            replace_q[pending_set_q] <= (fill_way == LAST_WAY) ? '0 : fill_way + 1'b1;
          end
          state_q <= READY;
        end
        HIT_RESPONSE: if (client_rsp_ready_i) state_q <= READY;
        default: state_q <= READY;
      endcase
    end
  end
endmodule
