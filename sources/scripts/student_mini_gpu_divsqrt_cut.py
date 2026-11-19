"""A private Vortex timing candidate: one NR step per SRT pipeline stage.

Preserves recurrence, format, rounding, flags and throughput; changes F32
latency from 17 to 30 enabled clocks. Not a PROMOTE or a physical PASS.
Never edits the pinned vendor tree or silently reuses 17-cycle counters.
"""
import re


def once(source,old,new):
    if source.count(old)!=1:raise ValueError('unexpected pinned SRT source: '+old[:70])
    return source.replace(old,new)


def project(source):
    source=once(source,'module VX_fdivsqrt_unit import','module VX_fdivsqrt_step_cut import')
    source=once(source,'parameter LATENCY = 17,','parameter LATENCY = 30,')
    source=once(source,'localparam NR_STAGES = NR_BITS / 2;', 'localparam NR_STAGES = NR_BITS;')
    source=source.replace('// 13 / 28','// 26 / 56')
    source=once(source,'(two NR steps each, carry-save W)','(one NR step each, carry-save W)')
    source=once(source,'SUPER_SIG + SCALE_SQRT - 2 - 2*k','SUPER_SIG + SCALE_SQRT - 2 - k')
    for name in ('ULP_B_NRO0','ULP_B_NRO1'):
        source,count=re.subn(r'^        localparam \[W_BITS-1:0\] '+name+r' = .*;\n','',source,flags=re.M)
        if count!=1:raise ValueError('missing second-step ULP')
    source=once(source,'SUPER_SIG + SCALE_SQRT - 3 - 2*k','SUPER_SIG + SCALE_SQRT - 3 - k')
    source=once(source,'        wire [W_BITS-1:0] ulp_b = nro_in ? ULP_B_NRO1 : ULP_B_NRO0;\n','')
    begin=source.index('        // --- Step B ---')
    end=source.index('        wire [STAGE_W-1:0] s_out;',begin)
    source=source[:begin]+'''        // Register after every original NR step; quotient shifts once.
        `UNUSED_VAR (qb_in[NR_BITS-1])
        wire [NR_BITS-1:0] qb_new = {qb_in[NR_BITS-2:0], q_a};

'''+source[end:]
    for old,new in [('= Ws_b;','= Ws_a;'),('= Wc_b;','= Wc_a;'),('= DS_b;','= DS_a;')]:
        source=once(source,old,new)
    source=source.replace('//   SUPER=F32: NR_STAGES=13 -> LATENCY 17','//   SUPER=F32: NR_STAGES=26 -> LATENCY 30')
    source=source.replace('//   SUPER=F64: NR_STAGES=28 -> LATENCY 32','//   SUPER=F64: NR_STAGES=56 -> LATENCY 60 (not the mini profile)')
    return source
