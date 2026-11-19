"""Extend each of the three native-port fixed read-valid pipelines by one edge.

The DFI output register shifts every external read command by one edge. The
generated crossbar does not derive these valid signals from PHY rddata_valid;
its three independent five-register chains must therefore become six-register
chains. Data, arbitration, reset and all input/output geometry stay unchanged.
"""
import re

PREFIX='builder_litedramcore_new_master_rdata_valid'
TERMINALS=(4,9,14)


def project(source):
    if source.count(' dfi_output_boundary (')!=1 or 'dfi_read_valid_alignment' in source:
        raise ValueError('unaligned common DFI output boundary required')
    for terminal in TERMINALS:
        name=PREFIX+str(terminal);early='mini_dfi_early_valid'+str(terminal)
        declaration=f"  reg {name} = 1'h0;"
        update=f"  always @(posedge sys_clk)\n    if (asic_reset_i) {name} <= 1'h0;\n    else {name} <= {PREFIX}{terminal-1};"
        if source.count(declaration)!=1 or source.count(update)!=1:
            raise ValueError('exact terminal fixed-latency read-valid seam changed')
        source=source.replace(declaration,f"  wire {name};\n  reg {early} = 1'h0;")
        source=source.replace(update,update.replace(name,early))
    # Insert into the same top, ahead of its first endmodule. No other module
    # or consumer is rewritten, including the SRAM data return itself.
    index=source.index('endmodule')
    instance='''  student_mini_cpu_dfi_output_cut #(.WIDTH(3), .RESET_VALUE(3'b000)) dfi_read_valid_alignment (
    .clk(sys_clk), .reset(asic_reset_i),
    .request({mini_dfi_early_valid4,mini_dfi_early_valid9,mini_dfi_early_valid14}),
    .response({builder_litedramcore_new_master_rdata_valid4,builder_litedramcore_new_master_rdata_valid9,builder_litedramcore_new_master_rdata_valid14}));
'''
    return source[:index]+instance+source[index:]


def formal_bench():
    return '''module contract(input wire clk, reset, input wire [2:0] request);
    wire [2:0] response;
    student_mini_cpu_dfi_output_cut #(.WIDTH(3),.RESET_VALUE(3'b000)) dut
      (.clk(clk),.reset(reset),.request(request),.response(response));
    reg seen=0;
    always @(posedge clk) begin
      seen <= 1;
      if(seen) begin
        if($past(reset)) assert(response == 0);
        else assert(response == $past(request));
      end
    end
endmodule
'''
