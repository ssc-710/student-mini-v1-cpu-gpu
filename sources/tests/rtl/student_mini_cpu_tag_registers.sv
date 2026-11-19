`timescale 1ns/1ps
module bench;
  reg clk=0, rd=0;
  reg [9:0] wa=0, ra=0;
  reg [31:0] wd=0;
  reg [3:0] wm=0;
  wire [31:0] original, actual;
  reg [21:0] golden [0:511];
  reg [21:0] held;
  integer seed, address, step, rows=0;
  reg [31:0] rng;
  always #5 clk=~clk;
  student_mini_cpu_sram_32x1024 old(clk,wa,ra,wd,wm,rd,original);
  student_mini_cpu_cache_tag_registers fixed(clk,wa,ra,wd,wm,rd,actual);
  task random_next;
    begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5); end
  endtask
  task run_row;
    reg [21:0] value;
    begin
      if (rd) held=golden[ra];
      value=golden[wa];
      if (wm[0]) value[7:0]=wd[7:0];
      if (wm[1]) value[15:8]=wd[15:8];
      if (wm[2]) value[21:16]=wd[21:16];
      golden[wa]=value;
      @(posedge clk); @(negedge clk); #4;
      if (actual[21:0] !== held || original[21:0] !== held)
        $fatal(1,"tag mismatch seed=%0d row=%0d expected=%h old=%h actual=%h",seed,rows,held,original[21:0],actual[21:0]);
      $display("TAG_ROW seed=%0d index=%0d rd=%0d wa=%0d ra=%0d mask=%h data=%h golden=%h old=%h actual=%h",seed,rows,rd,wa,ra,wm,wd,held,original[21:0],actual[21:0]);
      rows=rows+1;
    end
  endtask
  initial begin
    #1;
    for(seed=1;seed<=10;seed=seed+1) begin
      rng=seed;
      // Full writes first; held state intentionally survives between seeds.
      for(address=0;address<512;address=address+1) begin
        random_next; rd=0;wm=7;wa=address;ra=0;wd=rng;run_row;
      end
      for(address=0;address<512;address=address+1) begin
        rd=1;wm=0;ra=address;wa=0;run_row;
      end
      for(step=0;step<512;step=step+1) begin
        random_next;wa=rng[8:0];random_next;ra=rng[8:0];
        if(wa==ra) ra=(ra+1)%512;
        random_next;wm=rng[2:0];rd=(step%3!=0);random_next;wd=rng;run_row;
      end
    end
    $display("CPU_TAG_REGISTERS_PASS seeds=10 rows=15360 words=512 bits=22");$finish;
  end
endmodule
