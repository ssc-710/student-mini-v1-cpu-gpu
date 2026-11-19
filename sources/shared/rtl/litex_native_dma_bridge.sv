// SPDX-License-Identifier: Apache-2.0
// One-outstanding bridge from the frozen accelerator DMA request/response seam
// to LiteDRAM's independent native command, write-data and read-data channels.
module litex_native_dma_bridge #(
  parameter int NATIVE_ADDR_WIDTH = 28,
  parameter bit DEBUG = 1'b0,
  parameter bit WRITE_FENCE = 1'b1
) (
  input  logic         clk_i,
  input  logic         rst_ni,
  input  logic         req_valid_i,
  output logic         req_ready_o,
  input  logic         req_write_i,
  input  logic [31:0]  req_addr_i,
  input  logic [127:0] req_wdata_i,
  input  logic [15:0]  req_wstrb_i,
  output logic         rsp_valid_o,
  input  logic         rsp_ready_i,
  output logic [127:0] rsp_rdata_o,
  output logic         rsp_error_o,

  output logic         native_cmd_valid_o,
  input  logic         native_cmd_ready_i,
  output logic         native_cmd_we_o,
  output logic [NATIVE_ADDR_WIDTH-1:0] native_cmd_addr_o,
  output logic         native_wdata_valid_o,
  input  logic         native_wdata_ready_i,
  output logic [127:0] native_wdata_o,
  output logic [15:0]  native_wstrb_o,
  input  logic         native_rdata_valid_i,
  output logic         native_rdata_ready_o,
  input  logic [127:0] native_rdata_i
);
  // LiteDRAM's native writers issue the command before presenting its data.
  // Although cmd/wdata are decoupled streams, accepting both in the same
  // cycle is not a portable association contract across crossbar/FIFO
  // configurations.  Keep one request outstanding and serialize the two
  // handshakes exactly like LiteDRAMNativePortDMAWriter.
  typedef enum logic [3:0] {
    IDLE, ISSUE_READ, WAIT_READ, ISSUE_WRITE_CMD, ISSUE_WRITE_DATA,
    ISSUE_WRITE_FENCE, WAIT_WRITE_FENCE, RESPONSE
  } state_t;
  state_t state_q;
  logic write_q;
  logic [31:0] addr_q;
  logic [127:0] wdata_q, rdata_q;
  logic [15:0] wstrb_q;

  assign req_ready_o = state_q == IDLE;
  assign native_cmd_valid_o =
    (state_q == ISSUE_READ) || (state_q == ISSUE_WRITE_CMD) ||
    (state_q == ISSUE_WRITE_FENCE);
  assign native_cmd_we_o = state_q == ISSUE_WRITE_CMD;
  assign native_cmd_addr_o = addr_q[4 +: NATIVE_ADDR_WIDTH];
  assign native_wdata_valid_o = state_q == ISSUE_WRITE_DATA;
  assign native_wdata_o = wdata_q;
  assign native_wstrb_o = wstrb_q;
  assign native_rdata_ready_o =
    (state_q == WAIT_READ) || (state_q == WAIT_WRITE_FENCE);
  assign rsp_valid_o = state_q == RESPONSE;
  assign rsp_rdata_o = rdata_q;
  assign rsp_error_o = 1'b0;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      write_q <= 1'b0;
      addr_q <= '0; wdata_q <= '0; wstrb_q <= '0; rdata_q <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (req_valid_i) begin
          write_q <= req_write_i;
          addr_q <= req_addr_i;
          wdata_q <= req_wdata_i;
          wstrb_q <= req_wstrb_i;
          state_q <= req_write_i ? ISSUE_WRITE_CMD : ISSUE_READ;
        end
        ISSUE_READ: if (native_cmd_ready_i) state_q <= WAIT_READ;
        WAIT_READ: if (native_rdata_valid_i) begin
          rdata_q <= native_rdata_i;
          state_q <= RESPONSE;
        end
        ISSUE_WRITE_CMD:
          if (native_cmd_ready_i) begin
            if (DEBUG) $display("COURSE_DMA_WRITE_CMD addr=%08x data=%032x strb=%04x",
                                addr_q, wdata_q, wstrb_q);
            state_q <= ISSUE_WRITE_DATA;
          end
        ISSUE_WRITE_DATA: if (native_wdata_ready_i) begin
          if (DEBUG) $display("COURSE_DMA_WRITE_DATA addr=%08x", addr_q);
          rdata_q <= '0;
          state_q <= WRITE_FENCE ? ISSUE_WRITE_FENCE : RESPONSE;
        end
        ISSUE_WRITE_FENCE:
          if (native_cmd_ready_i) state_q <= WAIT_WRITE_FENCE;
        WAIT_WRITE_FENCE: if (native_rdata_valid_i) begin
          // A same-port read cannot pass the preceding write.  Returning only
          // after its data arrives turns the request/response seam into a real
          // DMA completion contract instead of an enqueue acknowledgement.
          rdata_q <= native_rdata_i;
          if (DEBUG && ((addr_q[19:0] == 20'h816c0) ||
                        (addr_q[19:0] == 20'h856c0)))
            $display("COURSE_DMA_FENCE addr=%08x wrote=%032x read=%032x strb=%04x",
                     addr_q, wdata_q, native_rdata_i, wstrb_q);
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
