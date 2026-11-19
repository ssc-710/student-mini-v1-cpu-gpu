module cpu_p3_scale_apply_tb;
    logic clk = 0;
    logic reset = 1;
    logic input_valid;
    logic signed [31:0] input_value;
    logic [23:0] input_significand;
    logic signed [5:0] input_shift;
    logic output_valid;
    logic signed [15:0] output_result;
    integer cycle = 0;
    integer sent = 0;
    integer received = 0;
    integer seed = 32'h50335343;
    logic signed [15:0] expected [0:4095];

    cpu_p3_scale_apply_pipe dut(.*);
    always #5 clk = ~clk;

    function automatic signed [15:0] reference(
        input signed [31:0] value,
        input [23:0] significand,
        input signed [5:0] shift
    );
        reg [31:0] magnitude;
        reg [63:0] product, scaled, quotient, remainder, mask, half;
        integer s;
        begin
            magnitude = value[31] ? (32'd0 - value) : value;
            product = magnitude * significand;
            if (shift >= 0) begin
                scaled = product << shift;
            end else begin
                s = -shift;
                quotient = product >> s;
                mask = (64'd1 << s) - 1;
                remainder = product & mask;
                half = 64'd1 << (s - 1);
                scaled = quotient + (remainder > half || (remainder == half && quotient[0]));
            end
            if (value[31])
                reference = scaled >= 32768 ? -16'sd32768 : -$signed(scaled[15:0]);
            else
                reference = scaled >= 32767 ? 16'sd32767 : $signed(scaled[15:0]);
        end
    endfunction

    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (output_valid) begin
            if (output_result !== expected[received]) begin
                $display("P3_SCALE_PIPE_FAIL index=%0d got=%0d expected=%0d",
                         received, output_result, expected[received]);
                $fatal(1);
            end
            received <= received + 1;
        end
        if (!reset && input_valid) begin
            expected[sent] <= reference(input_value, input_significand, input_shift);
            sent <= sent + 1;
        end
    end

    initial begin
        input_valid = 0;
        input_value = 0;
        input_significand = 24'h800000;
        input_shift = -6'sd1;
        repeat (3) @(negedge clk);
        reset = 0;
        repeat (2048) begin
            @(negedge clk);
            input_valid = $urandom(seed) & 1;
            input_value = $urandom(seed);
            input_significand = 24'h800000 | ($urandom(seed) & 24'h7fffff);
            input_shift = -28 + ($urandom(seed) % 33);
        end
        @(negedge clk); input_valid = 0;
        repeat (4) @(negedge clk);
        if (received != sent) begin
            $display("P3_SCALE_PIPE_DRAIN_FAIL sent=%0d received=%0d", sent, received);
            $fatal(1);
        end
        reset = 1;
        @(negedge clk); reset = 0;
        repeat (3) @(negedge clk);
        if (output_valid) $fatal(1, "P3_SCALE_PIPE_RESET_FAIL");
        $display("P3_SCALE_PIPE_PASS sent=%0d cycles=%0d latency=2", sent, cycle);
        $finish;
    end
endmodule
