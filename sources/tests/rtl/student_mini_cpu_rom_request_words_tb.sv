`timescale 1ns/1ps
module bench;
  reg clk=0, reset=1, cyc=0, stb=0;
  reg [14:0] address=0, wanted=0;
  wire ack;
  wire [31:0] data, golden;
  actual_rom actual(.*);
  golden_rom oracle(.address(wanted),.data(golden));
  always #5 clk=~clk;
  integer seed=0,index;
  reg [31:0] prng;
  task read_word(input [14:0] target);
    begin
      @(negedge clk); wanted=target;address=target;cyc=1;stb=1;
      @(posedge clk);#1;if(ack) $fatal(1,"early response");
      @(posedge clk);#1;
      if(!ack || data!==golden) $fatal(1,"ROM data mismatch address=%0d golden=%h actual=%h",target,golden,data);
      $display("ROM_REQUEST_ROW seed=%0d address=%0d golden=%h actual=%h",seed,target,golden,data);
      @(posedge clk);#1;if(ack) $fatal(1,"duplicate response");
    end
  endtask
  initial begin
    repeat(2) @(posedge clk);
    @(negedge clk);reset=0;
    for(index=0;index<32768;index=index+1) read_word(index[14:0]);
    for(seed=1;seed<=10;seed=seed+1) begin
      prng=seed;
      for(index=0;index<512;index=index+1) begin
        prng=prng*1664525+1013904223;read_word(prng[14:0]);
      end
    end
    $display("ROM_REQUEST_WORDS_PASS addresses=32768 seeds=10 random_rows=5120");
    $finish;
  end
endmodule
