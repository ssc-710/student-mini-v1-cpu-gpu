module vortex_memory_adapter #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 64,
    parameter int TAG_WIDTH = 16
) (
    input  logic                  clk_i,
    input  logic                  rst_ni,
    input  logic                  vx_req_valid_i,
    output logic                  vx_req_ready_o,
    input  logic                  vx_req_rw_i,
    input  logic [DATA_WIDTH/8-1:0] vx_req_byteen_i,
    input  logic [ADDR_WIDTH-1:0] vx_req_addr_i,
    input  logic [DATA_WIDTH-1:0] vx_req_data_i,
    input  logic [TAG_WIDTH-1:0]  vx_req_tag_i,
    output logic                  vx_rsp_valid_o,
    input  logic                  vx_rsp_ready_i,
    output logic [DATA_WIDTH-1:0] vx_rsp_data_o,
    output logic [TAG_WIDTH-1:0]  vx_rsp_tag_o,
    output logic                  mem_req_valid_o,
    input  logic                  mem_req_ready_i,
    output logic                  mem_req_rw_o,
    output logic [DATA_WIDTH/8-1:0] mem_req_byteen_o,
    output logic [ADDR_WIDTH-1:0] mem_req_addr_o,
    output logic [DATA_WIDTH-1:0] mem_req_data_o,
    output logic [TAG_WIDTH-1:0]  mem_req_tag_o,
    input  logic                  mem_rsp_valid_i,
    output logic                  mem_rsp_ready_o,
    input  logic [DATA_WIDTH-1:0] mem_rsp_data_i,
    input  logic [TAG_WIDTH-1:0]  mem_rsp_tag_i
);
  logic req_valid_q, req_rw_q;
  logic [DATA_WIDTH/8-1:0] req_byteen_q;
  logic [ADDR_WIDTH-1:0] req_addr_q;
  logic [DATA_WIDTH-1:0] req_data_q;
  logic [TAG_WIDTH-1:0] req_tag_q;
  logic rsp_valid_q;
  logic [DATA_WIDTH-1:0] rsp_data_q;
  logic [TAG_WIDTH-1:0] rsp_tag_q;

  assign vx_req_ready_o = !req_valid_q || mem_req_ready_i;
  assign mem_req_valid_o = req_valid_q;
  assign mem_req_rw_o = req_rw_q;
  assign mem_req_byteen_o = req_byteen_q;
  assign mem_req_addr_o = req_addr_q;
  assign mem_req_data_o = req_data_q;
  assign mem_req_tag_o = req_tag_q;
  assign mem_rsp_ready_o = !rsp_valid_q || vx_rsp_ready_i;
  assign vx_rsp_valid_o = rsp_valid_q;
  assign vx_rsp_data_o = rsp_data_q;
  assign vx_rsp_tag_o = rsp_tag_q;

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      req_valid_q <= 1'b0;
      req_rw_q <= 1'b0;
      req_byteen_q <= '0;
      req_addr_q <= '0;
      req_data_q <= '0;
      req_tag_q <= '0;
      rsp_valid_q <= 1'b0;
      rsp_data_q <= '0;
      rsp_tag_q <= '0;
    end else begin
      if (vx_req_ready_o) begin
        req_valid_q <= vx_req_valid_i;
        if (vx_req_valid_i) begin
          req_rw_q <= vx_req_rw_i;
          req_byteen_q <= vx_req_byteen_i;
          req_addr_q <= vx_req_addr_i;
          req_data_q <= vx_req_data_i;
          req_tag_q <= vx_req_tag_i;
        end
      end
      if (mem_rsp_ready_o) begin
        rsp_valid_q <= mem_rsp_valid_i;
        if (mem_rsp_valid_i) begin
          rsp_data_q <= mem_rsp_data_i;
          rsp_tag_q <= mem_rsp_tag_i;
        end
      end
    end
  end
endmodule
