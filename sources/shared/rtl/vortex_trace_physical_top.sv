// Frozen deepseek-v3.2-trace hardware boundary for the Vortex platform.
// The trace profile intentionally preserves only host command, DCR, address,
// tag, byte-enable and memory transaction behavior; it does not stand in for
// a numeric Vortex core or for RTLSIM performance evidence.
module vortex_trace_physical_top (
    input  logic         clk_i,
    input  logic         rst_ni,
    input  logic         host_cmd_valid_i,
    output logic         host_cmd_ready_o,
    input  logic [1:0]   host_cmd_kind_i,
    input  logic [11:0]  host_cmd_addr_i,
    input  logic [31:0]  host_cmd_data_i,
    output logic         host_rsp_valid_o,
    input  logic         host_rsp_ready_i,
    output logic [31:0]  host_rsp_data_o,
    output logic         host_rsp_error_o,
    output logic         dcr_req_valid_o,
    output logic         dcr_req_rw_o,
    output logic [11:0]  dcr_req_addr_o,
    output logic [31:0]  dcr_req_data_o,
    input  logic         dcr_rsp_valid_i,
    input  logic [31:0]  dcr_rsp_data_i,
    output logic         start_o,
    input  logic         busy_i,
    input  logic         vx_req_valid_i,
    output logic         vx_req_ready_o,
    input  logic         vx_req_rw_i,
    input  logic [7:0]   vx_req_byteen_i,
    input  logic [31:0]  vx_req_addr_i,
    input  logic [63:0]  vx_req_data_i,
    input  logic [15:0]  vx_req_tag_i,
    output logic         vx_rsp_valid_o,
    input  logic         vx_rsp_ready_i,
    output logic [63:0]  vx_rsp_data_o,
    output logic [15:0]  vx_rsp_tag_o,
    output logic         mem_req_valid_o,
    input  logic         mem_req_ready_i,
    output logic         mem_req_rw_o,
    output logic [7:0]   mem_req_byteen_o,
    output logic [31:0]  mem_req_addr_o,
    output logic [63:0]  mem_req_data_o,
    output logic [15:0]  mem_req_tag_o,
    input  logic         mem_rsp_valid_i,
    output logic         mem_rsp_ready_o,
    input  logic [63:0]  mem_rsp_data_i,
    input  logic [15:0]  mem_rsp_tag_i
);
  vortex_command_adapter command_adapter (
      .clk_i, .rst_ni,
      .host_cmd_valid_i, .host_cmd_ready_o, .host_cmd_kind_i,
      .host_cmd_addr_i, .host_cmd_data_i,
      .host_rsp_valid_o, .host_rsp_ready_i, .host_rsp_data_o,
      .host_rsp_error_o, .dcr_req_valid_o, .dcr_req_rw_o,
      .dcr_req_addr_o, .dcr_req_data_o, .dcr_rsp_valid_i,
      .dcr_rsp_data_i, .start_o, .busy_i
  );

  vortex_memory_adapter memory_adapter (
      .clk_i, .rst_ni,
      .vx_req_valid_i, .vx_req_ready_o, .vx_req_rw_i,
      .vx_req_byteen_i, .vx_req_addr_i, .vx_req_data_i, .vx_req_tag_i,
      .vx_rsp_valid_o, .vx_rsp_ready_i, .vx_rsp_data_o, .vx_rsp_tag_o,
      .mem_req_valid_o, .mem_req_ready_i, .mem_req_rw_o,
      .mem_req_byteen_o, .mem_req_addr_o, .mem_req_data_o, .mem_req_tag_o,
      .mem_rsp_valid_i, .mem_rsp_ready_o, .mem_rsp_data_i, .mem_rsp_tag_i
  );
endmodule
