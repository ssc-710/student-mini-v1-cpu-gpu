// SPDX-License-Identifier: Apache-2.0
// Baseline command front-end: fetches and validates one 64-byte descriptor.
module litex_descriptor_engine (
  input  logic         clk_i,
  input  logic         rst_ni,
  input  logic         cmd_valid_i,
  output logic         cmd_ready_o,
  input  logic [2:0]   cmd_opcode_i,
  input  logic [31:0]  cmd_desc_addr_i,
  output logic         mem_req_valid_o,
  input  logic         mem_req_ready_i,
  output logic [31:0]  mem_req_addr_o,
  input  logic         mem_rsp_valid_i,
  output logic         mem_rsp_ready_o,
  input  logic [127:0] mem_rsp_data_i,
  input  logic         mem_rsp_error_i,
  output logic [511:0] descriptor_o,
  output logic [7:0]   operator_arg_o,
  output logic [31:0]  dma_request_count_o,
  output logic [31:0]  dma_response_count_o,
  output logic [1:0]   dma_outstanding_peak_o,
  output logic         rsp_valid_o,
  input  logic         rsp_ready_i,
  output logic [7:0]   rsp_status_o,
  output logic [63:0]  rsp_cycles_o
);
  localparam logic [7:0] OK = 8'd0;
  localparam logic [7:0] BAD_DESCRIPTOR = 8'd1;
  localparam logic [7:0] BUS_ERROR = 8'd5;
  typedef enum logic [2:0] {IDLE, READ_REQ, READ_RSP, VALIDATE, RESPONSE} state_t;
  state_t state_q;
  logic [1:0] beat_q;
  logic [2:0] opcode_q;
  logic [31:0] address_q;
  logic [31:0] header_q;
  logic [31:0] reserved_q;
  logic [511:0] descriptor_q;
  logic [63:0] cycles_q;
  logic [7:0] status_q;
  logic [31:0] request_count_q, response_count_q;
  logic outstanding_q;

  assign cmd_ready_o = state_q == IDLE;
  assign mem_req_valid_o = state_q == READ_REQ;
  assign mem_req_addr_o = address_q + {26'd0, beat_q, 4'b0000};
  assign mem_rsp_ready_o = state_q == READ_RSP;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = cycles_q;
  assign descriptor_o = descriptor_q;
  assign operator_arg_o = header_q[31:24];
  assign dma_request_count_o = request_count_q;
  assign dma_response_count_o = response_count_q;
  assign dma_outstanding_peak_o = {1'b0, (request_count_q != 0)};

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      beat_q <= '0;
      opcode_q <= '0;
      address_q <= '0;
      header_q <= '0;
      reserved_q <= '0;
      descriptor_q <= '0;
      cycles_q <= '0;
      status_q <= OK;
      request_count_q <= '0;
      response_count_q <= '0;
      outstanding_q <= 1'b0;
    end else begin
      if (state_q != IDLE && state_q != RESPONSE) cycles_q <= cycles_q + 1'b1;
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          beat_q <= '0;
          opcode_q <= cmd_opcode_i;
          address_q <= cmd_desc_addr_i;
          header_q <= '0;
          reserved_q <= '0;
          descriptor_q <= '0;
          cycles_q <= '0;
          status_q <= OK;
          request_count_q <= '0;
          response_count_q <= '0;
          outstanding_q <= 1'b0;
          if (cmd_desc_addr_i[5:0] != 0 || cmd_opcode_i == 0 || cmd_opcode_i > 4) begin
            status_q <= BAD_DESCRIPTOR;
            state_q <= RESPONSE;
          end else state_q <= READ_REQ;
        end
        READ_REQ: if (mem_req_ready_i) begin
          request_count_q <= request_count_q + 1'b1;
          outstanding_q <= 1'b1;
          state_q <= READ_RSP;
        end
        READ_RSP: if (mem_rsp_valid_i) begin
          response_count_q <= response_count_q + 1'b1;
          outstanding_q <= 1'b0;
          if (mem_rsp_error_i) begin
            status_q <= BUS_ERROR;
            state_q <= RESPONSE;
          end else begin
            descriptor_q[beat_q*128 +: 128] <= mem_rsp_data_i;
            if (beat_q == 0) header_q <= mem_rsp_data_i[31:0];
            if (beat_q == 3) reserved_q <= mem_rsp_data_i[127:96];
            if (beat_q == 3) state_q <= VALIDATE;
            else begin beat_q <= beat_q + 1'b1; state_q <= READ_REQ; end
          end
        end
        VALIDATE: begin
          if (header_q[7:0] != 8'd1 || header_q[15:8] != {5'd0, opcode_q} || reserved_q != 0)
            status_q <= BAD_DESCRIPTOR;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
`ifndef FORMAL
      // The dedicated formal harness proves the stronger external one-
      // outstanding property; keep this immediate simulation assertion out of
      // Yosys's async-reset lowering path.
      assert (!(outstanding_q && state_q == READ_REQ));
`endif
    end
  end
endmodule
