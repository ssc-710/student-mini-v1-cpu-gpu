"""Full-chip 10 ns sign-off of the hierarchical student-mini GPU.

Inputs: the passing guarded top-level run and the four passing guarded quadrant-block runs
(scripts/run_student_mini_platform_physical.py).  OpenSTA links the top's final netlist with the four
blocks' final netlists (no abstract timing models), annotates the top SPEF and every block SPEF at its
instance, applies the GPU constraint with propagated clocks and reports setup and hold over every path,
cross-block paths included.  PASS requires setup WNS >= 0 and hold WNS >= 0 with every input unchanged.
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

STA = Path('/home/soclab/.local/bin/sta')
STD_LIB = Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib')
NAMES = ('q0_LL', 'q1_LR', 'q2_UL', 'q3_UR')


def passing(path, status='PLATFORM_PHYSICAL_ROUTE_STAGE_PASS'):
    done = json.loads(path.read_text())
    if done.get('status') != status:
        raise ValueError(f'{path} is not a passing run')
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top', type=Path, required=True, help='completion.json of the guarded top-level run')
    parser.add_argument('--blocks', type=Path, nargs=4, required=True, help='completion.json of q0..q3 block runs')
    parser.add_argument('--sram-libs', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    top = passing(args.top)
    blocks = [passing(b) for b in args.blocks]
    top_results = Path(top['result_directory'])
    files = [STA, STD_LIB, *args.sram_libs, Path(__file__), ROOT / 'integration/student-mini/gpu_fullchip_sta.tcl',
             args.top.resolve(), top_results / '6_final.v', top_results / '6_final.spef', top_results / '6_final.sdc']
    triples = []
    for q, (path, done) in enumerate(zip(args.blocks, blocks)):
        r = Path(done['result_directory'])
        module = re.search(r'^module (\S+)', (r / '6_final.v').read_text(errors='replace')[:4000], re.M).group(1)
        triples += [f'{module}_inst', str(r / '6_final.v'), str(r / '6_final.spef')]
        files += [path.resolve(), r / '6_final.v', r / '6_final.spef']
    bindings = {str(p): sha(p) for p in files}
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    work = ROOT / 'build/student-mini/gpu-fullchip-sta' / key
    work.mkdir(parents=True, exist_ok=True)
    env = dict(STUDENT_MINI_LIBS=' '.join(str(p) for p in [STD_LIB, *args.sram_libs]),
               STUDENT_MINI_TOP_V=str(top_results / '6_final.v'), STUDENT_MINI_TOP_SPEF=str(top_results / '6_final.spef'),
               STUDENT_MINI_SDC=str(top_results / '6_final.sdc'), STUDENT_MINI_BLOCKS=' '.join(triples),
               STUDENT_MINI_TOP=top.get('design', 'vortex_physical_top'), STUDENT_MINI_REPORT=str(work / 'fullchip.rpt'),
               PATH='/usr/bin:/bin')
    started = time.monotonic()
    with (work / 'sta.log').open('w') as log:
        code = subprocess.call(['/usr/bin/time', '-v', str(STA), '-exit', '-no_splash',
                                str(ROOT / 'integration/student-mini/gpu_fullchip_sta.tcl')], env=env, stdout=log, stderr=subprocess.STDOUT)
    text = (work / 'sta.log').read_text(errors='replace')
    setup = re.search(r'STUDENT_MINI_FULLCHIP_SETUP\s+worst slack max (\S+)\s+tns max (\S+)', text)
    hold = re.search(r'STUDENT_MINI_FULLCHIP_HOLD\s+worst slack min (\S+)\s+tns min (\S+)', text)
    black = re.findall(r'Warning 198: .* not found\. Creating black box', text)
    result = dict(status='HOLD', bindings=bindings, clock_period_ns=10, elapsed_seconds=time.monotonic() - started,
                  peak_rss_bytes=int(re.findall(r'Maximum resident set size \(kbytes\): (\d+)', text)[-1]) * 1024
                  if 'Maximum resident' in text else None)
    try:
        if code or not setup or not hold or 'STUDENT_MINI_FULLCHIP_COMPLETE' not in text:
            raise RuntimeError('full-chip STA did not complete; see sta.log')
        if black:
            raise ValueError(f'unlinked cells (black boxes): {black[:2]}')
        if any(sha(Path(p)) != v for p, v in bindings.items()):
            raise ValueError('input changed during STA')
        result.update(setup_wns_ns=float(setup.group(1)), setup_tns_ns=float(setup.group(2)),
                      hold_wns_ns=float(hold.group(1)), hold_tns_ns=float(hold.group(2)))
        if result['setup_wns_ns'] < 0 or result['hold_wns_ns'] < 0:
            raise ValueError('full-chip 10 ns timing not closed')
        result.update(status='GPU_FULLCHIP_SIGNOFF_PASS', reason='setup and hold closed at 10 ns over the assembled GPU')
    except Exception as error:
        result['reason'] = f'{type(error).__name__}: {error}'
    (work / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), status=result['status'], reason=result['reason'],
                          setup=result.get('setup_wns_ns'), hold=result.get('hold_wns_ns'))))
    return 0 if result['status'] == 'GPU_FULLCHIP_SIGNOFF_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
