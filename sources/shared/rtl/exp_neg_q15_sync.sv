// SPDX-License-Identifier: Apache-2.0
// Two-stage banked exponential ROM for the P1/P2 timing candidate.
//
// A register placed only after a 1025:1 ROM mux does not shorten that mux's
// critical path.  This implementation first evaluates thirty-three independent
// 32-entry banks and registers their candidates, then selects the requested
// bank in the following cycle.  The checked-in ROM image and address rounding
// are identical to exp_neg_q15; only the latency changes, and valid_o states
// exactly when the registered result is available.
module exp_neg_q15_sync (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic               valid_i,
  input  logic signed [15:0] x_q11_i,
  output logic               valid_o,
  output logic        [15:0] exp_q15_o
);
`ifndef EXP_Q15_MEM_FILE
`define EXP_Q15_MEM_FILE "shared/rtl/exp_q15_q6.mem"
`endif
  localparam int BANK_SIZE = 32;
  localparam int BANK_COUNT = 33;
  logic [15:0] rom [0:1024];
  logic [15:0] magnitude;
  logic [10:0] quotient, rounded, address;
  logic [4:0] remainder;
  logic [15:0] bank_value_w [0:BANK_COUNT-1];
  logic [15:0] bank_value_q [0:BANK_COUNT-1];
  logic [5:0] bank_select_q;
  logic stage1_valid_q;
  integer bank_comb;
  integer bank_seq;
  integer entry;

  initial $readmemh(`EXP_Q15_MEM_FILE, rom);

  always_comb begin
    magnitude = '0;
    quotient = '0;
    remainder = '0;
    rounded = '0;
    address = 11'd1024;
    if (x_q11_i[15]) begin
      magnitude = (~x_q11_i) + 1'b1;
      quotient = magnitude[15:5];
      remainder = magnitude[4:0];
      rounded = quotient + 11'((remainder > 5'd16) ||
                               ((remainder == 5'd16) && quotient[0]));
      address = rounded >= 11'd1024 ? 11'd0 : 11'd1024 - rounded;
    end
    for (bank_comb = 0; bank_comb < BANK_COUNT; bank_comb = bank_comb + 1) begin
      entry = bank_comb * BANK_SIZE + 32'(address[4:0]);
      bank_value_w[bank_comb] = entry <= 1024 ? rom[entry] : 16'h0000;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      stage1_valid_q <= 1'b0;
      valid_o <= 1'b0;
      exp_q15_o <= '0;
    end else begin
      stage1_valid_q <= valid_i;
      valid_o <= stage1_valid_q;
      if (valid_i) begin
        bank_select_q <= address[10:5];
        for (bank_seq = 0; bank_seq < BANK_COUNT; bank_seq = bank_seq + 1)
          bank_value_q[bank_seq] <= bank_value_w[bank_seq];
      end
      if (stage1_valid_q) exp_q15_o <= bank_value_q[bank_select_q];
    end
  end
endmodule
