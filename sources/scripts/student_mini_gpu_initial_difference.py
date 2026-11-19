"""Exact unsigned DIV initialization: one extended subtraction, no latency change."""
from scripts.student_mini_gpu_divsqrt_cut import once
from scripts.student_mini_gpu_sign_cut import project as sign_project


def project(source):
    source = sign_project(source)
    return once(source, '''    wire                 i_q_int0_div = (i_sig_a >= i_sig_b);
    wire [SUPER_SIG-1:0] i_pre_diff   = i_sig_a - (i_q_int0_div ? i_sig_b : {SUPER_SIG{1'b0}});''', '''    // Carry/borrow and difference share the same full-width subtraction.
    // All SUPER_SIG bits and the unsigned borrow bit are retained.
    wire [SUPER_SIG:0] i_full_diff = {1'b0, i_sig_a} - {1'b0, i_sig_b};
    wire i_q_int0_div = ~i_full_diff[SUPER_SIG];
    wire [SUPER_SIG-1:0] i_pre_diff = i_q_int0_div ? i_full_diff[SUPER_SIG-1:0] : i_sig_a;''')
