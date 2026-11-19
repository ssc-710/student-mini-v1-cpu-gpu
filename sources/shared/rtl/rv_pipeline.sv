// SPDX-License-Identifier: Apache-2.0
module rv_pipeline #(
  parameter int WIDTH = 32
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             in_valid_i,
  output logic             in_ready_o,
  input  logic [WIDTH-1:0] in_data_i,
  output logic             out_valid_o,
  input  logic             out_ready_i,
  output logic [WIDTH-1:0] out_data_o
);
  logic full_q;
  logic [WIDTH-1:0] data_q;

  assign in_ready_o = ~full_q | out_ready_i;
  assign out_valid_o = full_q;
  assign out_data_o = data_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      full_q <= 1'b0;
      data_q <= '0;
    end else if (in_ready_o) begin
      full_q <= in_valid_i;
      if (in_valid_i) data_q <= in_data_i;
    end
  end

`ifdef FORMAL
  logic past_valid_q;
  always_ff @(posedge clk_i) past_valid_q <= 1'b1;
  always_ff @(posedge clk_i) begin
    if (past_valid_q && $past(rst_ni) && $past(out_valid_o && !out_ready_i)) begin
      assert(out_valid_o);
      assert(out_data_o == $past(out_data_o));
    end
  end
`endif
endmodule
