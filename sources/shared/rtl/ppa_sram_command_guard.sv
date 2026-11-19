// SPDX-License-Identifier: Apache-2.0
// PPA-visible command scratch.  A command is first committed to the shared
// 128x256 SRAM seam, synchronously read back, and only then presented to the
// descriptor/DMA engine.  The read-back dependency prevents an unconnected or
// optimized-away macro from masquerading as macro-backed evidence.
module ppa_sram_command_guard (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  logic        cmd_valid_i,
  output logic        cmd_ready_o,
  input  logic [2:0]  cmd_opcode_i,
  input  logic [31:0] cmd_desc_addr_i,
  output logic        guarded_valid_o,
  input  logic        guarded_ready_i,
  output logic [2:0]  guarded_opcode_o,
  output logic [31:0] guarded_desc_addr_o
);
  typedef enum logic [1:0] {IDLE, READ_BACK, ISSUE} state_t;
  state_t state_q;
`ifdef COURSE_USE_OPENRAM_COMPACT
  localparam int SCRATCH_WIDTH = 40;
  localparam int SCRATCH_DEPTH = 16;
`elsif COURSE_USE_OPENRAM_SMALL
  localparam int SCRATCH_WIDTH = 128;
  localparam int SCRATCH_DEPTH = 16;
`else
  localparam int SCRATCH_WIDTH = 128;
  localparam int SCRATCH_DEPTH = 256;
`endif
  logic [SCRATCH_WIDTH-1:0] scratch_rdata;
  logic scratch_enable, scratch_write;
  logic [SCRATCH_WIDTH-1:0] scratch_wdata;

  assign cmd_ready_o = state_q == IDLE;
  assign guarded_valid_o = state_q == ISSUE;
  assign guarded_opcode_o = scratch_rdata[2:0];
  assign guarded_desc_addr_o = scratch_rdata[34:3];
  assign scratch_enable = (state_q == READ_BACK) ||
                          (state_q == IDLE && cmd_valid_i && cmd_ready_o);
  assign scratch_write = state_q == IDLE;
`ifdef COURSE_USE_OPENRAM_COMPACT
  assign scratch_wdata = {5'h0, cmd_desc_addr_i, cmd_opcode_i};
`else
  assign scratch_wdata = {61'h0, 32'h43534d44, cmd_desc_addr_i, cmd_opcode_i};
`endif

  sram_1rw_seam #(.WIDTH(SCRATCH_WIDTH), .DEPTH(SCRATCH_DEPTH)) u_command_scratch (
    .clk_i, .enable_i(scratch_enable), .write_i(scratch_write),
    .addr_i('0), .wdata_i(scratch_wdata), .wstrb_i({SCRATCH_WIDTH/8{1'b1}}),
    .rdata_o(scratch_rdata)
  );

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) state_q <= IDLE;
    else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i && cmd_ready_o) state_q <= READ_BACK;
        READ_BACK: state_q <= ISSUE;
        ISSUE: if (guarded_valid_o && guarded_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
