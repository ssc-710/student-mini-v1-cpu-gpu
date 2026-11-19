// SPDX-License-Identifier: Apache-2.0
// Protocol-safe output isolation: ready/valid payloads are meaningful only
// while valid is asserted.  Driving zero otherwise prevents idle boundary
// toggles without changing any accepted transaction.
module valid_payload_isolator #(
  parameter int WIDTH = 1
) (
  input  logic             valid_i,
  input  logic [WIDTH-1:0] payload_i,
  output logic [WIDTH-1:0] payload_o
);
  assign payload_o = payload_i & {WIDTH{valid_i}};
endmodule
