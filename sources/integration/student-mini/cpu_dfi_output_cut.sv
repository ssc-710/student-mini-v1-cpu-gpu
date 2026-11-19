// One common clock boundary for every DFI command, payload and enable bit.
// This is a latency-changing feasibility candidate, not a qualified baseline.
module student_mini_cpu_dfi_output_cut #(
    parameter integer WIDTH = 169,
    parameter [WIDTH-1:0] RESET_VALUE = 0
) (
    input wire clk, reset,
    input wire [WIDTH-1:0] request,
    output reg [WIDTH-1:0] response
);
    always @(posedge clk) begin
        if (reset) response <= RESET_VALUE;
        else response <= request;
    end
endmodule
