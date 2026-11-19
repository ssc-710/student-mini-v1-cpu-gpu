module cpu_p3_scale_finish_elastic_tb;
    logic clk = 0;
    logic reset = 1;
    logic flush;
    logic input_ready;
    logic input_valid;
    logic input_negative;
    logic [55:0] input_product;
    logic signed [5:0] input_shift;
    logic [4:0] input_rd;
    logic output_ready;
    logic output_valid;
    logic signed [15:0] output_result;
    logic [4:0] output_rd;
    logic signed [15:0] expected_result [0:8191];
    logic [4:0] expected_rd [0:8191];
    logic held;
    logic signed [15:0] held_result;
    logic [4:0] held_rd;
    integer head = 0;
    integer tail = 0;
    integer accepted = 0;
    integer retired = 0;
    integer flushed = 0;
    integer cycle = 0;
    integer seed = 32'h5033454c;

    cpu_p3_scale_finish_elastic dut(.*);
    always #5 clk = ~clk;

    function automatic signed [15:0] reference(
        input negative,
        input [55:0] product,
        input signed [5:0] shift
    );
        reg [63:0] scaled, quotient, remainder, mask, half;
        integer s;
        begin
            if (shift >= 0) scaled = {8'd0, product} << shift;
            else begin
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
        cycle = cycle + 1;
        if (reset || flush) begin
            flushed = flushed + (tail - head);
            head = tail;
            held = 0;
        end else begin
            if (held && (!output_valid || output_result !== held_result || output_rd !== held_rd))
                $fatal(1, "P3_ELASTIC_HOLD_FAIL cycle=%0d", cycle);
            if (output_valid && output_ready) begin
                if (head == tail) $fatal(1, "P3_ELASTIC_GHOST_OUTPUT cycle=%0d", cycle);
                if (output_result !== expected_result[head] || output_rd !== expected_rd[head])
                    $fatal(1, "P3_ELASTIC_DATA_FAIL index=%0d", head);
                head = head + 1;
                retired = retired + 1;
            end
            if (input_valid && input_ready) begin
                expected_result[tail] = reference(input_negative, input_product, input_shift);
                expected_rd[tail] = input_rd;
                tail = tail + 1;
                accepted = accepted + 1;
            end
            held = output_valid && !output_ready;
            if (held) begin
                held_result = output_result;
                held_rd = output_rd;
            end
        end
    end

    initial begin
        flush = 0;
        input_valid = 0;
        input_negative = 0;
        input_product = 0;
        input_shift = -1;
        input_rd = 0;
        output_ready = 0;
        held = 0;
        repeat (3) @(negedge clk);
        reset = 0;
        // Directed cancellation at the architectural output boundary.
        @(negedge clk); input_valid = 1; output_ready = 0; input_rd = 5'd7;
        input_product = 56'h123456789abcd; input_shift = -6'sd7;
        @(negedge clk); input_valid = 0;
        while (!output_valid) @(negedge clk);
        flush = 1; output_ready = 1;
        #1 if (output_valid) $fatal(1, "P3_ELASTIC_FLUSH_READY_VISIBLE");
        @(negedge clk); flush = 0;

        @(negedge clk); input_valid = 1; output_ready = 0; input_rd = 5'd9;
        input_product = 56'h0fedcba9876543; input_shift = -6'sd11;
        @(negedge clk); input_valid = 0;
        while (!output_valid) @(negedge clk);
        flush = 1; output_ready = 0;
        #1 if (output_valid) $fatal(1, "P3_ELASTIC_FLUSH_STALL_VISIBLE");
        @(negedge clk); flush = 0;

        // Reset an in-flight transaction, not just an empty pipeline.
        @(negedge clk); input_valid = 1; output_ready = 0; input_rd = 5'd11;
        input_product = 56'h11112222333344; input_shift = -6'sd3;
        @(negedge clk); input_valid = 0;
        reset = 1;
        #1 if (output_valid || input_ready) $fatal(1, "P3_ELASTIC_RESET_VISIBLE");
        @(negedge clk); reset = 0;

        // Fill all stages, then hold both a compliant producer and output for
        // 80 cycles. The pending input and exposed result must remain stable.
        output_ready = 0;
        repeat (4) begin
            @(negedge clk);
            input_valid = 1;
            input_product = input_product + 56'h01020304050607;
            input_shift = -6'sd9;
            input_rd = input_rd + 1'b1;
        end
        while (input_ready) @(negedge clk);
        begin : long_stall
            reg [55:0] producer_product;
            reg signed [5:0] producer_shift;
            reg [4:0] producer_rd;
            reg signed [15:0] stalled_result;
            reg [4:0] stalled_rd;
            producer_product = input_product;
            producer_shift = input_shift;
            producer_rd = input_rd;
            stalled_result = output_result;
            stalled_rd = output_rd;
            repeat (80) begin
                @(negedge clk);
                if (input_ready) $fatal(1, "P3_ELASTIC_LONG_STALL_READY");
                if (!output_valid || output_result !== stalled_result || output_rd !== stalled_rd)
                    $fatal(1, "P3_ELASTIC_LONG_STALL_OUTPUT");
                if (input_product !== producer_product || input_shift !== producer_shift || input_rd !== producer_rd)
                    $fatal(1, "P3_ELASTIC_PRODUCER_HOLD");
            end
        end
        @(negedge clk); output_ready = 1;
        while (!input_ready) @(negedge clk);
        input_valid = 0;

        repeat (4096) begin
            @(negedge clk);
            flush = (($urandom(seed) & 8'hff) == 8'h5a);
            input_valid = $urandom(seed) & 1;
            output_ready = ($urandom(seed) & 3) != 0;
            input_negative = $urandom(seed) & 1;
            input_product = {$urandom(seed), $urandom(seed)};
            input_shift = -28 + ($urandom(seed) % 33);
            input_rd = $urandom(seed);
        end
        @(negedge clk);
        flush = 0;
        input_valid = 0;
        output_ready = 1;
        while (head != tail || output_valid) @(negedge clk);
        reset = 1;
        @(negedge clk);
        reset = 0;
        repeat (4) @(negedge clk);
        if (output_valid) $fatal(1, "P3_ELASTIC_RESET_GHOST");
        if (accepted != retired + flushed)
            $fatal(1, "P3_ELASTIC_ACCOUNTING accepted=%0d retired=%0d flushed=%0d",
                   accepted, retired, flushed);
        $display("P3_ELASTIC_FINISH_PASS accepted=%0d retired=%0d flushed=%0d cycles=%0d",
                 accepted, retired, flushed, cycle);
        $finish;
    end
endmodule
