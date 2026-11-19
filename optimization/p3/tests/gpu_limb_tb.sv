module gpu_limb_tb(input clk,input enable,input [32:0] dataa,datab,
    output [65:0] candidate,baseline);
    p3_signed33_limb_mul3 c(clk,enable,dataa,datab,candidate);
    student_mini_signed33_mul3 b(clk,enable,dataa,datab,baseline);
endmodule
