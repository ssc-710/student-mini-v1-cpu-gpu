// SPDX-License-Identifier: Apache-2.0
// Descriptor fetch plus a single selected P1/P2/P3/P4 operator/DMA seam.
// The descriptor engine's successful response is internal: software receives
// a response only after the selected operator finishes.
module litex_accelerator_dispatcher (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic [2:0] cmd_opcode_i, input logic [31:0] cmd_desc_addr_i,

  output logic mem_req_valid_o, input logic mem_req_ready_i,
  output logic mem_req_write_o, output logic [31:0] mem_req_addr_o,
  output logic [127:0] mem_req_wdata_o, output logic [15:0] mem_req_wstrb_o,
  input logic mem_rsp_valid_i, output logic mem_rsp_ready_o,
  input logic [127:0] mem_rsp_rdata_i, input logic mem_rsp_error_i,

  output logic op_valid_o, input logic op_ready_i,
  output logic [2:0] op_opcode_o, output logic [511:0] op_descriptor_o,
  output logic [7:0] op_operator_arg_o,
  input logic op_dma_req_valid_i, output logic op_dma_req_ready_o,
  input logic op_dma_req_write_i, input logic [31:0] op_dma_req_addr_i,
  input logic [127:0] op_dma_req_wdata_i, input logic [15:0] op_dma_req_wstrb_i,
  output logic op_dma_rsp_valid_o, input logic op_dma_rsp_ready_i,
  output logic [127:0] op_dma_rsp_rdata_o, output logic op_dma_rsp_error_o,
  input logic op_rsp_valid_i, output logic op_rsp_ready_o,
  input logic [7:0] op_rsp_status_i, input logic [63:0] op_rsp_cycles_i,

  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic [7:0] rsp_status_o, output logic [63:0] rsp_cycles_o
);
  typedef enum logic [2:0] {IDLE, FETCH, ISSUE, EXECUTE, RESPONSE} state_t;
  state_t state_q;
  logic [2:0] opcode_q;
  logic [511:0] descriptor_q, fetched_descriptor;
  logic [7:0] operator_arg_q, fetched_operator_arg;
  logic [7:0] status_q, fetch_status;
  // Service time is measured locally from accepted command through the
  // completion cycle.  Four 16-bit limbs avoid a 64-bit carry chain on every
  // cycle while preserving the frozen 64-bit CSR/result contract.
  logic [15:0] cycles_0_q, cycles_1_q, cycles_2_q, cycles_3_q;
  logic [63:0] fetch_cycles;
  logic count_enable_w;
  logic fetch_cmd_ready, fetch_rsp_valid, fetch_rsp_ready;
  logic fetch_mem_req_valid, fetch_mem_req_ready;
  logic [31:0] fetch_mem_req_addr;
  logic fetch_mem_rsp_valid, fetch_mem_rsp_ready;
  logic [31:0] unused_request_count, unused_response_count;
  logic [1:0] unused_peak;

  logic dma_mem_req_valid, dma_mem_req_ready;
  logic dma_mem_req_write;
  logic [31:0] dma_mem_req_addr;
  logic [127:0] dma_mem_req_wdata;
  logic [15:0] dma_mem_req_wstrb;
  logic dma_mem_rsp_valid, dma_mem_rsp_ready;
  logic [127:0] dma_rsp_data;
  logic dma_rsp_error, dma_rsp_valid;
  logic [31:0] unused_reads, unused_writes;
  logic [63:0] unused_read_bytes, unused_write_bytes, unused_wait;
  logic [1:0] unused_dma_peak;

  assign cmd_ready_o = state_q == IDLE && fetch_cmd_ready;
  assign fetch_rsp_ready = state_q == FETCH;
  assign op_valid_o = state_q == ISSUE;
  assign op_opcode_o = opcode_q;
  assign op_descriptor_o = descriptor_q;
  assign op_operator_arg_o = operator_arg_q;
  assign op_rsp_ready_o = state_q == EXECUTE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_status_o = status_q;
  assign rsp_cycles_o = {cycles_3_q, cycles_2_q, cycles_1_q, cycles_0_q};
  assign count_enable_w = state_q == FETCH || state_q == ISSUE || state_q == EXECUTE;

  // Descriptor fetch owns memory only during FETCH.  The selected operator's
  // DMA owns it during ISSUE/EXECUTE; no two clients can be outstanding.
  assign mem_req_valid_o = (state_q == FETCH) ? fetch_mem_req_valid : dma_mem_req_valid;
  assign mem_req_write_o = (state_q == FETCH) ? 1'b0 : dma_mem_req_write;
  assign mem_req_addr_o = (state_q == FETCH) ? fetch_mem_req_addr : dma_mem_req_addr;
  assign mem_req_wdata_o = (state_q == FETCH) ? 128'd0 : dma_mem_req_wdata;
  assign mem_req_wstrb_o = (state_q == FETCH) ? 16'd0 : dma_mem_req_wstrb;
  assign fetch_mem_req_ready = (state_q == FETCH) && mem_req_ready_i;
  assign dma_mem_req_ready = (state_q != FETCH) && mem_req_ready_i;
  assign fetch_mem_rsp_valid = (state_q == FETCH) && mem_rsp_valid_i;
  assign dma_mem_rsp_valid = (state_q != FETCH) && mem_rsp_valid_i;
  assign mem_rsp_ready_o = (state_q == FETCH) ? fetch_mem_rsp_ready : dma_mem_rsp_ready;

  litex_descriptor_engine u_descriptor (
    .clk_i, .rst_ni,
    .cmd_valid_i(cmd_valid_i && state_q == IDLE), .cmd_ready_o(fetch_cmd_ready),
    .cmd_opcode_i, .cmd_desc_addr_i,
    .mem_req_valid_o(fetch_mem_req_valid), .mem_req_ready_i(fetch_mem_req_ready),
    .mem_req_addr_o(fetch_mem_req_addr), .mem_rsp_valid_i(fetch_mem_rsp_valid),
    .mem_rsp_ready_o(fetch_mem_rsp_ready), .mem_rsp_data_i(mem_rsp_rdata_i),
    .mem_rsp_error_i,
    .descriptor_o(fetched_descriptor), .operator_arg_o(fetched_operator_arg),
    .dma_request_count_o(unused_request_count), .dma_response_count_o(unused_response_count),
    .dma_outstanding_peak_o(unused_peak),
    .rsp_valid_o(fetch_rsp_valid), .rsp_ready_i(fetch_rsp_ready),
    .rsp_status_o(fetch_status), .rsp_cycles_o(fetch_cycles)
  );

  dma_128_adapter u_operator_dma (
    .clk_i, .rst_ni,
    .cmd_valid_i(op_dma_req_valid_i), .cmd_ready_o(op_dma_req_ready_o),
    .cmd_write_i(op_dma_req_write_i), .cmd_addr_i(op_dma_req_addr_i),
    .cmd_wdata_i(op_dma_req_wdata_i), .cmd_wstrb_i(op_dma_req_wstrb_i),
    .mem_req_valid_o(dma_mem_req_valid), .mem_req_ready_i(dma_mem_req_ready),
    .mem_req_write_o(dma_mem_req_write), .mem_req_addr_o(dma_mem_req_addr),
    .mem_req_wdata_o(dma_mem_req_wdata), .mem_req_wstrb_o(dma_mem_req_wstrb),
    .mem_rsp_valid_i(dma_mem_rsp_valid), .mem_rsp_ready_o(dma_mem_rsp_ready),
    .mem_rsp_rdata_i, .mem_rsp_error_i,
    .rsp_valid_o(dma_rsp_valid), .rsp_ready_i(op_dma_rsp_ready_i),
    .rsp_rdata_o(dma_rsp_data), .rsp_error_o(dma_rsp_error),
    .counters_clear_i(state_q == IDLE), .read_requests_o(unused_reads),
    .write_requests_o(unused_writes), .read_bytes_o(unused_read_bytes),
    .write_bytes_o(unused_write_bytes), .wait_cycles_o(unused_wait),
    .outstanding_peak_o(unused_dma_peak)
  );
  assign op_dma_rsp_valid_o = dma_rsp_valid;
  assign op_dma_rsp_rdata_o = dma_rsp_data;
  assign op_dma_rsp_error_o = dma_rsp_error;

  // The descriptor engine and operator expose diagnostic cycle counts, but
  // adding them here would double-count time already spent in FETCH/EXECUTE.
  // They intentionally do not feed the service counter; synthesis may prune
  // their internal projection-only arithmetic when no explicit trace output
  // consumes it.

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      cycles_0_q <= '0;
      cycles_1_q <= '0;
      cycles_2_q <= '0;
      cycles_3_q <= '0;
    end else if (state_q == IDLE && cmd_valid_i && cmd_ready_o) begin
      cycles_0_q <= '0;
      cycles_1_q <= '0;
      cycles_2_q <= '0;
      cycles_3_q <= '0;
    end else if (count_enable_w) begin
      cycles_0_q <= cycles_0_q + 1'b1;
      if (&cycles_0_q) begin
        cycles_1_q <= cycles_1_q + 1'b1;
        if (&cycles_1_q) begin
          cycles_2_q <= cycles_2_q + 1'b1;
          if (&cycles_2_q) cycles_3_q <= cycles_3_q + 1'b1;
        end
      end
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE; opcode_q <= '0; descriptor_q <= '0; operator_arg_q <= '0;
      status_q <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i && cmd_ready_o) begin
          opcode_q <= cmd_opcode_i; state_q <= FETCH;
        end
        FETCH: begin
          if (fetch_rsp_valid) begin
            if (fetch_status != 0) begin status_q <= fetch_status; state_q <= RESPONSE; end
            else begin
              descriptor_q <= fetched_descriptor; operator_arg_q <= fetched_operator_arg;
              state_q <= ISSUE;
            end
          end
        end
        ISSUE: begin
          if (op_ready_i) state_q <= EXECUTE;
        end
        EXECUTE: begin
          if (op_rsp_valid_i) begin
            status_q <= op_rsp_status_i;
            state_q <= RESPONSE;
          end
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
