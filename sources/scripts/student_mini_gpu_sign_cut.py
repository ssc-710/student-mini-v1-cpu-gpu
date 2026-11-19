"""Timing foundation: separate NR sign resolution from the state update."""
from scripts.student_mini_gpu_divsqrt_cut import once
from scripts.student_mini_gpu_normalization_cut import project as normalize, wrapper as normalize_wrapper


def project(source):
    source = normalize(source)
    source = once(source, 'parameter LATENCY = 31,', 'parameter LATENCY = 57,')
    source = once(source, 'PRE_LATENCY + INI_LATENCY + NR_STAGES + CONV_LATENCY + NRM_LATENCY',
                  'PRE_LATENCY + INI_LATENCY + 2*NR_STAGES + CONV_LATENCY + NRM_LATENCY')
    # These are timing indices only; the recurrence count and its ULP constants
    # remain NR_STAGES == NR_BITS, and all arithmetic is unchanged.
    key = 'PRE_LATENCY+INI_LATENCY+NR_STAGES'
    if source.count(key) != 4: raise ValueError('NR timing-index seam changed')
    source = source.replace(key, 'PRE_LATENCY+INI_LATENCY+2*NR_STAGES')
    begin = source.index('        wire [CS_BITS-1:0]       Ws_in')
    end = source.index('        wire [W_BITS-1:0] ulp_a', begin)
    state = source[begin:end]
    if state.count('srt_stage[k]') != 12: raise ValueError('complete NR state seam changed')
    state = state.replace('srt_stage[k]', 'step_state')
    capture = '''        // First enabled clock resolves the original carry-save sign.
        // Capture every corresponding state bit; no arithmetic is approximated.
        wire [STAGE_W-1:0] step_state;
        wire q_a;
        wire [CS_BITS:0] select_sum = {1'b0, srt_stage[k][W_LO +: CS_BITS]}
                                    + {1'b0, srt_stage[k][WC_LO +: CS_BITS]};
        VX_pipe_register #(.DATAW(STAGE_W+1), .DEPTH(1)) sign_reg (
            .clk(clk), .reset(reset),
            .enable(enable && mask_pipe[PRE_LATENCY+INI_LATENCY-1+2*k]),
            .data_in({srt_stage[k], ~select_sum[CS_BITS-1]}),
            .data_out({step_state, q_a})
        );

'''
    source = source[:begin]+capture+state+source[end:]
    source = once(source, "        wire [CS_BITS:0] W_a_sum = {1'b0, Ws_in} + {1'b0, Wc_in};\n        wire q_a = ~W_a_sum[CS_BITS-1];\n", '')
    source = once(source, 'mask_pipe[PRE_LATENCY+INI_LATENCY-1+k]',
                  'mask_pipe[PRE_LATENCY+INI_LATENCY+2*k]')
    return source


def wrapper(source):
    source = normalize_wrapper(source)
    for old, new in {
        '.LATENCY(31)': '.LATENCY(57)', 'reg [30:0] valid_pipe;': 'reg [56:0] valid_pipe;',
        'reference_delay[0:13]': 'reference_delay[0:39]', 'descriptors[0:30]': 'descriptors[0:56]',
        'valid_pipe[29:0]': 'valid_pipe[55:0]', 'i<14': 'i<40', 'i<31': 'i<57',
        'valid=valid_pipe[30]': 'valid=valid_pipe[56]', 'reference_delay[13]': 'reference_delay[39]',
        'descriptors[30]': 'descriptors[56]',
    }.items(): source = once(source, old, new)
    return source
