// SPDX-License-Identifier: Apache-2.0
// Two-stage banked SiLU ROM used by the P3 B1 timing experiment.  The first
// stage registers one candidate from each 32-entry bank; the second selects
// the addressed bank.  This breaks the original 2049:1 combinational mux while
// preserving the exact checked-in Q-format table and RNE address contract.
module silu_q11_sync (
  input logic clk_i, input logic rst_ni, input logic valid_i,
  input logic signed [15:0] x_q11_i,
  output logic valid_o, output logic signed [15:0] silu_q11_o
);
`ifndef SILU_Q11_MEM_FILE
`define SILU_Q11_MEM_FILE "shared/rtl/silu_q11_q6.mem"
`endif
  localparam int BANK_SIZE = 32;
  localparam int BANK_COUNT = 65;
  logic signed [15:0] rom [0:2048];
  logic negative;
  logic [15:0] magnitude;
  logic [10:0] quotient, rounded_magnitude;
  logic [4:0] remainder;
  logic signed [11:0] index_q6;
  logic [11:0] address;
  logic signed [15:0] bank_value_w [0:BANK_COUNT-1];
  logic signed [15:0] bank_value_q [0:BANK_COUNT-1];
  logic [6:0] bank_select_q;
  logic stage1_valid_q;
  integer bank_comb;
  integer bank_seq;
  integer entry;

  initial $readmemh(`SILU_Q11_MEM_FILE, rom);
  always_comb begin
    negative = x_q11_i[15];
    magnitude = negative ? (~x_q11_i + 1'b1) : x_q11_i;
    quotient = magnitude[15:5];
    remainder = magnitude[4:0];
    rounded_magnitude = quotient +
      11'((remainder > 5'd16) ||
          ((remainder == 5'd16) && quotient[0]));
    index_q6 = negative ? -$signed({1'b0, rounded_magnitude}) :
                          $signed({1'b0, rounded_magnitude});
    if (index_q6 < -12'sd1024) address = 12'd0;
    else if (index_q6 > 12'sd1024) address = 12'd2048;
    else address = index_q6 + 12'sd1024;
    for (bank_comb = 0; bank_comb < BANK_COUNT; bank_comb = bank_comb + 1) begin
      entry = bank_comb * BANK_SIZE + 32'(address[4:0]);
      bank_value_w[bank_comb] = entry <= 2048 ? rom[entry] : 16'sh0000;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      stage1_valid_q <= 1'b0;
      valid_o <= 1'b0;
      silu_q11_o <= '0;
    end
    else begin
      stage1_valid_q <= valid_i;
      valid_o <= stage1_valid_q;
      if (valid_i) begin
        bank_select_q <= address[11:5];
        for (bank_seq = 0; bank_seq < BANK_COUNT; bank_seq = bank_seq + 1)
          bank_value_q[bank_seq] <= bank_value_w[bank_seq];
      end
      if (stage1_valid_q) silu_q11_o <= bank_value_q[bank_select_q];
    end
  end
endmodule
