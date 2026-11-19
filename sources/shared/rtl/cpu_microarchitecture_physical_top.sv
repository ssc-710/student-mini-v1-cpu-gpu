// SPDX-License-Identifier: Apache-2.0
// Platform M1 boundary.  The CPU/memory behavior is unchanged; the exported
// activity probe is registered so the five physical profiles use a distinct,
// synthesizable instrumentation boundary rather than reusing B0 netlists.
module cpu_microarchitecture_physical_top (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [31:0] reset_vector_i,
    input  logic        timer_interrupt_i,
    input  logic        software_interrupt_i,
    input  logic [31:0] external_interrupt_i,
    output logic [31:0] activity_o
);
  logic [31:0] raw_activity;

  cpu_vexriscv_physical_top u_platform (
      .clk_i, .rst_ni, .reset_vector_i, .timer_interrupt_i,
      .software_interrupt_i, .external_interrupt_i,
      .activity_o(raw_activity)
  );

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) activity_o <= '0;
    else activity_o <= raw_activity;
  end
endmodule
