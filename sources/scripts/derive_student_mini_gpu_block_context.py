"""Chip timing context of the hierarchical student-mini GPU's quadrant blocks.

Inputs: the same as the full-chip sign-off (scripts/run_student_mini_gpu_fullchip_sta.py): the passing guarded top-level
run and the four passing guarded quadrant-block runs.  OpenSTA times the assembled chip exactly as the sign-off does
(integration/student-mini/gpu_block_context.tcl) and writes, per block, an SDC overlay with the block's real chip
surroundings (clock edge at clk_i, arrival / required times at every timed port) in the block's own time frame.  The
context post-route ECO (scripts/run_student_mini_platform_physical_ctx.py --eco-context) repairs a block against it.
Writes build/student-mini/gpu-block-context/<key>/{<instance>.sdc, sta.log, completion.json}; PASS when every block got
its overlay with every input unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.run_student_mini_gpu_fullchip_sta import STA, STD_LIB, passing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top', type=Path, required=True, help='completion.json of the guarded top-level run')
    parser.add_argument('--blocks', type=Path, nargs=4, required=True, help='completion.json of q0..q3 block runs')
    parser.add_argument('--sram-libs', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    top = passing(args.top)
    blocks = [passing(b) for b in args.blocks]
    top_results = Path(top['result_directory'])
    files = [STA, STD_LIB, *args.sram_libs, Path(__file__), ROOT / 'scripts/run_student_mini_gpu_fullchip_sta.py',
             ROOT / 'integration/student-mini/gpu_block_context.tcl', args.top.resolve(),
             top_results / '6_final.v', top_results / '6_final.spef', top_results / '6_final.sdc']
    triples, instances = [], []
    for path, done in zip(args.blocks, blocks):
        r = Path(done['result_directory'])
        module = re.search(r'^module (\S+)', (r / '6_final.v').read_text(errors='replace')[:4000], re.M).group(1)
        triples += [f'{module}_inst', str(r / '6_final.v'), str(r / '6_final.spef')]
        instances.append(f'{module}_inst')
        files += [path.resolve(), r / '6_final.v', r / '6_final.spef']
    bindings = {str(p): sha(p) for p in files}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-block-context' / key
    work.mkdir(parents=True, exist_ok=False)
    env = dict(STUDENT_MINI_LIBS=' '.join(str(p) for p in [STD_LIB, *args.sram_libs]),
               STUDENT_MINI_TOP_V=str(top_results / '6_final.v'), STUDENT_MINI_TOP_SPEF=str(top_results / '6_final.spef'),
               STUDENT_MINI_SDC=str(top_results / '6_final.sdc'), STUDENT_MINI_BLOCKS=' '.join(triples),
               STUDENT_MINI_TOP=top.get('design', 'vortex_physical_top'), STUDENT_MINI_CONTEXT_OUT=str(work),
               STUDENT_MINI_CONTEXT_BLOCKS=' '.join(instances), PATH='/usr/bin:/bin')
    started = time.monotonic()
    with (work / 'sta.log').open('w') as log:
        code = subprocess.call(['/usr/bin/time', '-v', str(STA), '-exit', '-no_splash',
                                str(ROOT / 'integration/student-mini/gpu_block_context.tcl')], env=env, stdout=log, stderr=subprocess.STDOUT)
    text = (work / 'sta.log').read_text(errors='replace')
    result = dict(status='HOLD', bindings=bindings, top=str(args.top.resolve()), blocks=[str(b.resolve()) for b in args.blocks],
                  elapsed_seconds=time.monotonic() - started,
                  peak_rss_bytes=int(re.findall(r'Maximum resident set size \(kbytes\): (\d+)', text)[-1]) * 1024
                  if 'Maximum resident' in text else None)
    try:
        if code or 'STUDENT_MINI_CONTEXT_COMPLETE' not in text:
            raise RuntimeError('context STA did not complete; see sta.log')
        if re.findall(r'Warning 198: .* not found\. Creating black box', text):
            raise ValueError('unlinked cells (black boxes)')
        contexts = {}
        for inst in instances:
            clock = re.search(rf'^STUDENT_MINI_CONTEXT_CLOCK {inst} margin=(\S+) rise=(\S+) fall=(\S+) slew_rise=(\S+) slew_fall=(\S+)$',
                              text, re.M)
            ports = re.search(rf'^STUDENT_MINI_CONTEXT_BLOCK {inst} inputs=(\d+) outputs=(\d+) untimed=(\d+)$', text, re.M)
            sdc = work / f'{inst}.sdc'
            if not clock or not ports or not sdc.exists():
                raise RuntimeError(f'no context for {inst}')
            contexts[inst] = dict(sdc=str(sdc), sha256=sha(sdc), setup_margin_ns=float(clock.group(1)),
                                  clock_rise_ns=float(clock.group(2)), clock_fall_ns=float(clock.group(3)),
                                  clock_slew_rise_ns=float(clock.group(4)), clock_slew_fall_ns=float(clock.group(5)),
                                  timed_inputs=int(ports.group(1)),
                                  timed_outputs=int(ports.group(2)), untimed_ports=int(ports.group(3)))
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('input changed during the context STA')
        result.update(status='GPU_BLOCK_CONTEXT_PASS', contexts=contexts,
                      reason='chip timing context of every quadrant block written')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'])))
    return 0 if result['status'] == 'GPU_BLOCK_CONTEXT_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
