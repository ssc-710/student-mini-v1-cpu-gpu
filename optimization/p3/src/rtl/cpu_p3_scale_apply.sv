module cpu_p3_scale_finish (
    input  logic               negative,
    input  logic        [55:0] product,
    input  logic signed  [5:0] shift,
    output logic signed [15:0] result
);
    logic        [63:0] scaled;
    logic        [63:0] quotient;
    logic        [63:0] remainder;
    logic        [63:0] mask;
    logic        [63:0] half;
    logic         round_up;
    integer       right_shift;

    always_comb begin
        scaled = 64'd0;
        quotient = 64'd0;
        remainder = 64'd0;
        mask = 64'd0;
        half = 64'd0;
        round_up = 1'b0;
        right_shift = 0;

        if (shift >= 0) begin
            scaled = {8'd0, product} << shift;
        end else begin
            right_shift = -shift;
            quotient = {8'd0, product} >> right_shift;
            mask = (64'd1 << right_shift) - 64'd1;
            remainder = {8'd0, product} & mask;
            half = 64'd1 << (right_shift - 1);
            round_up = (remainder > half)
                    || ((remainder == half) && quotient[0]);
            scaled = quotient + round_up;
        end

        if (negative)
            result = scaled >= 64'd32768 ? -16'sd32768 : -$signed(scaled[15:0]);
        else
            result = scaled >= 64'd32767 ? 16'sd32767 : $signed(scaled[15:0]);
    end
endmodule

module cpu_p3_scale_apply_comb (
    input  logic signed [31:0] value,
    input  logic        [23:0] significand,
    input  logic signed  [5:0] shift,
    output logic signed [15:0] result
);
    logic [31:0] magnitude;
    logic [55:0] product;

    always_comb begin
        magnitude = value[31] ? (~value[31:0] + 32'd1) : value[31:0];
        product = magnitude * significand;
    end

    cpu_p3_scale_finish finish (
        .negative(value[31]),
        .product(product),
        .shift(shift),
        .result(result)
    );
endmodule

// Fixed two-cycle latency, one operation per cycle. Context encoding is the
// software p3_scale_ctx: a 24-bit significand and a signed shift in [-28, 4].
module cpu_p3_scale_apply_pipe (
    input  logic               clk,
    input  logic               reset,
    input  logic               input_valid,
    input  logic signed [31:0] input_value,
    input  logic        [23:0] input_significand,
    input  logic signed  [5:0] input_shift,
    output logic               output_valid,
    output logic signed [15:0] output_result
);
    logic signed [31:0] value_q;
    logic        [23:0] significand_q;
    logic signed  [5:0] shift_q;
    logic                valid_q;
    logic signed [15:0] result_d;

    cpu_p3_scale_apply_comb comb (
        .value(value_q),
        .significand(significand_q),
        .shift(shift_q),
        .result(result_d)
    );

    always_ff @(posedge clk) begin
        if (reset) begin
            valid_q <= 1'b0;
            output_valid <= 1'b0;
            output_result <= 16'sd0;
        end else begin
            valid_q <= input_valid;
            output_valid <= valid_q;
            if (input_valid) begin
                value_q <= input_value;
                significand_q <= input_significand;
                shift_q <= input_shift;
            end
            if (valid_q)
                output_result <= result_d;
        end
    end
endmodule
