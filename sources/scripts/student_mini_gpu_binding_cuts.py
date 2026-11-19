"""Checked private GPU correctness candidates; no in-place source mutation."""


def hold_idle_read_output(source):
    old='''  reg read_seen_q;

  always @(posedge clk) begin
    if (reset) read_seen_q <= 1'b0;
    else if (read) read_seen_q <= 1'b1;
  end
  assign rdata = (reset || !read_seen_q) ? {DATAW{1'b0}} : macro_rdata;'''
    new='''  reg read_seen_q, read_live_q;
  reg [DATAW-1:0] held_data_q;

  // Real OpenRAM invalidates dout during idle clocks. Capture the previous
  // valid word before that invalidation; enabled reads retain their latency.
  always @(posedge clk) begin
    if (reset) begin
      read_seen_q <= 1'b0;
      read_live_q <= 1'b0;
      held_data_q <= {DATAW{1'b0}};
    end else begin
      read_live_q <= read;
      if (read) read_seen_q <= 1'b1;
      if (read_live_q) held_data_q <= macro_rdata;
    end
  end
  assign rdata = (reset || !read_seen_q) ? {DATAW{1'b0}} :
      (read_live_q ? macro_rdata : held_data_q);'''
    count=source.count(old)
    if count not in (1,2):raise ValueError('unknown generated RAM holding seam')
    return source.replace(old,new)


def retained_transactions(shape,seed):
    from scripts.run_student_mini_gpu_memory_witness import transactions
    rows=[];held=0
    for original in transactions(shape,seed):
        row=dict(original)
        if row['golden_hex'] is not None:held=int(row['golden_hex'],16)
        row.update(index=len(rows),golden_hex=f'{held:x}')
        rows.append(row)
        if row['read'] and not row['reset']:
            for _ in range(2):
                idle=dict(row,index=len(rows),label='idle-retention',read=0,write=0,mask=0)
                rows.append(idle)
    return rows
