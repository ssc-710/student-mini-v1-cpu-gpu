// Post-multiply P3 scale path. The VexRiscv MulPlugin supplies product; this
// block deliberately contains no multiplier. Legal shift range is [-28, 4].
module cpu_p3_scale_finish_reduced (
    input  logic               negative,
    input  logic        [55:0] product,
    input  logic signed  [5:0] shift,
    output logic signed [15:0] result
);
    logic [59:0] base;
    logic [26:0] sticky_mask;
    logic        guard_bit;
    logic        sticky_bit;
    logic        round_up;
    logic [59:0] rounded;
    integer right_shift;

    always_comb begin
        base = 60'd0;
        sticky_mask = 27'd0;
        guard_bit = 1'b0;
        sticky_bit = 1'b0;
        right_shift = 0;
        if (shift >= 0) begin
            base = {4'd0, product} << shift;
        end else begin
            right_shift = -shift;
            base = {4'd0, product >> right_shift};
            guard_bit = product[right_shift - 1];
            sticky_mask = (27'd1 << (right_shift - 1)) - 27'd1;
            sticky_bit = |(product[26:0] & sticky_mask);
        end
        round_up = guard_bit && (sticky_bit || base[0]);
        rounded = base + round_up;
        if (negative)
            result = rounded >= 60'd32768 ? -16'sd32768 : -$signed(rounded[15:0]);
        else
            result = rounded >= 60'd32767 ? 16'sd32767 : $signed(rounded[15:0]);
    end
endmodule

// Three-cycle fixed latency, one result per cycle. F0 performs shift and
// guard/sticky extraction; F1 rounds; F2 restores sign and saturates.
module cpu_p3_scale_finish_pipe (
    input  logic               clk,
    input  logic               reset,
    input  logic               input_valid,
    input  logic               input_negative,
    input  logic        [55:0] input_product,
    input  logic signed  [5:0] input_shift,
    output logic               output_valid,
    output logic signed [15:0] output_result
);
    logic [59:0] f0_base_d;
    logic [26:0] f0_sticky_mask_d;
    logic        f0_guard_d;
    logic        f0_sticky_d;
    logic        f0_negative_d;
    integer      f0_right_shift_d;

    logic [59:0] f0_base_q;
    logic        f0_guard_q;
    logic        f0_sticky_q;
    logic        f0_negative_q;
    logic        f0_valid_q;

    logic [59:0] f1_rounded_q;
    logic        f1_negative_q;
    logic        f1_valid_q;

    always_comb begin
        f0_base_d = 60'd0;
        f0_sticky_mask_d = 27'd0;
        f0_guard_d = 1'b0;
        f0_sticky_d = 1'b0;
        f0_negative_d = input_negative;
        f0_right_shift_d = 0;
        if (input_shift >= 0) begin
            f0_base_d = {4'd0, input_product} << input_shift;
        end else begin
            f0_right_shift_d = -input_shift;
            f0_base_d = {4'd0, input_product >> f0_right_shift_d};
            f0_guard_d = input_product[f0_right_shift_d - 1];
            f0_sticky_mask_d = (27'd1 << (f0_right_shift_d - 1)) - 27'd1;
            f0_sticky_d = |(input_product[26:0] & f0_sticky_mask_d);
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            f0_valid_q <= 1'b0;
            f1_valid_q <= 1'b0;
            output_valid <= 1'b0;
            output_result <= 16'sd0;
        end else begin
            f0_valid_q <= input_valid;
            f1_valid_q <= f0_valid_q;
            output_valid <= f1_valid_q;
            if (input_valid) begin
                f0_base_q <= f0_base_d;
                f0_guard_q <= f0_guard_d;
                f0_sticky_q <= f0_sticky_d;
                f0_negative_q <= f0_negative_d;
            end
            if (f0_valid_q) begin
                f1_rounded_q <= f0_base_q
                    + (f0_guard_q && (f0_sticky_q || f0_base_q[0]));
                f1_negative_q <= f0_negative_q;
            end
            if (f1_valid_q) begin
                if (f1_negative_q)
                    output_result <= f1_rounded_q >= 60'd32768
                        ? -16'sd32768 : -$signed(f1_rounded_q[15:0]);
                else
                    output_result <= f1_rounded_q >= 60'd32767
                        ? 16'sd32767 : $signed(f1_rounded_q[15:0]);
            end
        end
    end
endmodule

// Integration-facing variant. A blocked output holds the whole tail so data,
// rd tag and validity remain aligned. Flush cancels every in-flight result.
module cpu_p3_scale_finish_elastic (
    input  logic               clk,
    input  logic               reset,
    input  logic               flush,
    output logic               input_ready,
    input  logic               input_valid,
    input  logic               input_negative,
    input  logic        [55:0] input_product,
    input  logic signed  [5:0] input_shift,
    input  logic         [4:0] input_rd,
    input  logic               output_ready,
    output logic               output_valid,
    output logic signed [15:0] output_result,
    output logic         [4:0] output_rd
);
    logic [59:0] s0_base_d;
    logic [26:0] s0_mask_d;
    logic        s0_guard_d;
    logic        s0_sticky_d;
    integer      s0_right_shift_d;

    logic [59:0] s0_base_q;
    logic        s0_guard_q;
    logic        s0_sticky_q;
    logic        s0_negative_q;
    logic  [4:0] s0_rd_q;
    logic        s0_valid_q;

    logic [59:0] s1_rounded_q;
    logic        s1_negative_q;
    logic  [4:0] s1_rd_q;
    logic        s1_valid_q;

    logic signed [15:0] s2_result_q;
    logic         [4:0] s2_rd_q;
    logic               s2_valid_q;
    logic               blocked;

    always_comb begin
        s0_base_d = 60'd0;
        s0_mask_d = 27'd0;
        s0_guard_d = 1'b0;
        s0_sticky_d = 1'b0;
        s0_right_shift_d = 0;
        if (input_shift >= 0) begin
            s0_base_d = {4'd0, input_product} << input_shift;
        end else begin
            s0_right_shift_d = -input_shift;
            s0_base_d = {4'd0, input_product >> s0_right_shift_d};
            s0_guard_d = input_product[s0_right_shift_d - 1];
            s0_mask_d = (27'd1 << (s0_right_shift_d - 1)) - 27'd1;
            s0_sticky_d = |(input_product[26:0] & s0_mask_d);
        end
    end

    assign blocked = s2_valid_q && !output_ready;
    assign input_ready = !blocked && !flush && !reset;
    assign output_valid = s2_valid_q && !flush && !reset;
    assign output_result = s2_result_q;
    assign output_rd = s2_rd_q;

    always_ff @(posedge clk) begin
        if (reset || flush) begin
            s0_valid_q <= 1'b0;
            s1_valid_q <= 1'b0;
            s2_valid_q <= 1'b0;
            s2_result_q <= 16'sd0;
            s2_rd_q <= 5'd0;
        end else if (!blocked) begin
            s2_valid_q <= s1_valid_q;
            s1_valid_q <= s0_valid_q;
            s0_valid_q <= input_valid;
            if (input_valid) begin
                s0_base_q <= s0_base_d;
                s0_guard_q <= s0_guard_d;
                s0_sticky_q <= s0_sticky_d;
                s0_negative_q <= input_negative;
                s0_rd_q <= input_rd;
            end
            if (s0_valid_q) begin
                s1_rounded_q <= s0_base_q
                    + (s0_guard_q && (s0_sticky_q || s0_base_q[0]));
                s1_negative_q <= s0_negative_q;
                s1_rd_q <= s0_rd_q;
            end
            if (s1_valid_q) begin
                if (s1_negative_q)
                    s2_result_q <= s1_rounded_q >= 60'd32768
                        ? -16'sd32768 : -$signed(s1_rounded_q[15:0]);
                else
                    s2_result_q <= s1_rounded_q >= 60'd32767
                        ? 16'sd32767 : $signed(s1_rounded_q[15:0]);
                s2_rd_q <= s1_rd_q;
            end
        end
    end
endmodule
