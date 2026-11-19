module p3_signed33_limb_mul3 (
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
    reg [31:0] p00;
    reg signed [32:0] p01, p10;
    reg signed [33:0] p11;
    wire [34:0] mid_a = {{2{p01[32]}},p01};
    wire [34:0] mid_b = {{2{p10[32]}},p10};
    wire [34:0] mid_c = {19'b0,p00[31:16]};
    wire [34:0] mid_sum = mid_a ^ mid_b ^ mid_c;
    wire [34:0] mid_carry = ((mid_a & mid_b) | (mid_a & mid_c) | (mid_b & mid_c)) << 1;
    reg [15:0] low;
    reg signed [34:0] mid;
    reg signed [33:0] high;
    reg [65:0] product;
    wire signed [33:0] upper = high + {{15{mid[34]}},mid[34:16]};
    always @(posedge clk) begin
        if (enable) begin
            p00 <= dataa[15:0] * datab[15:0];
            p01 <= a_low * b_high;
            p10 <= a_high * b_low;
            p11 <= a_high * b_high;
            low <= p00[15:0];
            mid <= mid_sum + mid_carry;
            high <= p11;
            product <= {upper,mid[15:0],low};
        end
    end
    assign result = product;
endmodule
