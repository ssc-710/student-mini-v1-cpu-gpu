// SPDX-License-Identifier: Apache-2.0
// Feasibility B0: one serial dot product and one scalar Split-KV core,
// replayed over 8 value lanes. No host-generated scores, Radix-16 or overlap.
// Descriptor: q_tokens=query rows (1/2), kv_tokens=length (1..32).
// Ordinary frozen operator cases use 1..8; Nano requires context 32. The
// serial token stream adds no context-sized register array.
// q_addr=16-byte Q records, kv_addr=32-byte {K12,pad4,V8,pad8} records,
// page_addr=uint32 page IDs; aux0_addr word carries page-table entry count.
module p2_student_mini_vector (
  input logic clk_i, rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [511:0] descriptor_i,
  output logic dma_req_valid_o, input logic dma_req_ready_i,
  output logic dma_req_write_o, output logic [31:0] dma_req_addr_o,
  output logic [127:0] dma_req_wdata_o, output logic [15:0] dma_req_wstrb_o,
  input logic dma_rsp_valid_i, output logic dma_rsp_ready_o,
  input logic [127:0] dma_rsp_rdata_i, input logic dma_rsp_error_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  typedef enum logic [4:0] {
    IDLE, SCALE_REQ, SCALE_RSP, CHECK_SCALE, QUERY_REQ, QUERY_RSP,
    START_CORE, CORE_WAIT, PAGE_ADDR, PAGE_REQ, PAGE_RSP, KEY_ADDR,
    KEY_REQ, KEY_RSP, VALUE_REQ, VALUE_RSP, DOT_PRODUCT, DOT_ADD,
    SCALE_START, SCALE_WAIT, FEED, WRITE_REQ, WRITE_RSP, RESPONSE
  } state_t;
  state_t state_q;
  logic [31:0] q_base_q, kv_base_q, page_base_q, out_base_q, scale_base_q;
  logic [31:0] length_q, rows_q, page_count_q, page_size_q, splits_q;
  logic [31:0] score_scale_q, value_scale_q, query_q, token_q;
  logic [31:0] page_address_q, physical_page_q, key_address_q;
  logic [1:0] page_word_q;
  logic [2:0] lane_q;
  logic [3:0] dot_lane_q;
  logic [95:0] query_data_q, key_data_q;
  logic signed [15:0] product_q, score_q;
  logic signed [31:0] sum_q;
  logic signed [7:0] value_q;
  logic [127:0] output_q;
  logic [7:0] status_q;
  logic [63:0] cycles_q;
  logic score_valid, value_valid;
  fp32_scale_check u_score_check(.scale_i(score_scale_q), .valid_o(score_valid));
  fp32_scale_check u_value_check(.scale_i(value_scale_q), .valid_o(value_valid));

  logic scale_ready, scale_rsp, scale_result_valid;
  logic signed [15:0] scaled_score;
  int32_scale_to_q5_11_finalize_pipeline u_score (
    .clk_i, .rst_ni, .cmd_valid_i(state_q == SCALE_START), .cmd_ready_o(scale_ready),
    .value_i(sum_q), .scale_i(score_scale_q), .rsp_valid_o(scale_rsp),
    .rsp_ready_i(state_q == SCALE_WAIT), .q5_11_o(scaled_score), .scale_valid_o(scale_result_valid)
  );
  logic core_ready, token_valid, token_ready, core_rsp;
  logic [31:0] core_token;
  logic [7:0] core_status;
  logic [15:0] core_bf16;
  wire core_reset_n = rst_ni && state_q != IDLE;
  p2_split_kv_b4_serial_output #(.PIPELINED_SOFTMAX(1), .RADIX16_MERGE(0)) u_scalar (
    .clk_i, .rst_ni(core_reset_n), .cmd_valid_i(state_q == START_CORE), .cmd_ready_o(core_ready),
    // Pagination is resolved here, before the logical token stream enters
    // the scalar core. Its stream records have logical page size 1; the
    // external descriptor still strictly validates and executes page 1/4.
    .cache_len_i(length_q), .splits_i(splits_q[3:0]), .page_size_i(8'd1), .value_scale_i(value_scale_q),
    .token_req_valid_o(token_valid), .token_req_ready_i(state_q == CORE_WAIT), .token_index_o(core_token), .split_id_o(),
    .token_rsp_valid_i(state_q == FEED), .token_rsp_ready_o(token_ready), .token_rsp_score_q11_i(score_q),
    .token_rsp_value_i(value_q), .token_rsp_error_i(1'b0),
    .rsp_valid_o(core_rsp), .rsp_ready_i(state_q == CORE_WAIT), .rsp_status_o(core_status), .rsp_cycles_o(),
    .output_q16_o(), .output_bf16_o(core_bf16), .merged_max_q11_o(), .merged_sum_q15_o(), .merged_weighted_q15_o()
  );
  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = cycles_q;
  always_comb begin
    dma_req_valid_o=0; dma_req_write_o=0; dma_req_addr_o=0;
    dma_req_wdata_o=output_q; dma_req_wstrb_o=16'hffff; dma_rsp_ready_o=0;
    case (state_q)
      SCALE_REQ: begin dma_req_valid_o=1; dma_req_addr_o=scale_base_q; end
      QUERY_REQ: begin dma_req_valid_o=1; dma_req_addr_o=q_base_q+(query_q<<4); end
      PAGE_REQ: begin dma_req_valid_o=1; dma_req_addr_o=page_address_q; end
      KEY_REQ: begin dma_req_valid_o=1; dma_req_addr_o=key_address_q; end
      VALUE_REQ: begin dma_req_valid_o=1; dma_req_addr_o=key_address_q+32'd16; end
      WRITE_REQ: begin dma_req_valid_o=1; dma_req_write_o=1; dma_req_addr_o=out_base_q+(query_q<<4); end
      SCALE_RSP, QUERY_RSP, PAGE_RSP, KEY_RSP, VALUE_RSP, WRITE_RSP: dma_rsp_ready_o=1;
      default: begin end
    endcase
  end
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q<=IDLE; status_q<=0; cycles_q<=0;
      q_base_q<=0;kv_base_q<=0;page_base_q<=0;out_base_q<=0;scale_base_q<=0;
      length_q<=0;rows_q<=0;page_count_q<=0;page_size_q<=0;splits_q<=0;
      score_scale_q<=0;value_scale_q<=0;query_q<=0;token_q<=0;
      page_address_q<=0;physical_page_q<=0;key_address_q<=0;page_word_q<=0;
      lane_q<=0;dot_lane_q<=0;query_data_q<=0;key_data_q<=0;product_q<=0;score_q<=0;sum_q<=0;value_q<=0;output_q<=0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) begin
        cycles_q[15:0]<=cycles_q[15:0]+16'd1;
        if (&cycles_q[15:0]) cycles_q[31:16]<=cycles_q[31:16]+16'd1;
        if (&cycles_q[31:0]) cycles_q[47:32]<=cycles_q[47:32]+16'd1;
        if (&cycles_q[47:0]) cycles_q[63:48]<=cycles_q[63:48]+16'd1;
      end
      if (dma_rsp_valid_i && dma_rsp_ready_o && dma_rsp_error_i) begin
        status_q<=8'd5;state_q<=RESPONSE;
      end else case(state_q)
        IDLE: if (cmd_valid_i) begin
          cycles_q<=0;status_q<=0;query_q<=0;lane_q<=0;output_q<=0;
          rows_q<=descriptor_i[64+:32]; length_q<=descriptor_i[96+:32];
          q_base_q<=descriptor_i[128+:32];kv_base_q<=descriptor_i[160+:32];page_base_q<=descriptor_i[192+:32];
          page_count_q<=descriptor_i[256+:32];scale_base_q<=descriptor_i[352+:32];out_base_q<=descriptor_i[384+:32];
          page_size_q<={16'd0,descriptor_i[448+:16]};splits_q<={24'd0,descriptor_i[464+:8]};
          if (descriptor_i[96+:32]==0 || descriptor_i[96+:32]>32 || descriptor_i[64+:32]==0 || descriptor_i[64+:32]>2) begin status_q<=8'd2;state_q<=RESPONSE;end
          else if (descriptor_i[32+:32]!=1 || (descriptor_i[448+:16]!=1 && descriptor_i[448+:16]!=4) ||
                   (descriptor_i[464+:8]!=1 && descriptor_i[464+:8]!=2 && descriptor_i[464+:8]!=4) || descriptor_i[464+:8]>descriptor_i[96+:32]) begin status_q<=8'd1;state_q<=RESPONSE;end
          else state_q<=SCALE_REQ;
        end
        SCALE_REQ: if(dma_req_ready_i)state_q<=SCALE_RSP;
        SCALE_RSP: if(dma_rsp_valid_i)begin score_scale_q<=dma_rsp_rdata_i[31:0];value_scale_q<=dma_rsp_rdata_i[63:32];state_q<=CHECK_SCALE;end
        CHECK_SCALE: if(!score_valid || !value_valid)begin status_q<=8'd4;state_q<=RESPONSE;end else state_q<=QUERY_REQ;
        QUERY_REQ: if(dma_req_ready_i)state_q<=QUERY_RSP;
        QUERY_RSP: if(dma_rsp_valid_i)begin query_data_q<=dma_rsp_rdata_i[95:0];state_q<=START_CORE;end
        START_CORE: if(core_ready)state_q<=CORE_WAIT;
        CORE_WAIT: begin
          if(core_rsp)begin
            if(core_status!=0)begin status_q<=core_status;state_q<=RESPONSE;end
            else begin output_q[lane_q*16+:16]<=core_bf16;
              if(lane_q==7)state_q<=WRITE_REQ;else begin lane_q<=lane_q+1'b1;state_q<=START_CORE;end
            end
          end else if(token_valid)begin token_q<=core_token;state_q<=PAGE_ADDR;end
        end
        PAGE_ADDR: begin
          if((page_size_q==4 ? token_q>>2 : token_q)>=page_count_q)begin status_q<=8'd3;state_q<=RESPONSE;end
          else begin
            page_word_q<=page_size_q==4 ? token_q[3:2] : token_q[1:0];
            page_address_q<=page_base_q+((page_size_q==4 ? token_q>>4 : token_q>>2)<<4);state_q<=PAGE_REQ;
          end
        end
        PAGE_REQ: if(dma_req_ready_i)state_q<=PAGE_RSP;
        PAGE_RSP: if(dma_rsp_valid_i)begin physical_page_q<=dma_rsp_rdata_i[page_word_q*32+:32];state_q<=KEY_ADDR;end
        KEY_ADDR: begin
          if(physical_page_q>=32)begin status_q<=8'd3;state_q<=RESPONSE;end
          else begin key_address_q<=kv_base_q+(((page_size_q==4 ? physical_page_q<<2 : physical_page_q)+(page_size_q==4 ? {30'd0,token_q[1:0]} : 32'd0))<<5);state_q<=KEY_REQ;end
        end
        KEY_REQ: if(dma_req_ready_i)state_q<=KEY_RSP;
        KEY_RSP: if(dma_rsp_valid_i)begin key_data_q<=dma_rsp_rdata_i[95:0];state_q<=VALUE_REQ;end
        VALUE_REQ: if(dma_req_ready_i)state_q<=VALUE_RSP;
        VALUE_RSP: if(dma_rsp_valid_i)begin value_q<=dma_rsp_rdata_i[lane_q*8+:8];dot_lane_q<=0;sum_q<=0;state_q<=DOT_PRODUCT;end
        DOT_PRODUCT: begin product_q<=$signed(query_data_q[dot_lane_q*8+:8])*$signed(key_data_q[dot_lane_q*8+:8]);state_q<=DOT_ADD;end
        DOT_ADD: begin sum_q<=sum_q+{{16{product_q[15]}},product_q};
          if(dot_lane_q==11)state_q<=SCALE_START;else begin dot_lane_q<=dot_lane_q+1'b1;state_q<=DOT_PRODUCT;end
        end
        SCALE_START: if(scale_ready)state_q<=SCALE_WAIT;
        SCALE_WAIT: if(scale_rsp)begin
          if(!scale_result_valid)begin status_q<=8'd4;state_q<=RESPONSE;end
          else begin score_q<=scaled_score;state_q<=FEED;end
        end
        FEED: if(token_ready)state_q<=CORE_WAIT;
        WRITE_REQ: if(dma_req_ready_i)state_q<=WRITE_RSP;
        WRITE_RSP: if(dma_rsp_valid_i)begin
          if(query_q+1==rows_q)state_q<=RESPONSE;
          else begin query_q<=query_q+1'b1;lane_q<=0;output_q<=0;state_q<=QUERY_REQ;end
        end
        RESPONSE: if(rsp_ready_i)state_q<=IDLE;
        default: state_q<=IDLE;
      endcase
    end
  end
endmodule
