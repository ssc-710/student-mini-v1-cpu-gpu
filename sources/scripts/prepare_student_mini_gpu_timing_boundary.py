"""Derive the final GPU boundary: timing cuts + bus-fault adapters.

Starting from the icache-pipeline boundary (flattened sv2v RTL), apply only:
  1. FMA significand multiply (F32, MUL_LATENCY == 2): the original computes the
     whole 24x24 Wallace product combinationally and then delays it by two
     enabled register stages.  Here the two stages hold two registered partial
     products (a*b_lo, a*b_hi) and their registered sum.  Same latency, same
     enable behaviour, mathematically identical product.
  2. perf_mem_pending_reads / perf_icache_pending_reads accumulate a registered
     per-cycle delta.  The accumulated latency counters are read only after the
     device is idle (no pending reads), so every reported counter is unchanged.
  3. The physical top / command adapter / memory adapters are replaced by the
     bus-fault variants (status DCR 0xFFF), formally checked against the
     originals in build/student-mini/explore/gpu-fault-proof.
No other RTL, configuration or macro mapping changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha

FMA_OLD = re.compile(r'''(\t\telse if \(\(MUL_LATENCY < 3\) && \(SIG_BITS <= 24\)\) begin : g_mul_wallace\n)(.*?)(\t\tend\n\t\telse begin : g_mul_infer\n)''', re.S)
FMA_NEW = '''\t\t\t// student-mini timing cut: the two MUL register stages hold two partial
\t\t\t// products and their sum instead of delaying one combinational product.
\t\t\tif (MUL_LATENCY != 2) begin : g_mul_split_requires_two_stages
\t\t\t\tinitial $fatal(1, "student-mini FMA split requires MUL_LATENCY == 2");
\t\t\tend
\t\t\tlocalparam BL_W = SIG_BITS - (SIG_BITS / 2);
\t\t\tlocalparam BH_W = SIG_BITS / 2;
\t\t\treg [(SIG_BITS + BL_W) - 1:0] pp_lo_q;
\t\t\treg [(SIG_BITS + BH_W) - 1:0] pp_hi_q;
\t\t\treg [PROD_BITS - 1:0] prod_q;
\t\t\talways @(posedge clk)
\t\t\t\tif (enable) begin
\t\t\t\t\tpp_lo_q <= r1_sig_a * r1_sig_b[BL_W - 1:0];
\t\t\t\t\tpp_hi_q <= r1_sig_a * r1_sig_b[SIG_BITS - 1:BL_W];
\t\t\t\t\tprod_q <= {{(PROD_BITS - (SIG_BITS + BL_W)){1'b0}}, pp_lo_q} + ({{(PROD_BITS - (SIG_BITS + BH_W)){1'b0}}, pp_hi_q} << BL_W);
\t\t\t\tend
\t\t\tassign s1_prod = prod_q;
'''

MEM_OLD = '''\t\t\tperf_mem_pending_reads <= $signed(perf_mem_pending_reads) + sv2v_cast_44_signed($signed(sv2v_cast_3(perf_mem_reads_per_cycle) - sv2v_cast_3(perf_mem_rsps_per_cycle)));'''
MEM_NEW = '''\t\t\tperf_mem_pending_reads <= $signed(perf_mem_pending_reads) + sv2v_cast_44_signed($signed(perf_mem_pending_delta_q));'''
MEM_DECL_OLD = '''\treg [43:0] perf_mem_pending_reads;\n'''
MEM_DECL_NEW = '''\treg [43:0] perf_mem_pending_reads;
\t// student-mini timing cut: registered per-cycle pending-read delta.
\treg [2:0] perf_mem_pending_delta_q;
\talways @(posedge clk)
\t\tif (reset)
\t\t\tperf_mem_pending_delta_q <= 1'sb0;
\t\telse
\t\t\tperf_mem_pending_delta_q <= sv2v_cast_3(perf_mem_reads_per_cycle) - sv2v_cast_3(perf_mem_rsps_per_cycle);
'''
ICACHE_OLD = '''perf_icache_pending_reads <= $signed(perf_icache_pending_reads) + sv2v_cast_44_signed($signed(perf_icache_pending_read_cycle));'''
ICACHE_NEW = '''perf_icache_pending_reads <= $signed(perf_icache_pending_reads) + sv2v_cast_44_signed($signed(perf_icache_pending_read_cycle_q));'''


def patch(text):
    match = list(FMA_OLD.finditer(text))
    if len(match) != 1 or 'VX_wallace_mul' not in match[0].group(2) or '.DEPTH(MUL_LATENCY)' not in match[0].group(2):
        raise ValueError('unexpected FMA Wallace block')
    text = text[:match[0].start(2)] + FMA_NEW + text[match[0].end(2):]
    for old, new in ((MEM_OLD, MEM_NEW), (MEM_DECL_OLD, MEM_DECL_NEW), (ICACHE_OLD, ICACHE_NEW)):
        if text.count(old) != 1:
            raise ValueError('unexpected perf counter seam: ' + old[:60])
        text = text.replace(old, new)
    # Declare and register the icache pending-read delta next to its source.
    decl = re.findall(r'\n(\t+)(wire|reg) (\[[^\]]+\] )?perf_icache_pending_read_cycle;\n', text)
    if len(decl) != 1:
        raise ValueError('unexpected icache pending-read declaration')
    indent, _, width = decl[0]
    width = width or ''
    anchor = re.search(r'\n\t+(wire|reg) (\[[^\]]+\] )?perf_icache_pending_read_cycle;\n', text)
    block = (f'{indent}// student-mini timing cut: registered per-cycle pending-read delta.\n'
             f'{indent}reg {width}perf_icache_pending_read_cycle_q;\n'
             f'{indent}always @(posedge clk)\n{indent}\tif (reset)\n{indent}\t\tperf_icache_pending_read_cycle_q <= 1\'sb0;\n'
             f'{indent}\telse\n{indent}\t\tperf_icache_pending_read_cycle_q <= perf_icache_pending_read_cycle;\n')
    text = text[:anchor.end()] + block + text[anchor.end():]
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary', type=Path, required=True, help='icache-pipeline boundary directory')
    args = parser.parse_args()
    boundary = args.boundary.resolve()
    completed = json.loads((boundary / 'completion.json').read_text())
    project = boundary / 'project-banked.v'
    if completed['artifacts'].get(project.name) != sha(project):
        raise ValueError('parent boundary RTL changed')
    local = {'vortex_physical_top.sv': ROOT / 'integration/student-mini/gpu_fault_physical_top.sv',
             'gpu_status_command_adapter.sv': ROOT / 'integration/student-mini/gpu_status_command_adapter.sv',
             'gpu_fault_memory_adapter.sv': ROOT / 'integration/student-mini/gpu_fault_memory_adapter.sv'}
    proof = ROOT / 'build/student-mini/explore/gpu-fault-proof/proof.log'
    if 'SAT proof finished - no model found: SUCCESS!' not in proof.read_text():
        raise ValueError('bus-fault adapter proof missing')
    paths = [Path(__file__), boundary / 'completion.json', project, boundary / 'macros-blackboxes.v',
             boundary / 'macro-placement.tcl', proof, *local.values()]
    bindings = {str(p): sha(p) for p in paths}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-timing-boundary' / key / 'boundary'
    work.mkdir(parents=True, exist_ok=False)
    (work / 'project-banked.v').write_text(patch(project.read_text()))
    for name, path in local.items():
        shutil.copyfile(path, work / name)
    for name in ('macros-blackboxes.v', 'macro-placement.tcl'):
        shutil.copyfile(boundary / name, work / name)
    result = dict(status='GPU_TIMING_BOUNDARY_DERIVED', boundary_complete=True, parent=str(boundary), bindings=bindings,
                  changes=['fma-split-partial-products', 'perf-pending-delta-registers', 'bus-fault-adapters'],
                  formal_baseline=False, physical_evidence_complete=False,
                  artifacts={p.name: sha(p) for p in work.iterdir() if p.is_file()})
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'])))


if __name__ == '__main__':
    main()
