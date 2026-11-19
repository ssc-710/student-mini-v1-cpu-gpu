"""Strictly scoped, latency-preserving signed 33x33 multiplier projection."""
import hashlib

PINNED_SHA256 = '2262edce9571335796e973d6b68e5d3edd7d88e40abf139f6e7e5fe77ae6ec36'


def project(original, candidate, *, differential=False):
    if hashlib.sha256(original.encode()).hexdigest() != PINNED_SHA256:
        raise ValueError('pinned original VX_multiplier source changed')
    if candidate.count('module student_mini_signed33_mul3 (') != 1:
        raise ValueError('one dedicated signed33 candidate required')
    seam = '    wire [R_WIDTH-1:0] prod_w;'
    if original.count(seam) != 1 or original.count('\nendmodule') != 1:
        raise ValueError('multiplier source seam changed')
    branch = '''    if (A_WIDTH == 33 && B_WIDTH == 33 && R_WIDTH == 66 && SIGNED == 1 && LATENCY == 3) begin : g_mini_cut
        student_mini_signed33_mul3 cut (
            .clk(clk), .enable(enable), .dataa(dataa), .datab(datab), .result(result)
        );
    end else begin : g_original
'''
    value = original.replace(seam, branch+seam).replace('\nendmodule', '\n    end\nendmodule')
    if differential:
        value = value.replace('module VX_multiplier #(', 'module VX_multiplier_candidate #(')
    return value+'\n'+candidate


def mutants(candidate):
    changes = {
        'unsigned_high': ("$signed(dataa[32:16])", "$signed({1'b0, dataa[31:16]})"),
        'wrong_cross_term': ('p01 <= a_low * b_high;', 'p01 <= a_high * b_low;'),
        'lost_stall': ('if (enable) begin', "if (1'b1) begin"),
        'wrong_final_shift': ("{row_high, 16'b0}", "{row_high[49], row_high, 15'b0}"),
    }
    result = {}
    for name, (old, new) in changes.items():
        if candidate.count(old) != 1: raise ValueError('mutation seam changed: '+name)
        result[name] = candidate.replace(old, new)
    return result
