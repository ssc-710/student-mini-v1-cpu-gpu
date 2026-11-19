module cpu_p3_vex_blocking_adapter_tb;
  logic clk = 0, reset = 1, flush = 0;
  always #5 clk = ~clk;

  logic decode_valid;
  logic [31:0] decode_instruction;
  logic signed [31:0] decode_rs1;
  logic [31:0] decode_rs2;
  logic [4:0] decode_rd;
  logic decode_claim, decode_legal, decode_ready, core_halt;
  logic ordinary_mul_busy;
  logic mul_req_valid, mul_req_ready;
  logic [31:0] mul_req_a, mul_req_b;
  logic [7:0] mul_req_tag;
  logic mul_rsp_valid;
  logic [63:0] mul_rsp_product;
  logic mul_rsp_owner_p3;
  logic [7:0] mul_rsp_tag;
  logic wb_valid, wb_ready;
  logic [4:0] wb_rd;
  logic signed [31:0] wb_data;
  logic protocol_error;

  cpu_p3_vex_blocking_adapter dut(.*);

  localparam logic [31:0] P3_INSN = {7'b0101010, 5'd0, 5'd0,
                                      3'b000, 5'd0, 7'b0001011};
  integer accepted = 0, retired = 0, flushed = 0, cycle = 0;
  integer rsp_delay = -1;
  logic [63:0] pending_product;
  logic [7:0] pending_tag;
  logic pending_mul;
  logic stale_pending;
  logic [63:0] stale_product;
  logic [7:0] stale_tag;
  logic stale_injected;
  logic arm_wrong_owner;
  logic wrong_owner_pending;
  logic wrong_owner_injected;
  integer request_count = 0;
  integer random_seed = 32'h50335eed;
  logic signed [31:0] expected_data [0:1023];
  logic [4:0] expected_rd [0:1023];
  integer head = 0, tail = 0;

  function automatic signed [15:0] reference_finish(
      input logic negative,
      input logic [55:0] product,
      input integer shift);
    reg [63:0] q, rem, mask, half, scaled;
    integer rshift;
    begin
      q=0; rem=0; mask=0; half=0; scaled=0; rshift=0;
      if (shift >= 0) scaled = {8'd0,product} << shift;
      else begin
        rshift = -shift;
        q = {8'd0,product} >> rshift;
        mask = (64'd1 << rshift) - 1;
        rem = {8'd0,product} & mask;
        half = 64'd1 << (rshift-1);
        scaled = q + ((rem > half) || ((rem == half) && q[0]));
      end
      if (negative)
        reference_finish = scaled >= 32768 ? -16'sd32768
                                           : -$signed(scaled[15:0]);
      else
        reference_finish = scaled >= 32767 ? 16'sd32767
                                           : $signed(scaled[15:0]);
    end
  endfunction

  always @(posedge clk) begin
    cycle <= cycle + 1;
    if (cycle > 10000)
      $fatal(1,"watchdog state=%0d tag=%0d pending=%0d delay=%0d stale=%0d wrong_owner=%0d head=%0d tail=%0d wb_valid=%0d wb_ready=%0d finish=%0d/%0d/%0d out=%0d",
        dut.state_q,dut.active_tag_q,pending_mul,rsp_delay,stale_pending,
        wrong_owner_pending,head,tail,wb_valid,wb_ready,
        dut.finish.s0_valid_q,dut.finish.s1_valid_q,dut.finish.s2_valid_q,
        dut.finish_output_valid);
    mul_rsp_valid <= 0;
    if (mul_req_valid && mul_req_ready) begin
      if (pending_mul) $fatal(1,"overlapping multiply request");
      if (mul_req_tag !== request_count[7:0])
        $fatal(1,"non-monotonic request tag got=%0d expected=%0d",
          mul_req_tag,request_count[7:0]);
      request_count <= request_count + 1;
      pending_product <= mul_req_a * mul_req_b;
      pending_tag <= mul_req_tag;
      rsp_delay <= (stale_pending || arm_wrong_owner) ? 3 : cycle % 4;
      pending_mul <= 1;
      if (arm_wrong_owner) begin
        wrong_owner_pending <= 1;
        arm_wrong_owner <= 0;
      end
    end else if (wrong_owner_pending && pending_mul && rsp_delay == 2) begin
      mul_rsp_product <= pending_product;
      mul_rsp_owner_p3 <= 0;
      mul_rsp_tag <= pending_tag;
      mul_rsp_valid <= 1;
      wrong_owner_pending <= 0;
      wrong_owner_injected <= 1;
    end else if (stale_pending && pending_mul && rsp_delay == 1) begin
      // A killed pre-flush result may arrive after the new request. Its epoch
      // must prevent it from being consumed as the new transaction.
      mul_rsp_product <= stale_product;
      mul_rsp_owner_p3 <= 1;
      mul_rsp_tag <= stale_tag;
      mul_rsp_valid <= 1;
      if (stale_tag == pending_tag)
        $fatal(1,"stale tag aliases active tag");
      stale_pending <= 0;
      stale_injected <= 1;
    end else if (pending_mul && rsp_delay == 0) begin
      mul_rsp_product <= pending_product;
      mul_rsp_owner_p3 <= 1;
      mul_rsp_tag <= pending_tag;
      mul_rsp_valid <= 1;
      pending_mul <= 0;
    end else if (pending_mul) rsp_delay <= rsp_delay - 1;

    if (flush && (head < tail)) begin
      flushed <= flushed + (tail-head);
      head <= tail;
      if (pending_mul && !stale_pending) begin
        stale_pending <= 1;
        stale_product <= pending_product;
        stale_tag <= pending_tag;
      end
      pending_mul <= 0;
      rsp_delay <= -1;
    end
    if (wb_valid && wb_ready) begin
      if (head >= tail) $fatal(1,"ghost writeback");
      if (wb_rd !== expected_rd[head] || wb_data !== expected_data[head])
        $fatal(1,"writeback mismatch idx=%0d rd=%0d/%0d data=%0d/%0d",
          head,wb_rd,expected_rd[head],wb_data,expected_data[head]);
      head <= head + 1;
      retired <= retired + 1;
    end
  end

  task automatic issue(input integer value, input integer sig,
                       input integer shift, input integer rd);
    reg [31:0] magnitude;
    reg [55:0] product;
    reg signed [15:0] result;
    begin
      @(negedge clk);
      while (!decode_ready) @(negedge clk);
      decode_instruction=P3_INSN; decode_rs1=value;
      decode_rs2={2'b00,shift[5:0],sig[23:0]}; decode_rd=rd;
      decode_valid=1;
      @(posedge clk);
      @(negedge clk);
      if (!core_halt) $fatal(1,"accepted custom op did not halt core");
      decode_valid=0;
      magnitude = value < 0 ? -value : value;
      product = magnitude * sig[23:0];
      result = reference_finish(value < 0,product,shift);
      expected_data[tail] = {{16{result[15]}},result};
      expected_rd[tail] = rd;
      tail = tail + 1;
      accepted = accepted + 1;
    end
  endtask

  task automatic flush_now;
    begin
      @(negedge clk); flush=1;
      @(posedge clk);
      @(negedge clk); flush=0;
    end
  endtask

  initial begin
    decode_valid=0; decode_instruction=0; decode_rs1=0; decode_rs2=0;
    decode_rd=0; ordinary_mul_busy=0; mul_req_ready=1; mul_rsp_valid=0;
    mul_rsp_product=0; mul_rsp_owner_p3=0; mul_rsp_tag=0;
    wb_ready=1; pending_mul=0;
    pending_tag=0; stale_pending=0; stale_product=0; stale_tag=0;
    stale_injected=0; arm_wrong_owner=0; wrong_owner_pending=0;
    wrong_owner_injected=0;
    repeat(3) @(posedge clk); @(negedge clk); reset=0;
    random_seed = $urandom(random_seed);

    // Decode and reserved-context gates must not consume an instruction.
    decode_instruction=P3_INSN; decode_rs2=32'hc0000001; decode_valid=1;
    #1; if (!decode_claim || decode_legal) $fatal(1,"reserved bits legal");
    @(posedge clk); decode_valid=0;
    decode_instruction=32'h00000033; #1;
    if (decode_claim || decode_legal) $fatal(1,"ordinary MUL claimed");
    decode_instruction={7'b0000001,5'd0,5'd0,3'b001,5'd0,7'b0001011}; #1;
    if (decode_claim || decode_legal) $fatal(1,"other custom-0 op claimed");

    ordinary_mul_busy=1; decode_instruction=P3_INSN; decode_rs2=0; #1;
    if (decode_ready) $fatal(1,"accepted while ordinary MUL busy");
    ordinary_mul_busy=0;

    arm_wrong_owner=1;
    issue(1234567,24'h812345,-7,3);
    while (head != tail) begin
      @(negedge clk);
      wb_ready = (cycle % 5 != 0);
      @(posedge clk);
    end
    if (!wrong_owner_injected) $fatal(1,"wrong-owner response not injected");
    @(negedge clk); wb_ready=1;

    // Tag 0 retired normally. Kill tag 1 and tag 2; while tag 3 is active,
    // inject the retained tag 1 response and require it to be ignored.
    issue(-7654321,24'h654321,-20,7);
    repeat(1) @(posedge clk); flush_now();
    issue(-2222222,24'h456789,-9,8);
    repeat(1) @(posedge clk); flush_now();
    issue(3141592,24'h765432,-11,9);
    while (head != tail) @(posedge clk);
    if (!stale_injected) $fatal(1,"stale response was not injected");
    repeat(4) @(posedge clk);
    if (wb_valid) $fatal(1,"writeback after request-phase flush");

    for (integer i=0;i<300;i=i+1) begin
      issue($random,$urandom_range(1,24'hffffff),
            $urandom_range(0,32)-28,$urandom_range(1,31));
      if ((i % 17)==5) begin
        repeat($urandom_range(0,5)) @(posedge clk);
        flush_now();
      end else begin
        while (head != tail) begin
          @(negedge clk);
          wb_ready=(cycle%7 != 2 && cycle%7 != 3);
          @(posedge clk);
        end
        @(negedge clk); wb_ready=1;
      end
    end
    repeat(20) @(posedge clk);
    if (head != tail) $fatal(1,"unretired expected result");
    if (accepted != retired + flushed)
      $fatal(1,"conservation failed accepted=%0d retired=%0d flushed=%0d",
        accepted,retired,flushed);
    if (protocol_error) $fatal(1,"unexpected protocol error");
    $display("CPU_P3_VEX_BLOCKING_ADAPTER_PASS accepted=%0d retired=%0d flushed=%0d cycles=%0d",
      accepted,retired,flushed,cycle);
    $finish;
  end
endmodule
