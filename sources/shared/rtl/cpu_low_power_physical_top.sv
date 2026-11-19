// SPDX-License-Identifier: Apache-2.0
// Platform P1 boundary.  activity_o is an opaque switching probe, not an
// architectural interface.  Gray encoding reduces probe-boundary toggles
// without changing CPU, Wishbone, LiteDRAM, cache, or SRAM behavior.
module cpu_low_power_physical_top (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [31:0] reset_vector_i,
    input  logic        timer_interrupt_i,
    input  logic        software_interrupt_i,
    input  logic [31:0] external_interrupt_i,
    output logic [31:0] activity_o
);
  logic [31:0] registered_activity;

  cpu_microarchitecture_physical_top u_microarchitecture (
      .clk_i, .rst_ni, .reset_vector_i, .timer_interrupt_i,
      .software_interrupt_i, .external_interrupt_i,
      .activity_o(registered_activity)
  );

  always_comb activity_o = registered_activity ^ (registered_activity >> 1);
endmodule
