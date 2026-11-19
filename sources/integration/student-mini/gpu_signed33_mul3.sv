// Timing-only candidate for the pinned RV32 Vortex signed 33-bit multiplier.
// Exactly three ENABLED rising edges, like VX_multiplier LATENCY=3.
// No reset port: the upstream unit masks validity independently.
module student_mini_signed33_mul3 (
    input wire clk,
    input wire enable,
    input wire [32:0] dataa,
    input wire [32:0] datab,
    output wire [65:0] result
);
    wire signed [16:0] a_low = $signed({1'b0, dataa[15:0]});
    wire signed [16:0] b_low = $signed({1'b0, datab[15:0]});
    wire signed [16:0] a_high = $signed(dataa[32:16]);
    wire signed [16:0] b_high = $signed(datab[32:16]);
    reg signed [33:0] p00, p01, p10, p11;
    reg signed [49:0] row_low, row_high;
    reg signed [65:0] product;
    always @(posedge clk) begin
        if (enable) begin
            p00 <= a_low * b_low;
            p01 <= a_low * b_high;
            p10 <= a_high * b_low;
            p11 <= a_high * b_high;
            row_low <= {{16{p00[33]}}, p00} + {p01, 16'b0};
            row_high <= {{16{p10[33]}}, p10} + {p11, 16'b0};
            product <= {{16{row_low[49]}}, row_low} + {row_high, 16'b0};
        end
    end
    assign result = product;
endmodule
