`include "VX_define.vh"

module p3_gpu_fault_wrapper import VX_gpu_pkg::*; (
    `SCOPE_IO_DECL
    input wire clk, reset,
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
    input wire dcr_req_valid, dcr_req_rw,
    input wire [VX_DCR_ADDR_WIDTH-1:0] dcr_req_addr,
    input wire [VX_DCR_DATA_WIDTH-1:0] dcr_req_data,
    output wire dcr_rsp_valid,
    output wire [VX_DCR_DATA_WIDTH-1:0] dcr_rsp_data,
    input wire start,
    output wire busy
);
    localparam integer PENDING = 16;
    wire req_valid [VX_MEM_PORTS], req_rw [VX_MEM_PORTS];
    wire [VX_MEM_BYTEEN_WIDTH-1:0] req_byteen [VX_MEM_PORTS];
    wire [VX_MEM_ADDR_WIDTH-1:0] req_addr [VX_MEM_PORTS];
    wire [VX_MEM_DATA_WIDTH-1:0] req_data [VX_MEM_PORTS];
    wire [VX_MEM_TAG_WIDTH-1:0] req_tag [VX_MEM_PORTS];
    wire req_ready [VX_MEM_PORTS], rsp_valid [VX_MEM_PORTS];
    wire [VX_MEM_DATA_WIDTH-1:0] rsp_data [VX_MEM_PORTS];
    wire [VX_MEM_TAG_WIDTH-1:0] rsp_tag [VX_MEM_PORTS];
    wire rsp_ready [VX_MEM_PORTS];
    wire [VX_MEM_PORTS-1:0] fault;
    wire core_dcr_valid;
    wire [VX_DCR_DATA_WIDTH-1:0] core_dcr_data;
    wire status_read = dcr_req_valid && !dcr_req_rw && (&dcr_req_addr);
    reg status_pending, status_valid;
    reg [VX_DCR_DATA_WIDTH-1:0] status_data;
    assign dcr_rsp_valid = status_valid || core_dcr_valid;
    assign dcr_rsp_data = status_valid ? status_data : core_dcr_data;

    // The native DCR seam has no ready signal. Preserve its timing and intercept
    // only the reserved read; response-hold qualification needs a separate seam.
    always @(posedge clk) begin
        if (reset) begin
            status_pending <= 0;
            status_valid <= 0;
            status_data <= 0;
        end else begin
            status_pending <= status_read;
            status_valid <= status_pending;
            if (status_read) begin
                status_data <= {{(VX_DCR_DATA_WIDTH-2){1'b0}}, busy, |fault};
                $display("P3_FAULT_STATUS busy=%0d fault=%0d", busy, |fault);
            end
            assert (!(status_valid && core_dcr_valid)) else $fatal(1, "DCR response collision");
        end
    end

    `SCOPE_IO_SWITCH (1);
    Vortex core (
        `SCOPE_IO_BIND (0)
        .clk(clk), .reset(reset),
        .mem_req_valid(req_valid), .mem_req_rw(req_rw),
        .mem_req_byteen(req_byteen), .mem_req_addr(req_addr),
        .mem_req_data(req_data), .mem_req_tag(req_tag), .mem_req_ready(req_ready),
        .mem_rsp_valid(rsp_valid), .mem_rsp_data(rsp_data),
        .mem_rsp_tag(rsp_tag), .mem_rsp_ready(rsp_ready),
        .dcr_req_valid(dcr_req_valid && !status_read), .dcr_req_rw(dcr_req_rw),
        .dcr_req_addr(dcr_req_addr), .dcr_req_data(dcr_req_data),
        .dcr_rsp_valid(core_dcr_valid), .dcr_rsp_data(core_dcr_data),
        .start(start), .busy(busy)
    );

    for (genvar p = 0; p < VX_MEM_PORTS; ++p) begin : g_port
        reg [PENDING-1:0] pending;
        reg [VX_MEM_TAG_WIDTH-1:0] tags [PENDING];
        integer response_slot, free_slot, duplicate_slot;
        reg response_error;
        wire [63:0] byte_addr = 64'(mem_req_addr[p]) << $clog2(VX_MEM_DATA_WIDTH/8);
        wire fault_read = mem_req_valid[p] && mem_req_ready[p] && !mem_req_rw[p]
            && byte_addr >= 64'he0000000 && byte_addr < 64'he0001000;
        wire response_accept = mem_rsp_valid[p] && mem_rsp_ready[p];
        reg [31:0] accepted_fault_requests, accepted_fault_responses;

        always_comb begin
            response_slot = -1;
            free_slot = -1;
            duplicate_slot = -1;
            for (integer n = 0; n < PENDING; ++n) begin
                if (pending[n] && tags[n] == mem_rsp_tag[p]) response_slot = n;
                if (!pending[n] || (response_accept && tags[n] == mem_rsp_tag[p])) free_slot = n;
                if (pending[n] && tags[n] == mem_req_tag[p]
                    && !(response_accept && tags[n] == mem_rsp_tag[p])) duplicate_slot = n;
            end
            response_error = response_slot >= 0;
        end

        always @(posedge clk) begin
            if (reset) begin
                pending <= 0;
                accepted_fault_requests <= 0;
                accepted_fault_responses <= 0;
                for (integer n = 0; n < PENDING; ++n) tags[n] <= 0;
            end else begin
                if (response_accept && response_error) begin
                    pending[response_slot] <= 0;
                    accepted_fault_responses <= accepted_fault_responses + 1;
                    $display("P3_FAULT_RESPONSE port=%0d tag=%h count=%0d", p,
                        mem_rsp_tag[p], accepted_fault_responses + 1);
                end
                if (fault_read) begin
                    assert (free_slot >= 0 && duplicate_slot < 0)
                        else $fatal(1, "Fault pending table overflow or duplicate tag");
                    pending[free_slot] <= 1;
                    tags[free_slot] <= mem_req_tag[p];
                    accepted_fault_requests <= accepted_fault_requests + 1;
                    $display("P3_FAULT_REQUEST port=%0d addr=%h tag=%h count=%0d", p,
                        byte_addr, mem_req_tag[p], accepted_fault_requests + 1);
                end
                if (start) assert (pending == 0) else $fatal(1, "Launch with pending fault read");
            end
        end

        gpu_fault_memory_adapter #(
            .ADDR_WIDTH(VX_MEM_ADDR_WIDTH), .DATA_WIDTH(VX_MEM_DATA_WIDTH),
            .TAG_WIDTH(VX_MEM_TAG_WIDTH)
        ) adapter (
            .clk_i(clk), .rst_ni(!reset), .clear_fault_i(start), .bus_fault_o(fault[p]),
            .vx_req_valid_i(req_valid[p]), .vx_req_ready_o(req_ready[p]),
            .vx_req_rw_i(req_rw[p]), .vx_req_byteen_i(req_byteen[p]),
            .vx_req_addr_i(req_addr[p]), .vx_req_data_i(req_data[p]), .vx_req_tag_i(req_tag[p]),
            .vx_rsp_valid_o(rsp_valid[p]), .vx_rsp_ready_i(rsp_ready[p]),
            .vx_rsp_data_o(rsp_data[p]), .vx_rsp_tag_o(rsp_tag[p]),
            .mem_req_valid_o(mem_req_valid[p]), .mem_req_ready_i(mem_req_ready[p]),
            .mem_req_rw_o(mem_req_rw[p]), .mem_req_byteen_o(mem_req_byteen[p]),
            .mem_req_addr_o(mem_req_addr[p]), .mem_req_data_o(mem_req_data[p]),
            .mem_req_tag_o(mem_req_tag[p]), .mem_rsp_valid_i(mem_rsp_valid[p]),
            .mem_rsp_error_i(response_error), .mem_rsp_ready_o(mem_rsp_ready[p]),
            .mem_rsp_data_i(mem_rsp_data[p]), .mem_rsp_tag_i(mem_rsp_tag[p])
        );
    end
endmodule
