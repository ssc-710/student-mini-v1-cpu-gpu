"""Exact projection of the complete DFI output tuple, never just write data."""
import re
from scripts.export_student_mini_cpu_boundary import PREFIX, DFI_OUTPUTS
from scripts.student_mini_cpu_replay_sources import TOP

WIDTH = sum(DFI_OUTPUTS.values())
IDLE = {name: (2**width-1 if name in ('cas_n','cs_n','ras_n','we_n','act_n','wrdata_mask') else 0)
        for name,width in DFI_OUTPUTS.items()}


def reset_value():
    value=0
    for name,width in DFI_OUTPUTS.items(): value=(value<<width)|IDLE[name]
    return value


def project(source, module):
    if source.count('module '+TOP+'(')!=1 or 'mini_dfi_before_' in source:
        raise ValueError('unique untouched physical top required')
    start=source.index('module '+TOP+'(')
    header_end=source.index(';',start)+1
    end=source.index('endmodule',header_end)
    header=source[start:header_end];body=source[header_end:end]
    declarations=[];incoming=[];outgoing=[]
    for suffix,width in DFI_OUTPUTS.items():
        name=PREFIX+suffix;internal='mini_dfi_before_'+suffix
        span=f'[{width-1}:0] ' if width>1 else ''
        declaration='  output '+span+name+';'
        if body.count(declaration)!=1 or len(re.findall(r'\b'+name+r'\b',header))!=1:
            raise ValueError('DFI output declaration/header differs: '+suffix)
        body=body.replace(declaration,'')
        body=re.sub(r'\b'+name+r'\b',internal,body)
        declarations.extend([declaration,'  wire '+span+name+';'])
        incoming.append(internal);outgoing.append(name)
    if module.count('module student_mini_cpu_dfi_output_cut #(')!=1:
        raise ValueError('unique DFI output register module required')
    instance=(f'\n  student_mini_cpu_dfi_output_cut #(.WIDTH({WIDTH}), '
        f".RESET_VALUE({WIDTH}'h{reset_value():x})) dfi_output_boundary (\n"
        '    .clk(sys_clk), .reset(asic_reset_i),\n'
        '    .request({'+','.join(incoming)+'}),\n'
        '    .response({'+','.join(outgoing)+'}));\n')
    return source[:header_end]+'\n'+'\n'.join(declarations)+body+instance+source[end:]+'\n'+module


def formal_bench():
    return f'''module contract(input wire clk, reset, input wire [{WIDTH-1}:0] request);
    wire [{WIDTH-1}:0] response;
    student_mini_cpu_dfi_output_cut #(.RESET_VALUE({WIDTH}'h{reset_value():x})) dut
        (.clk(clk),.reset(reset),.request(request),.response(response));
    reg valid=0;
    always @(posedge clk) begin
        valid <= 1;
        if(valid) begin
            if($past(reset)) assert(response == {WIDTH}'h{reset_value():x});
            else assert(response == $past(request));
        end
    end
endmodule
'''


def mutants(module):
    changes={'ignore-reset':('if (reset)','if (1\'b0)'),
             'corrupt-data':('response <= request;',"response <= request ^ 169'h100000;"),
             'lost-enable':('response <= request;',"response <= request & ~169'h8;"),
             'extra-cycle':('else response <= request;', 'else response <= previous;')}
    results={}
    for name,(old,new) in changes.items():
        if module.count(old)!=1:raise ValueError('DFI mutation seam changed')
        value=module.replace(old,new)
        if name=='extra-cycle':value=value.replace('    always @(posedge clk) begin',
            '    reg [WIDTH-1:0] previous;\n    always @(posedge clk) begin\n        previous <= request;')
        results[name]=value
    return results
