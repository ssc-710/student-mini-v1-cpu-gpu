module student_mini_gpu_multiplier_cut (
    input wire clk, enable,
    input wire [32:0] dataa, datab,
    output wire [65:0] original_result, actual_result
);
    VX_multiplier #(.A_WIDTH(33), .B_WIDTH(33), .R_WIDTH(66), .SIGNED(1), .LATENCY(3)) original (
        .clk(clk), .enable(enable), .dataa(dataa), .datab(datab), .result(original_result)
    );
    VX_multiplier_candidate #(.A_WIDTH(33), .B_WIDTH(33), .R_WIDTH(66), .SIGNED(1), .LATENCY(3)) candidate (
        .clk(clk), .enable(enable), .dataa(dataa), .datab(datab), .result(actual_result)
    );
endmodule
