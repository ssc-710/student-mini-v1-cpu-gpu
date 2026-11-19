// SPDX-License-Identifier: Apache-2.0
module perf_counters #(
  parameter int WIDTH = 64,
  parameter int BYTES_PER_BEAT = 16
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             clear_i,
  input  logic             start_i,
  input  logic             done_i,
  input  logic             busy_i,
  input  logic             stall_i,
  input  logic             request_fire_i,
  input  logic             response_fire_i,
  output logic             active_o,
  output logic [WIDTH-1:0] cycles_o,
  output logic [WIDTH-1:0] busy_cycles_o,
  output logic [WIDTH-1:0] stall_cycles_o,
  output logic [WIDTH-1:0] requests_o,
  output logic [WIDTH-1:0] responses_o,
  output logic [WIDTH-1:0] bytes_o
);
  logic active_q;

  assign active_o = active_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      active_q <= 1'b0;
      cycles_o <= '0;
      busy_cycles_o <= '0;
      stall_cycles_o <= '0;
      requests_o <= '0;
      responses_o <= '0;
      bytes_o <= '0;
    end else begin
      if (clear_i) begin
        cycles_o <= '0;
        busy_cycles_o <= '0;
        stall_cycles_o <= '0;
        requests_o <= '0;
        responses_o <= '0;
        bytes_o <= '0;
      end
      if (start_i) active_q <= 1'b1;
      if (done_i) active_q <= 1'b0;
      if (active_q) begin
        cycles_o <= cycles_o + 1'b1;
        if (busy_i) busy_cycles_o <= busy_cycles_o + 1'b1;
        if (stall_i) stall_cycles_o <= stall_cycles_o + 1'b1;
        if (request_fire_i) requests_o <= requests_o + 1'b1;
        if (response_fire_i) begin
          responses_o <= responses_o + 1'b1;
          bytes_o <= bytes_o + BYTES_PER_BEAT;
        end
      end
    end
  end
endmodule
