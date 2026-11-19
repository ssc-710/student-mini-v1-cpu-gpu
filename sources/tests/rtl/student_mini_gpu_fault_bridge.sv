// Simulation-only packing/host bridge around the bus-fault physical boundary.
// It also models the external memory system's address decode: a read of the
// reserved unmapped window [FAULT_BASE, FAULT_BASE+4 KiB) is answered with a
// bus error (data still from the backing store). No answers or golden data.
// The DUT includes actual command/memory adapters and mapped SRAMs. No answers,
// opcodes, software results, or memory contents are generated in this bridge.
module student_mini_gpu_fault_bridge (
    input wire clk, reset,
    output wire mem_req_valid [2], mem_req_rw [2],
    output wire [63:0] mem_req_byteen [2],
    output wire [25:0] mem_req_addr [2],
    output wire [511:0] mem_req_data [2],
    output wire [9:0] mem_req_tag [2],
    input wire mem_req_ready [2], mem_rsp_valid [2],
    input wire [511:0] mem_rsp_data [2],
    input wire [9:0] mem_rsp_tag [2],
    output wire mem_rsp_ready [2],
    input wire dcr_req_valid, dcr_req_rw,
    input wire [11:0] dcr_req_addr,
    input wire [31:0] dcr_req_data,
    output wire dcr_rsp_valid,
    output wire [31:0] dcr_rsp_data,
    input wire start,
    output wire busy
);
  wire [0:1] req_valid, req_rw, req_ready, rsp_valid, rsp_ready;
  wire [127:0] req_byteen;
  wire [51:0] req_addr;
  wire [1023:0] req_data, rsp_data;
  wire [19:0] req_tag, rsp_tag;
  // Byte 0xE0000000 = 64-byte line 0x3800000; 4 KiB = 64 lines.
  localparam [25:0] FAULT_LINE = 26'h3800000;
  reg [1023:0] fault_tag [2];
  wire [0:1] rsp_error;
  wire cmd_ready, host_rsp_valid, host_rsp_error;
  wire [31:0] host_rsp_data;
  wire cmd_valid = start || dcr_req_valid;
  wire [1:0] cmd_kind = start ? 2'd2 : (dcr_req_rw ? 2'd0 : 2'd1);
  reg read_pending;
  always @(posedge clk) begin
    if (reset) read_pending <= 1'b0;
    else begin
      if (start && dcr_req_valid) $fatal(1,"ambiguous host command");
      if (cmd_valid && !cmd_ready) $fatal(1,"host ignored physical command backpressure");
      if (host_rsp_valid && host_rsp_error) $fatal(1,"physical host command rejected");
      if (cmd_valid && cmd_ready) read_pending <= cmd_kind == 2'd1;
      else if (host_rsp_valid) read_pending <= 1'b0;
    end
  end
  assign dcr_rsp_valid = host_rsp_valid && read_pending;
  assign dcr_rsp_data = host_rsp_data;
  for (genvar p=0;p<2;p=p+1) begin : fault_decode
    wire fault_req = req_valid[p] && req_ready[p] && !req_rw[p]
        && req_addr[p*26+:26] >= FAULT_LINE && req_addr[p*26+:26] < FAULT_LINE + 26'd64;
    always @(posedge clk) begin
      if (reset) fault_tag[p] <= '0;
      else begin
        if (rsp_valid[p] && rsp_ready[p]) fault_tag[p][rsp_tag[p*10+:10]] <= 1'b0;
        if (fault_req) fault_tag[p][req_tag[p*10+:10]] <= 1'b1;
      end
    end
    assign rsp_error[p] = rsp_valid[p] && fault_tag[p][rsp_tag[p*10+:10]];
  end
  for (genvar p=0;p<2;p=p+1) begin : pack_ports
    assign mem_req_valid[p]=req_valid[p];
    assign mem_req_rw[p]=req_rw[p];
    assign mem_req_byteen[p]=req_byteen[p*64+:64];
    assign mem_req_addr[p]=req_addr[p*26+:26];
    assign mem_req_data[p]=req_data[p*512+:512];
    assign mem_req_tag[p]=req_tag[p*10+:10];
    assign req_ready[p]=mem_req_ready[p];
    assign rsp_valid[p]=mem_rsp_valid[p];
    assign rsp_data[p*512+:512]=mem_rsp_data[p];
    assign rsp_tag[p*10+:10]=mem_rsp_tag[p];
    assign mem_rsp_ready[p]=rsp_ready[p];
  end
  vortex_physical_top dut (
    .clk_i(clk),.rst_ni(~reset),
    .host_cmd_valid_i(cmd_valid),.host_cmd_ready_o(cmd_ready),.host_cmd_kind_i(cmd_kind),
    .host_cmd_addr_i(dcr_req_addr),.host_cmd_data_i(dcr_req_data),
    .host_rsp_valid_o(host_rsp_valid),.host_rsp_ready_i(1'b1),
    .host_rsp_data_o(host_rsp_data),.host_rsp_error_o(host_rsp_error),.busy_o(busy),
    .mem_req_valid_o(req_valid),.mem_req_ready_i(req_ready),.mem_req_rw_o(req_rw),
    .mem_req_byteen_o(req_byteen),.mem_req_addr_o(req_addr),.mem_req_data_o(req_data),.mem_req_tag_o(req_tag),
    .mem_rsp_valid_i(rsp_valid),.mem_rsp_error_i(rsp_error),.mem_rsp_ready_o(rsp_ready),.mem_rsp_data_i(rsp_data),.mem_rsp_tag_i(rsp_tag)
  );
endmodule
