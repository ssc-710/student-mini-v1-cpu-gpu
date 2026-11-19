// SPDX-License-Identifier: Apache-2.0
// Platform M1 boundary: preserve accepted Vortex memory transactions while
// suppressing invalid-cycle switching on every wide request payload.
module vortex_microarchitecture_physical_top #(
    parameter int MEM_PORTS = 2,
    parameter int MEM_ADDR_WIDTH = 26,
    parameter int MEM_DATA_WIDTH = 512,
    parameter int MEM_TAG_WIDTH = 10
) (
    input logic clk_i, input logic rst_ni,
    input logic host_cmd_valid_i, output logic host_cmd_ready_o,
    input logic [1:0] host_cmd_kind_i, input logic [11:0] host_cmd_addr_i,
    input logic [31:0] host_cmd_data_i,
    output logic host_rsp_valid_o, input logic host_rsp_ready_i,
    output logic [31:0] host_rsp_data_o, output logic host_rsp_error_o,
    output logic busy_o,
    output logic [0:MEM_PORTS-1] mem_req_valid_o,
    input logic [0:MEM_PORTS-1] mem_req_ready_i,
    output logic [0:MEM_PORTS-1] mem_req_rw_o,
    output logic [MEM_PORTS*(MEM_DATA_WIDTH/8)-1:0] mem_req_byteen_o,
    output logic [MEM_PORTS*MEM_ADDR_WIDTH-1:0] mem_req_addr_o,
    output logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] mem_req_data_o,
    output logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] mem_req_tag_o,
    input logic [0:MEM_PORTS-1] mem_rsp_valid_i,
    output logic [0:MEM_PORTS-1] mem_rsp_ready_o,
    input logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] mem_rsp_data_i,
    input logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] mem_rsp_tag_i
);
  localparam int BYTEEN_WIDTH = MEM_DATA_WIDTH / 8;
  localparam int PAYLOAD_WIDTH = 1 + BYTEEN_WIDTH + MEM_ADDR_WIDTH
                                   + MEM_DATA_WIDTH + MEM_TAG_WIDTH;
  logic [0:MEM_PORTS-1] raw_valid, raw_rw;
  logic [MEM_PORTS*BYTEEN_WIDTH-1:0] raw_byteen;
  logic [MEM_PORTS*MEM_ADDR_WIDTH-1:0] raw_addr;
  logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] raw_data;
  logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] raw_tag;

  vortex_physical_top #(
      .MEM_PORTS(MEM_PORTS), .MEM_ADDR_WIDTH(MEM_ADDR_WIDTH),
      .MEM_DATA_WIDTH(MEM_DATA_WIDTH), .MEM_TAG_WIDTH(MEM_TAG_WIDTH)
  ) u_platform (
      .clk_i, .rst_ni, .host_cmd_valid_i, .host_cmd_ready_o,
      .host_cmd_kind_i, .host_cmd_addr_i, .host_cmd_data_i,
      .host_rsp_valid_o, .host_rsp_ready_i, .host_rsp_data_o,
      .host_rsp_error_o, .busy_o,
      .mem_req_valid_o(raw_valid), .mem_req_ready_i,
      .mem_req_rw_o(raw_rw), .mem_req_byteen_o(raw_byteen),
      .mem_req_addr_o(raw_addr), .mem_req_data_o(raw_data),
      .mem_req_tag_o(raw_tag), .mem_rsp_valid_i, .mem_rsp_ready_o,
      .mem_rsp_data_i, .mem_rsp_tag_i
  );
  assign mem_req_valid_o = raw_valid;

  genvar port_index;
  generate
    for (port_index = 0; port_index < MEM_PORTS; port_index++) begin : g_isolate
      logic [PAYLOAD_WIDTH-1:0] raw_payload, isolated_payload;
      assign raw_payload = {
          raw_rw[port_index],
          raw_byteen[port_index*BYTEEN_WIDTH +: BYTEEN_WIDTH],
          raw_addr[port_index*MEM_ADDR_WIDTH +: MEM_ADDR_WIDTH],
          raw_data[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH],
          raw_tag[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH]
      };
      valid_payload_isolator #(.WIDTH(PAYLOAD_WIDTH)) u_isolator (
          .valid_i(raw_valid[port_index]), .payload_i(raw_payload),
          .payload_o(isolated_payload)
      );
      assign {
          mem_req_rw_o[port_index],
          mem_req_byteen_o[port_index*BYTEEN_WIDTH +: BYTEEN_WIDTH],
          mem_req_addr_o[port_index*MEM_ADDR_WIDTH +: MEM_ADDR_WIDTH],
          mem_req_data_o[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH],
          mem_req_tag_o[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH]
      } = isolated_payload;
    end
  endgenerate
endmodule
