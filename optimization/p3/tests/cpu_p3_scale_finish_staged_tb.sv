module cpu_p3_scale_finish_staged_tb;
    logic clk = 0;
    logic reset = 1;
    logic input_valid;
    logic input_negative;
    logic [55:0] input_product;
    logic signed [5:0] input_shift;
    logic output_valid;
    logic signed [15:0] output_result;
    integer cycle = 0;
    integer sent = 0;
    integer received = 0;
    integer seed = 32'h50334631;
    logic signed [15:0] expected [0:4095];

    cpu_p3_scale_finish_pipe dut(.*);
    always #5 clk = ~clk;

    function automatic signed [15:0] reference(
        input negative,
        input [55:0] product,
        input signed [5:0] shift
    );
        reg [63:0] scaled, quotient, remainder, mask, half;
        integer s;
        begin
            if (shift >= 0) begin
                scaled = {8'd0, product} << shift;
            end else begin
                s = -shift;
                quotient = {8'd0, product} >> s;
                mask = (64'd1 << s) - 1;
                remainder = {8'd0, product} & mask;
                half = 64'd1 << (s - 1);
                scaled = quotient + (remainder > half || (remainder == half && quotient[0]));
            end
            if (negative)
                reference = scaled >= 32768 ? -16'sd32768 : -$signed(scaled[15:0]);
            else
                reference = scaled >= 32767 ? 16'sd32767 : $signed(scaled[15:0]);
        end
    endfunction

    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (output_valid) begin
            if (output_result !== expected[received]) begin
                $display("P3_STAGED_FINISH_FAIL index=%0d got=%0d expected=%0d",
                         received, output_result, expected[received]);
                $fatal(1);
            end
            received <= received + 1;
        end
        if (!reset && input_valid) begin
            expected[sent] <= reference(input_negative, input_product, input_shift);
            sent <= sent + 1;
        end
    end

    initial begin
        input_valid = 0;
        input_negative = 0;
        input_product = 0;
        input_shift = -6'sd1;
        repeat (3) @(negedge clk);
        reset = 0;
        repeat (2048) begin
            @(negedge clk);
            input_valid = $urandom(seed) & 1;
            input_negative = $urandom(seed) & 1;
            input_product = {$urandom(seed), $urandom(seed)};
            input_shift = -28 + ($urandom(seed) % 33);
        end
        @(negedge clk); input_valid = 0;
        repeat (5) @(negedge clk);
        if (received != sent) begin
            $display("P3_STAGED_FINISH_DRAIN_FAIL sent=%0d received=%0d", sent, received);
            $fatal(1);
        end
        reset = 1;
        @(negedge clk); reset = 0;
        repeat (4) @(negedge clk);
        if (output_valid) $fatal(1, "P3_STAGED_FINISH_RESET_FAIL");
        $display("P3_STAGED_FINISH_PASS sent=%0d cycles=%0d latency=3", sent, cycle);
        $finish;
    end
endmodule
