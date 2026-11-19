// SPDX-License-Identifier: Apache-2.0
// Platform P1 boundary: keep M1 memory isolation and also suppress invalid
// host-response payload switching.
module vortex_low_power_physical_top #(
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
  logic raw_rsp_valid, raw_rsp_error;
  logic [31:0] raw_rsp_data;
  logic [32:0] raw_rsp_payload, isolated_rsp_payload;

  vortex_microarchitecture_physical_top #(
      .MEM_PORTS(MEM_PORTS), .MEM_ADDR_WIDTH(MEM_ADDR_WIDTH),
      .MEM_DATA_WIDTH(MEM_DATA_WIDTH), .MEM_TAG_WIDTH(MEM_TAG_WIDTH)
  ) u_microarchitecture (
      .clk_i, .rst_ni, .host_cmd_valid_i, .host_cmd_ready_o,
      .host_cmd_kind_i, .host_cmd_addr_i, .host_cmd_data_i,
      .host_rsp_valid_o(raw_rsp_valid), .host_rsp_ready_i,
      .host_rsp_data_o(raw_rsp_data), .host_rsp_error_o(raw_rsp_error),
      .busy_o, .mem_req_valid_o, .mem_req_ready_i, .mem_req_rw_o,
      .mem_req_byteen_o, .mem_req_addr_o, .mem_req_data_o, .mem_req_tag_o,
      .mem_rsp_valid_i, .mem_rsp_ready_o, .mem_rsp_data_i, .mem_rsp_tag_i
  );
  assign raw_rsp_payload = {raw_rsp_error, raw_rsp_data};
  valid_payload_isolator #(.WIDTH(33)) u_response_isolator (
      .valid_i(raw_rsp_valid), .payload_i(raw_rsp_payload),
      .payload_o(isolated_rsp_payload)
  );
  assign host_rsp_valid_o = raw_rsp_valid;
  assign {host_rsp_error_o, host_rsp_data_o} = isolated_rsp_payload;
endmodule
