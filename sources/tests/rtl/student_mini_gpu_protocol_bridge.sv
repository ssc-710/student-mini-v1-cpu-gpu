// Simulation-only protocol bridge around the bus-fault physical boundary
// (student-mini MINI-31/32/33 qualification).  Same packing, fault decode
// and DUT as student_mini_gpu_fault_bridge.sv, plus host-side protocol
// stimulus selected per run through student_mini_protocol_param():
//   0: backpressure probability in 1/256 units (memory request and response
//      handshakes stalled independently per port from a seeded xorshift32)
//   1: backpressure seed
//   2: host response hold cycles (host_rsp_ready_i low for N cycles per response)
// Host commands enter a FIFO so a stalled command port never drops a command.
// Every handshake the DUT drives is checked to stay stable until accepted.
// Cumulative counters reach the host model through student_mini_protocol_report().
// No answers, opcodes, software results, or memory contents are generated here.
module student_mini_gpu_fault_bridge (
    input wire clk, reset,
    output wire mem_req_valid [2], mem_req_rw [2],
    output wire [63:0] mem_req_byteen [2],
    output wire [25:0] mem_req_addr [2],
    output wire [511:0] mem_req_data [2],
    output wire [9:0] mem_req_tag [2],
    input wire mem_req_ready [2], mem_rsp_valid [2],
    input wire [511:0] mem_rsp_data [2],
    input wire [9:0] mem_rsp_tag [2],
    output wire mem_rsp_ready [2],
    input wire dcr_req_valid, dcr_req_rw,
    input wire [11:0] dcr_req_addr,
    input wire [31:0] dcr_req_data,
    output wire dcr_rsp_valid,
    output wire [31:0] dcr_rsp_data,
    input wire start,
    output wire busy
);
  import "DPI-C" function int student_mini_protocol_param(input int which);
  wire [0:1] req_valid, req_rw, req_ready, rsp_valid, rsp_ready;
  wire [127:0] req_byteen;
  wire [51:0] req_addr;
  wire [1023:0] req_data, rsp_data;
  wire [19:0] req_tag, rsp_tag;
  localparam [25:0] FAULT_LINE = 26'h3800000;
  reg [1023:0] fault_tag [2];
  wire [0:1] rsp_error;
  wire cmd_ready, host_rsp_valid, host_rsp_error;
  wire [31:0] host_rsp_data;
  // ---- protocol parameters
  int bp_prob, bp_seed, hold_cycles;
  initial begin
    bp_prob = student_mini_protocol_param(0);
    bp_seed = student_mini_protocol_param(1);
    hold_cycles = student_mini_protocol_param(2);
  end
  // ---- seeded stall generator: 4 independent decisions per cycle
  reg [31:0] lfsr;
  wire [31:0] lfsr_next = lfsr ^ (lfsr << 13) ^ ((lfsr ^ (lfsr << 13)) >> 17) ^
                          ((lfsr ^ (lfsr << 13) ^ ((lfsr ^ (lfsr << 13)) >> 17)) << 5);
  wire [3:0] stall;
  for (genvar i = 0; i < 4; i = i + 1) begin : stall_bits
    assign stall[i] = bp_prob != 0 && {24'd0, lfsr[8*i+:8]} < bp_prob;
  end
  always @(posedge clk) begin
    if (reset) lfsr <= (bp_seed == 0) ? 32'h1 : bp_seed[31:0] ^ 32'h9e3779b9;
    else lfsr <= (lfsr_next == 0) ? 32'h1 : lfsr_next;
  end
  // ---- host command FIFO (start = kind 2, read = 1, write = 0)
  localparam int DEPTH = 64;
  reg [45:0] fifo [DEPTH];
  reg [6:0] head, tail;
  wire fifo_empty = head == tail;
  // Occupancies at their own width (an int'() cast would evaluate the subtraction at
  // 32 bits and go negative once a pointer wraps).
  wire [6:0] fifo_count = tail - head;
  wire [4:0] kinds_count;
  wire [45:0] fifo_top = fifo[head[5:0]];
  wire cmd_valid = !fifo_empty;
  wire [1:0] cmd_kind = fifo_top[45:44];
  wire [11:0] cmd_addr = fifo_top[43:32];
  wire [31:0] cmd_data = fifo_top[31:0];
  wire host_in = start || dcr_req_valid;
  wire [1:0] host_kind = start ? 2'd2 : (dcr_req_rw ? 2'd0 : 2'd1);
  // ---- host response hold
  int held;
  wire host_rsp_ready = hold_cycles == 0 || held >= hold_cycles;
  // Every accepted command receives exactly one response, in order; a held
  // response may still be outstanding when the next command is accepted, so
  // the kind of each accepted command is queued and paired with its response.
  reg [1:0] kinds [16];
  reg [4:0] khead, ktail;
  assign kinds_count = ktail - khead;
  wire oldest_is_read = khead != ktail && kinds[khead[3:0]] == 2'd1;
  int stalled_req_cycles, stalled_rsp_cycles, held_rsp_cycles, violations, commands, responses, fifo_peak;
  always @(posedge clk) begin
    if (reset) begin
      head <= 0; tail <= 0; khead <= 0; ktail <= 0; held <= 0;
    end else begin
      if (start && dcr_req_valid) $fatal(1, "ambiguous host command");
      if (host_in) begin
        if (tail - head == 7'(DEPTH)) $fatal(1, "host command FIFO overflow");
        fifo[tail[5:0]] <= {host_kind, dcr_req_addr, dcr_req_data};
        tail <= tail + 1;
      end
      if (cmd_valid && cmd_ready) begin
        head <= head + 1;
        if (ktail - khead == 5'd16) $fatal(1, "outstanding command queue overflow");
        kinds[ktail[3:0]] <= cmd_kind;
        ktail <= ktail + 1;
        commands <= commands + 1;
      end
      if (host_rsp_valid && host_rsp_ready) begin
        if (khead == ktail) $fatal(1, "host response without an outstanding command");
        khead <= khead + 1;
      end
      if (host_rsp_valid && host_rsp_error) $fatal(1, "physical host command rejected");
      if (host_rsp_valid && !host_rsp_ready) begin held <= held + 1; held_rsp_cycles <= held_rsp_cycles + 1; end
      else held <= 0;
      if (host_rsp_valid && host_rsp_ready) responses <= responses + 1;
      if (int'(fifo_count) > fifo_peak) fifo_peak <= int'(fifo_count);
    end
  end
  assign dcr_rsp_valid = host_rsp_valid && host_rsp_ready && oldest_is_read;
  assign dcr_rsp_data = host_rsp_data;
  // ---- memory handshakes with seeded stalls
  wire [0:1] req_valid_host, req_ready_dut, rsp_valid_dut, rsp_ready_host;
  for (genvar p = 0; p < 2; p = p + 1) begin : gate
    assign req_ready_dut[p] = mem_req_ready[p] && !stall[p];
    assign req_valid_host[p] = req_valid[p] && !stall[p];
    assign rsp_valid_dut[p] = mem_rsp_valid[p] && !stall[2 + p];
    assign rsp_ready_host[p] = rsp_ready[p] && !stall[2 + p];
  end
  for (genvar p = 0; p < 2; p = p + 1) begin : fault_decode
    wire fault_req = req_valid[p] && req_ready_dut[p] && !req_rw[p]
        && req_addr[p*26+:26] >= FAULT_LINE && req_addr[p*26+:26] < FAULT_LINE + 26'd64;
    always @(posedge clk) begin
      if (reset) fault_tag[p] <= '0;
      else begin
        if (rsp_valid_dut[p] && rsp_ready[p]) fault_tag[p][rsp_tag[p*10+:10]] <= 1'b0;
        if (fault_req) fault_tag[p][req_tag[p*10+:10]] <= 1'b1;
      end
    end
    assign rsp_error[p] = rsp_valid_dut[p] && fault_tag[p][rsp_tag[p*10+:10]];
  end
  // ---- stability of every DUT-driven handshake while not accepted
  reg [0:1] req_wait_q;
  reg [1+64+26+512+10-1:0] req_q [2];
  reg rsp_wait_q;
  reg [32:0] rsp_q;
  always @(posedge clk) begin
    if (reset) begin req_wait_q <= '0; rsp_wait_q <= 1'b0; end
    else begin
      for (int p = 0; p < 2; p++) begin
        if (req_wait_q[p] && (!req_valid[p] || {req_rw[p], req_byteen[p*64+:64], req_addr[p*26+:26], req_data[p*512+:512], req_tag[p*10+:10]} != req_q[p]))
          violations <= violations + 1;
        req_wait_q[p] <= req_valid[p] && !req_ready_dut[p];
        req_q[p] <= {req_rw[p], req_byteen[p*64+:64], req_addr[p*26+:26], req_data[p*512+:512], req_tag[p*10+:10]};
        // A stalled cycle is a DUT request withheld from the host side.  (The host-side
        // arbiter raises ready only for a presented request, so mem_req_ready is low
        // whenever the request is withheld and cannot qualify this count.)
        if (req_valid[p] && stall[p]) stalled_req_cycles <= stalled_req_cycles + 1;
        if (mem_rsp_valid[p] && stall[2 + p]) stalled_rsp_cycles <= stalled_rsp_cycles + 1;
      end
      if (rsp_wait_q && (!host_rsp_valid || {host_rsp_error, host_rsp_data} != rsp_q)) violations <= violations + 1;
      rsp_wait_q <= host_rsp_valid && !host_rsp_ready;
      rsp_q <= {host_rsp_error, host_rsp_data};
    end
  end
  initial begin
    stalled_req_cycles = 0; stalled_rsp_cycles = 0; held_rsp_cycles = 0; violations = 0;
    commands = 0; responses = 0; fifo_peak = 0;
  end
  // Cumulative counters are handed to the host model one cycle after every host
  // response (DPI call that only stores integers); the host prints them after each
  // launch.  No $display here: the runtime keeps ticking the model during process
  // teardown, after the simulator's formatting buffers are gone.
  import "DPI-C" function void student_mini_protocol_report(input int bp_prob, input int bp_seed, input int hold,
      input int stalled_req, input int stalled_rsp, input int held_rsp, input int violations, input int commands,
      input int responses, input int fifo_peak);
  // Outstanding host commands (queued + accepted but not yet answered) for the host model,
  // which waits for zero after each command like the original synchronous host.
  import "DPI-C" function void student_mini_protocol_pending(input int outstanding);
  always @(posedge clk) student_mini_protocol_pending(int'(fifo_count) + int'(kinds_count) + int'(host_in));
  reg print_q;
  always @(posedge clk) begin
    print_q <= !reset && host_rsp_valid && host_rsp_ready;
    if (print_q) student_mini_protocol_report(bp_prob, bp_seed, hold_cycles, stalled_req_cycles, stalled_rsp_cycles,
                                              held_rsp_cycles, violations, commands, responses, fifo_peak);
  end
  for (genvar p = 0; p < 2; p = p + 1) begin : pack_ports
    assign mem_req_valid[p] = req_valid_host[p];
    assign mem_req_rw[p] = req_rw[p];
    assign mem_req_byteen[p] = req_byteen[p*64+:64];
    assign mem_req_addr[p] = req_addr[p*26+:26];
    assign mem_req_data[p] = req_data[p*512+:512];
    assign mem_req_tag[p] = req_tag[p*10+:10];
    assign req_ready[p] = req_ready_dut[p];
    assign rsp_valid[p] = rsp_valid_dut[p];
    assign rsp_data[p*512+:512] = mem_rsp_data[p];
    assign rsp_tag[p*10+:10] = mem_rsp_tag[p];
    assign mem_rsp_ready[p] = rsp_ready_host[p];
  end
  vortex_physical_top dut (
    .clk_i(clk), .rst_ni(~reset),
    .host_cmd_valid_i(cmd_valid), .host_cmd_ready_o(cmd_ready), .host_cmd_kind_i(cmd_kind),
    .host_cmd_addr_i(cmd_addr), .host_cmd_data_i(cmd_data),
    .host_rsp_valid_o(host_rsp_valid), .host_rsp_ready_i(host_rsp_ready),
    .host_rsp_data_o(host_rsp_data), .host_rsp_error_o(host_rsp_error), .busy_o(busy),
    .mem_req_valid_o(req_valid), .mem_req_ready_i(req_ready), .mem_req_rw_o(req_rw),
    .mem_req_byteen_o(req_byteen), .mem_req_addr_o(req_addr), .mem_req_data_o(req_data), .mem_req_tag_o(req_tag),
    .mem_rsp_valid_i(rsp_valid), .mem_rsp_error_i(rsp_error), .mem_rsp_ready_o(rsp_ready), .mem_rsp_data_i(rsp_data), .mem_rsp_tag_i(rsp_tag)
  );
endmodule
