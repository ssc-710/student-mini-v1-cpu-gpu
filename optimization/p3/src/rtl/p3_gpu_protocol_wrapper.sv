`include "VX_define.vh"

// MINI31/32 protocol seam.  This wrapper deliberately keeps the Vortex
// native memory ports unchanged and adds a real host command/response
// interface around the native, pulse-only DCR interface.  The status read is
// consumed by p3_gpu_fault_wrapper; all other DCR reads preserve the
// host supplied tag in dcr_req_data (the tag is not silently replaced by 0).
// This file is an independent preparation artifact; it is not used by the
// previously executed fault overlay.
module p3_gpu_protocol_wrapper import VX_gpu_pkg::*; (
    `SCOPE_IO_DECL
    input wire clk, reset,
    input wire [31:0] protocol_seed,
    input wire [7:0] protocol_stall_threshold,
    input wire host_cmd_valid,
    output wire host_cmd_ready,
    input wire [1:0] host_cmd_kind,
    input wire [VX_DCR_ADDR_WIDTH-1:0] host_cmd_addr,
    input wire [VX_DCR_DATA_WIDTH-1:0] host_cmd_data,
    output wire host_rsp_valid,
    input wire host_rsp_ready,
    output wire [VX_DCR_DATA_WIDTH-1:0] host_rsp_data,
    output wire host_rsp_error,
    output wire mem_req_valid [VX_MEM_PORTS],
    output wire mem_req_rw [VX_MEM_PORTS],
    output wire [VX_MEM_BYTEEN_WIDTH-1:0] mem_req_byteen [VX_MEM_PORTS],
    output wire [VX_MEM_ADDR_WIDTH-1:0] mem_req_addr [VX_MEM_PORTS],
    output wire [VX_MEM_DATA_WIDTH-1:0] mem_req_data [VX_MEM_PORTS],
    output wire [VX_MEM_TAG_WIDTH-1:0] mem_req_tag [VX_MEM_PORTS],
    input wire mem_req_ready [VX_MEM_PORTS],
    input wire mem_rsp_valid [VX_MEM_PORTS],
    input wire [VX_MEM_DATA_WIDTH-1:0] mem_rsp_data [VX_MEM_PORTS],
    input wire [VX_MEM_TAG_WIDTH-1:0] mem_rsp_tag [VX_MEM_PORTS],
    output wire mem_rsp_ready [VX_MEM_PORTS],
    output wire busy
);
    wire dcr_req_valid, dcr_req_rw;
    wire [VX_DCR_ADDR_WIDTH-1:0] dcr_req_addr;
    wire [VX_DCR_DATA_WIDTH-1:0] dcr_req_data;
    wire dcr_rsp_valid;
    wire [VX_DCR_DATA_WIDTH-1:0] dcr_rsp_data;
    wire start;
    wire req_valid [VX_MEM_PORTS], req_rw [VX_MEM_PORTS], req_ready [VX_MEM_PORTS];
    wire [VX_MEM_BYTEEN_WIDTH-1:0] req_byteen [VX_MEM_PORTS];
    wire [VX_MEM_ADDR_WIDTH-1:0] req_addr [VX_MEM_PORTS];
    wire [VX_MEM_DATA_WIDTH-1:0] req_data [VX_MEM_PORTS];
    wire [VX_MEM_TAG_WIDTH-1:0] req_tag [VX_MEM_PORTS];
    wire rsp_valid [VX_MEM_PORTS], rsp_ready [VX_MEM_PORTS];
    wire [VX_MEM_DATA_WIDTH-1:0] rsp_data [VX_MEM_PORTS];
    wire [VX_MEM_TAG_WIDTH-1:0] rsp_tag [VX_MEM_PORTS];
    p3_gpu_command_adapter #(
        .ADDR_WIDTH(VX_DCR_ADDR_WIDTH), .DATA_WIDTH(VX_DCR_DATA_WIDTH)
    ) command_adapter (
        .clk_i(clk), .rst_ni(!reset),
        .host_cmd_valid_i(host_cmd_valid), .host_cmd_ready_o(host_cmd_ready),
        .host_cmd_kind_i(host_cmd_kind), .host_cmd_addr_i(host_cmd_addr),
        .host_cmd_data_i(host_cmd_data), .host_rsp_valid_o(host_rsp_valid),
        .host_rsp_ready_i(host_rsp_ready), .host_rsp_data_o(host_rsp_data),
        .host_rsp_error_o(host_rsp_error), .dcr_req_valid_o(dcr_req_valid),
        .dcr_req_rw_o(dcr_req_rw), .dcr_req_addr_o(dcr_req_addr),
        .dcr_req_data_o(dcr_req_data), .dcr_rsp_valid_i(dcr_rsp_valid),
        .dcr_rsp_data_i(dcr_rsp_data), .start_o(start), .busy_i(busy)
    );

    p3_gpu_fault_wrapper core (
        `SCOPE_IO_BIND (0)
        .clk(clk), .reset(reset),
        .mem_req_valid(req_valid), .mem_req_rw(req_rw),
        .mem_req_byteen(req_byteen), .mem_req_addr(req_addr),
        .mem_req_data(req_data), .mem_req_tag(req_tag),
        .mem_req_ready(req_ready), .mem_rsp_valid(rsp_valid),
        .mem_rsp_data(rsp_data), .mem_rsp_tag(rsp_tag),
        .mem_rsp_ready(rsp_ready), .dcr_req_valid(dcr_req_valid),
        .dcr_req_rw(dcr_req_rw), .dcr_req_addr(dcr_req_addr),
        .dcr_req_data(dcr_req_data), .dcr_rsp_valid(dcr_rsp_valid),
        .dcr_rsp_data(dcr_rsp_data), .start(start), .busy(busy)
    );

    for (genvar p=0; p<VX_MEM_PORTS; ++p) begin : g_gate
        localparam integer REQ_WIDTH=1+VX_MEM_BYTEEN_WIDTH+VX_MEM_ADDR_WIDTH+VX_MEM_DATA_WIDTH+VX_MEM_TAG_WIDTH;
        localparam integer RSP_WIDTH=VX_MEM_DATA_WIDTH+VX_MEM_TAG_WIDTH;
        wire [63:0] req_stalls, req_accepted, rsp_stalls, rsp_accepted;
        p3_gpu_memory_gate #(.WIDTH(REQ_WIDTH)) request_gate (
            .clk(clk), .reset(reset), .seed(protocol_seed ^ (32'h9e3779b9 * (2*p+1))),
            .stall_threshold(protocol_stall_threshold), .in_valid(req_valid[p]), .in_ready(req_ready[p]),
            .in_data({req_rw[p],req_byteen[p],req_addr[p],req_data[p],req_tag[p]}),
            .out_valid(mem_req_valid[p]), .out_ready(mem_req_ready[p]),
            .out_data({mem_req_rw[p],mem_req_byteen[p],mem_req_addr[p],mem_req_data[p],mem_req_tag[p]}),
            .stall_cycles(req_stalls), .accepted(req_accepted));
        p3_gpu_memory_gate #(.WIDTH(RSP_WIDTH)) response_gate (
            .clk(clk), .reset(reset), .seed(protocol_seed ^ (32'h9e3779b9 * (2*p+2))),
            .stall_threshold(protocol_stall_threshold), .in_valid(mem_rsp_valid[p]), .in_ready(mem_rsp_ready[p]),
            .in_data({mem_rsp_data[p],mem_rsp_tag[p]}), .out_valid(rsp_valid[p]), .out_ready(rsp_ready[p]),
            .out_data({rsp_data[p],rsp_tag[p]}), .stall_cycles(rsp_stalls), .accepted(rsp_accepted));
    end

    // A response must remain bit-stable while the host deliberately holds
    // ready low (MINI32).  This catches accidental pulse-to-level regressions.
    reg [VX_DCR_DATA_WIDTH-1:0] held_data;
    reg held_error, was_held;
    always @(posedge clk) begin
        if (reset) begin
            held_data <= '0;
            held_error <= 1'b0;
            was_held <= 1'b0;
        end else if (host_rsp_valid && !host_rsp_ready) begin
            if (was_held && (held_data != host_rsp_data || held_error != host_rsp_error))
                $fatal(1, "MINI32 response changed while stalled");
            held_data <= host_rsp_data;
            held_error <= host_rsp_error;
            was_held <= 1'b1;
        end else begin
            if (was_held && (!host_rsp_valid || held_data != host_rsp_data || held_error != host_rsp_error))
                $fatal(1, "MINI32 held response lost before acceptance");
            was_held <= 1'b0;
            held_data <= '0;
            held_error <= 1'b0;
        end
    end
endmodule
