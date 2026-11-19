// Three-enabled-edge signed 33x33 multiplier using 11-bit limbs.
// Stage 1 limits multiplier width; stage 2 is a carry-save tree; stage 3 is one CPA.
module p3_signed33_radix11_mul3 (
    input wire clk,
    input wire enable,
    input wire [32:0] dataa,
    input wire [32:0] datab,
    output wire [65:0] result
);
    wire signed [11:0] a0 = $signed({1'b0, dataa[10:0]});
    wire signed [11:0] a1 = $signed({1'b0, dataa[21:11]});
    wire signed [10:0] a2 = $signed(dataa[32:22]);
    wire signed [11:0] b0 = $signed({1'b0, datab[10:0]});
    wire signed [11:0] b1 = $signed({1'b0, datab[21:11]});
    wire signed [10:0] b2 = $signed(datab[32:22]);

    reg signed [23:0] p00, p01, p02, p10, p11, p12, p20, p21, p22;
    wire [65:0] r00 = {{42{p00[23]}}, p00};
    wire [65:0] r01 = {{42{p01[23]}}, p01} << 11;
    wire [65:0] r02 = {{42{p02[23]}}, p02} << 22;
    wire [65:0] r10 = {{42{p10[23]}}, p10} << 11;
    wire [65:0] r11 = {{42{p11[23]}}, p11} << 22;
    wire [65:0] r12 = {{42{p12[23]}}, p12} << 33;
    wire [65:0] r20 = {{42{p20[23]}}, p20} << 22;
    wire [65:0] r21 = {{42{p21[23]}}, p21} << 33;
    wire [65:0] r22 = {{42{p22[23]}}, p22} << 44;

`define P3_CSA(name,x,y,z) \
    wire [65:0] name``_s = (x) ^ (y) ^ (z); \
    wire [65:0] name``_c = (((x) & (y)) | ((x) & (z)) | ((y) & (z))) << 1
    `P3_CSA(c0, r00, r01, r02);
    `P3_CSA(c1, r10, r11, r12);
    `P3_CSA(c2, r20, r21, r22);
    `P3_CSA(c3, c0_s, c0_c, c1_s);
    `P3_CSA(c4, c1_c, c2_s, c2_c);
    `P3_CSA(c5, c3_s, c3_c, c4_s);
    `P3_CSA(c6, c5_s, c5_c, c4_c);
`undef P3_CSA

    reg [65:0] carry_save_sum, carry_save_carry;
    reg [65:0] product;
    always @(posedge clk) begin
        if (enable) begin
            p00 <= a0 * b0;
            p01 <= a0 * b1;
            p02 <= a0 * b2;
            p10 <= a1 * b0;
            p11 <= a1 * b1;
            p12 <= a1 * b2;
            p20 <= a2 * b0;
            p21 <= a2 * b1;
            p22 <= a2 * b2;
            carry_save_sum <= c6_s;
            carry_save_carry <= c6_c;
            product <= carry_save_sum + carry_save_carry;
        end
    end
    assign result = product;
endmodule
