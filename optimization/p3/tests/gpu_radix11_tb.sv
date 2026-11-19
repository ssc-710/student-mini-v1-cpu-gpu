module tb;
  reg clk=0, enable=0; reg [32:0] a=0,b=0; wire [65:0] result;
  reg [65:0] expected[0:2]; integer head=0, count=0, i; reg [31:0] state=32'h13579bdf;
  p3_signed33_radix11_mul3 dut(clk,enable,a,b,result);
  task tick; begin #1; clk=1; #1; clk=0; #1; end endtask
  task enabled_edge; reg signed [32:0] sa,sb; begin
    sa=a; sb=b; expected[(head+count)%3]=sa*sb; if(count<3) count=count+1;
    enable=1; tick(); enable=0;
    if(count==3) begin
      if(result!==expected[head]) $fatal(1,"mismatch i=%0d got=%h expected=%h",i,result,expected[head]);
      head=(head+1)%3; count=count-1;
    end
  end endtask
  initial begin
    repeat(4) tick();
    for(i=0;i<20000;i=i+1) begin
      state=state^(state<<13);state=state^(state>>17);state=state^(state<<5);a={state,state[0]};
      state=state^(state<<13);state=state^(state>>17);state=state^(state<<5);b={state,state[1]};
      enabled_edge();
      if((state&3)==0) begin reg [65:0] held; held=result; repeat((state>>4)&7) tick();
        if(result!==held) $fatal(1,"stall changed result"); end
    end
    a=0;b=0;repeat(3) enabled_edge();
    $display("P3_RADIX11_RTL_STALL_PASS transactions=20003");$finish;
  end
endmodule
