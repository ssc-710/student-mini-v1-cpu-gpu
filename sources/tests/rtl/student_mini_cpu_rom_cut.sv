`timescale 1ns/1ps
module bench;
 reg sys_clk=0;
 reg [29:0] build_soc_coursesimsoc_coursesimsoc_ram_bus_adr=0;
 wire [31:0] original_data,cut_data;
 always #5 sys_clk=~sys_clk;
 original a(.sys_clk,.build_soc_coursesimsoc_coursesimsoc_ram_bus_adr,
   .build_soc_coursesimsoc_coursesimsoc_dat_r(original_data));
 cut b(.sys_clk,.build_soc_coursesimsoc_coursesimsoc_ram_bus_adr,
   .build_soc_coursesimsoc_coursesimsoc_dat_r(cut_data));
 integer address,seed,state,index;
 reg [29:0] saved_address;
 reg [31:0] saved_data;
 task check;
 begin
  @(posedge sys_clk); #1;
  if(original_data!==cut_data) $fatal(1,"ROM_CUT_MISMATCH address=%0d original=%h cut=%h",build_soc_coursesimsoc_coursesimsoc_ram_bus_adr,original_data,cut_data);
  $display("ROM_ROW address=%0d golden=%h actual=%h",build_soc_coursesimsoc_coursesimsoc_ram_bus_adr,original_data,cut_data);
  saved_address=build_soc_coursesimsoc_coursesimsoc_ram_bus_adr;saved_data=cut_data;
  build_soc_coursesimsoc_coursesimsoc_ram_bus_adr=saved_address^512;
  #1;
  if(original_data!==saved_data || cut_data!==saved_data) $fatal(1,"ROM_OUTPUT_NOT_REGISTERED");
  build_soc_coursesimsoc_coursesimsoc_ram_bus_adr=saved_address;
  @(negedge sys_clk);
 end
 endtask
 initial begin
  // Includes all defined words, partial last bank and out-of-range X semantics.
  for(address=0;address<32768;address=address+1) begin
   build_soc_coursesimsoc_coursesimsoc_ram_bus_adr=address;check;
  end
  for(seed=1;seed<=10;seed=seed+1) begin
   state=seed;
   for(index=0;index<512;index=index+1) begin
    build_soc_coursesimsoc_coursesimsoc_ram_bus_adr=$random(state)&32767;check;
   end
  end
  $display("CPU_ROM_CUT_PASS addresses=32768 random_seeds=10 random_rows=5120 latency=1");$finish;
 end
endmodule
