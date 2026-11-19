"""Private F32 timing foundation: isolate denormal shift from rounding/packing."""
import re
from scripts.student_mini_gpu_divsqrt_cut import project as step_project, once


def project(source):
    source=step_project(source)
    source=once(source,'parameter LATENCY = 30,','parameter LATENCY = 31,')
    source=once(source,'localparam NRM_LATENCY  = 1;','localparam NRM_LATENCY  = 2;')
    anchor='    wire [SUPER_SIG-1:0] abs_rounded;'
    if source.count(anchor)!=1:raise ValueError('normalization cut seam changed')
    prefix,suffix=source.split(anchor)
    capture='''    // Preserve the exact denormal/guard/sticky arithmetic; register its
    // result and all corresponding metadata before rounding and packing.
    localparam NRM_CUT_W = SUPER_SIG + EXP_W + INST_FRM_BITS + 10;
    wire [SUPER_SIG-1:0] cut_man;
    wire cut_guard, cut_sticky, cut_sign, cut_isd, cut_sub;
    wire [EXP_W-1:0] cut_exp_bits;
    wire [INST_FRM_BITS-1:0] cut_frm;
    wire [4:0] cut_exc;
    VX_pipe_register #(.DATAW(NRM_CUT_W), .DEPTH(1)) nrm_shift_reg (
        .clk(clk), .reset(reset), .enable(enable && valid_nrm),
        .data_in({sub_man, sub_guard, sub_sticky, s_exp_bits,
                  s_sign, s_frm, s_exc, s_isd, result_sub}),
        .data_out({cut_man, cut_guard, cut_sticky, cut_exp_bits,
                   cut_sign, cut_frm, cut_exc, cut_isd, cut_sub})
    );
    wire signed [EXP_W-1:0] cut_exp = $signed(cut_exp_bits);
    wire cut_act_d = HAS_D ? cut_isd : 1'b0;
    wire cut_nan = cut_exc[4];
    wire cut_inf = cut_exc[3];
    wire cut_zero = cut_exc[2];
    wire cut_dz = cut_exc[1];
    wire cut_nv = cut_exc[0];

'''
    names=dict(sub_man='cut_man',sub_guard='cut_guard',sub_sticky='cut_sticky',
        s_sign='cut_sign',s_frm='cut_frm',s_exp='cut_exp',result_sub='cut_sub',
        act_d='cut_act_d',is_nan='cut_nan',is_inf='cut_inf',is_zero='cut_zero',dz_flag='cut_dz',nv_flag='cut_nv')
    suffix=anchor+suffix
    for old,new in names.items():suffix=re.sub(r'\b'+old+r'\b',new,suffix)
    suffix=once(suffix,'.enable (enable && valid_nrm)',
        '.enable (enable && mask_pipe[PRE_LATENCY+INI_LATENCY+NR_STAGES+CONV_LATENCY])')
    return prefix+capture+suffix


def wrapper(source):
    changes={'.LATENCY(30)':' .LATENCY(31)', 'reg [29:0] valid_pipe;':'reg [30:0] valid_pipe;',
        'reference_delay[0:12]':'reference_delay[0:13]', 'descriptors[0:29]':'descriptors[0:30]',
        'valid_pipe[28:0]':'valid_pipe[29:0]', 'i<13':'i<14', 'i<30':'i<31',
        'valid=valid_pipe[29]':'valid=valid_pipe[30]', 'reference_delay[12]':'reference_delay[13]',
        'descriptors[29]':'descriptors[30]'}
    for old,new in changes.items():source=once(source,old,new)
    return source
