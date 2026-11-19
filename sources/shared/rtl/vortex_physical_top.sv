// Frozen Vortex core/cache/scheduler boundary plus the formally checked host
// command and memory skid adapters. Widths are fixed per generated Vortex
// profile by the physical config; no host model or SimX timing enters here.
module vortex_physical_top #(
    parameter int MEM_PORTS = 2,
    parameter int MEM_ADDR_WIDTH = 26,
    parameter int MEM_DATA_WIDTH = 512,
    parameter int MEM_TAG_WIDTH = 10
) (
    input  logic clk_i,
    input  logic rst_ni,
    input  logic host_cmd_valid_i,
    output logic host_cmd_ready_o,
    input  logic [1:0] host_cmd_kind_i,
    input  logic [11:0] host_cmd_addr_i,
    input  logic [31:0] host_cmd_data_i,
    output logic host_rsp_valid_o,
    input  logic host_rsp_ready_i,
    output logic [31:0] host_rsp_data_o,
    output logic host_rsp_error_o,
    output logic busy_o,
    output logic [0:MEM_PORTS-1] mem_req_valid_o,
    input  logic [0:MEM_PORTS-1] mem_req_ready_i,
    output logic [0:MEM_PORTS-1] mem_req_rw_o,
    output logic [MEM_PORTS*(MEM_DATA_WIDTH/8)-1:0] mem_req_byteen_o,
    output logic [MEM_PORTS*MEM_ADDR_WIDTH-1:0] mem_req_addr_o,
    output logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] mem_req_data_o,
    output logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] mem_req_tag_o,
    input  logic [0:MEM_PORTS-1] mem_rsp_valid_i,
    output logic [0:MEM_PORTS-1] mem_rsp_ready_o,
    input  logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] mem_rsp_data_i,
    input  logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] mem_rsp_tag_i
);
  logic dcr_req_valid, dcr_req_rw, dcr_rsp_valid, start;
  logic [11:0] dcr_req_addr;
  logic [31:0] dcr_req_data, dcr_rsp_data;
  logic [0:MEM_PORTS-1] vx_req_valid, vx_req_ready, vx_req_rw;
  logic [MEM_PORTS*(MEM_DATA_WIDTH/8)-1:0] vx_req_byteen;
  logic [MEM_PORTS*MEM_ADDR_WIDTH-1:0] vx_req_addr;
  logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] vx_req_data;
  logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] vx_req_tag;
  logic [0:MEM_PORTS-1] vx_rsp_valid, vx_rsp_ready;
  logic [MEM_PORTS*MEM_DATA_WIDTH-1:0] vx_rsp_data;
  logic [MEM_PORTS*MEM_TAG_WIDTH-1:0] vx_rsp_tag;

  vortex_command_adapter command_adapter (
      .clk_i, .rst_ni,
      .host_cmd_valid_i, .host_cmd_ready_o, .host_cmd_kind_i,
      .host_cmd_addr_i, .host_cmd_data_i,
      .host_rsp_valid_o, .host_rsp_ready_i, .host_rsp_data_o,
      .host_rsp_error_o, .dcr_req_valid_o(dcr_req_valid),
      .dcr_req_rw_o(dcr_req_rw), .dcr_req_addr_o(dcr_req_addr),
      .dcr_req_data_o(dcr_req_data), .dcr_rsp_valid_i(dcr_rsp_valid),
      .dcr_rsp_data_i(dcr_rsp_data), .start_o(start), .busy_i(busy_o)
  );

  Vortex core (
      .clk(clk_i), .reset(~rst_ni),
      .mem_req_valid(vx_req_valid), .mem_req_rw(vx_req_rw),
      .mem_req_byteen(vx_req_byteen), .mem_req_addr(vx_req_addr),
      .mem_req_data(vx_req_data), .mem_req_tag(vx_req_tag),
      .mem_req_ready(vx_req_ready), .mem_rsp_valid(vx_rsp_valid),
      .mem_rsp_data(vx_rsp_data), .mem_rsp_tag(vx_rsp_tag),
      .mem_rsp_ready(vx_rsp_ready), .dcr_req_valid(dcr_req_valid),
      .dcr_req_rw(dcr_req_rw), .dcr_req_addr(dcr_req_addr),
      .dcr_req_data(dcr_req_data), .dcr_rsp_valid(dcr_rsp_valid),
      .dcr_rsp_data(dcr_rsp_data), .start(start), .busy(busy_o)
  );

  genvar port_index;
  generate
    for (port_index = 0; port_index < MEM_PORTS; port_index++) begin : g_memory_adapter
      vortex_memory_adapter #(
          .ADDR_WIDTH(MEM_ADDR_WIDTH), .DATA_WIDTH(MEM_DATA_WIDTH),
          .TAG_WIDTH(MEM_TAG_WIDTH)
      ) adapter (
          .clk_i, .rst_ni,
          .vx_req_valid_i(vx_req_valid[port_index]),
          .vx_req_ready_o(vx_req_ready[port_index]),
          .vx_req_rw_i(vx_req_rw[port_index]),
          .vx_req_byteen_i(vx_req_byteen[port_index*(MEM_DATA_WIDTH/8) +: (MEM_DATA_WIDTH/8)]),
          .vx_req_addr_i(vx_req_addr[port_index*MEM_ADDR_WIDTH +: MEM_ADDR_WIDTH]),
          .vx_req_data_i(vx_req_data[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH]),
          .vx_req_tag_i(vx_req_tag[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH]),
          .vx_rsp_valid_o(vx_rsp_valid[port_index]),
          .vx_rsp_ready_i(vx_rsp_ready[port_index]),
          .vx_rsp_data_o(vx_rsp_data[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH]),
          .vx_rsp_tag_o(vx_rsp_tag[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH]),
          .mem_req_valid_o(mem_req_valid_o[port_index]),
          .mem_req_ready_i(mem_req_ready_i[port_index]),
          .mem_req_rw_o(mem_req_rw_o[port_index]),
          .mem_req_byteen_o(mem_req_byteen_o[port_index*(MEM_DATA_WIDTH/8) +: (MEM_DATA_WIDTH/8)]),
          .mem_req_addr_o(mem_req_addr_o[port_index*MEM_ADDR_WIDTH +: MEM_ADDR_WIDTH]),
          .mem_req_data_o(mem_req_data_o[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH]),
          .mem_req_tag_o(mem_req_tag_o[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH]),
          .mem_rsp_valid_i(mem_rsp_valid_i[port_index]),
          .mem_rsp_ready_o(mem_rsp_ready_o[port_index]),
          .mem_rsp_data_i(mem_rsp_data_i[port_index*MEM_DATA_WIDTH +: MEM_DATA_WIDTH]),
          .mem_rsp_tag_i(mem_rsp_tag_i[port_index*MEM_TAG_WIDTH +: MEM_TAG_WIDTH])
      );
    end
  endgenerate
endmodule
