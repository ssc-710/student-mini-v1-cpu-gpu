"""Join the GPU protocol runs (MINI-31/32/33) into per-record protocol evidence.

Each case/seed ran in all three counter classes with its frozen protocol
parameters (scripts/run_student_mini_gpu_protocol_rtl.py).  A record passes
only if all classes completed with identical output, the output is bit-exact
against the frozen golden, and the protocol counters show the condition was
actually applied and obeyed:
  MINI-31  stalls applied on both memory handshakes (request and response), zero
           stability violations
  MINI-32  every host response held exactly `hold` cycles, zero violations
  MINI-33  reset while the device was busy (no completion before it), every
           DCR write replayed, the reissued launch completed bit-exact
and the number of completed launches equals the baseline execution's.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_release_records import compare

CASES = ('MINI-31', 'MINI-32', 'MINI-33')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='gpu-protocol-rtl work dir')
    parser.add_argument('--baseline', type=Path, required=True, help='gpu-platform-rtl work dir of the formal results')
    parser.add_argument('--vectors', type=Path, required=True)
    args = parser.parse_args()
    work, baseline = args.work.resolve(), args.baseline.resolve()
    built = json.loads((work / 'build.json').read_text())
    if built['status'] != 'GPU_PLATFORM_RTL_BUILD_STAGE_PASS':
        raise ValueError('protocol build did not pass')
    vectors = [json.loads(line) for line in args.vectors.read_text().splitlines()]
    targets = [i for i, v in enumerate(vectors) if v['case']['id'].split('-', 1)[1] in CASES]
    records, failures = [], []
    bindings = {str(p): sha(p) for p in (Path(__file__), work / 'build.json', baseline / 'build.json', args.vectors.resolve())}
    for ordinal in targets:
        vector = vectors[ordinal]
        runs = {}
        for cls in (0, 4, 7):
            path = work / 'runs' / f'{ordinal:04d}-c{cls}' / 'record.json'
            runs[cls] = json.loads(path.read_text())
            bindings[str(path)] = sha(path)
        ref = json.loads((baseline / 'runs' / f'{ordinal:04d}-c0' / 'record.json').read_text())
        p = vector['inputs']['protocol']
        complete = all(r.get('complete') and r.get('protocol', {}).get('complete') for r in runs.values())
        same = len({json.dumps(r.get('output'), sort_keys=True) for r in runs.values()}) == 1
        r0 = runs[0]
        observation = dict(r0.get('output') or {}, cycles=r0.get('cycles'), instructions=r0.get('instructions'),
                           device_fault=r0.get('device_fault'), device_launches=r0.get('device_launches'),
                           dcache_requests=runs[4].get('dcache_requests'), memory=runs[7].get('memory'))
        if observation.get('dcache_requests') is not None:
            observation['cache_bytes'] = observation['dcache_requests'] * 8
        if observation.get('memory'):
            observation['dma_bytes'] = observation['memory'][0] * 64
        comparison = compare(vector['golden'], observation, vector['case']['operator']) if complete else dict(status='FAIL')
        events = {cls: r.get('protocol', {}) for cls, r in runs.items()}
        e = events[0]
        launches_ok = complete and all(r.get('device_launches') == ref.get('device_launches') for r in runs.values())
        stable = complete and all(ev.get('stability_violations') == 0 for ev in events.values())
        checks = {'exactly-one-completion': launches_ok and same}
        if p['backpressure_probability']:
            checks['stable-response-until-ready'] = stable and all(ev.get('stalled_req_cycles', 0) > 0 and ev.get('stalled_rsp_cycles', 0) > 0
                                                                   for ev in events.values())
        elif p['response_hold_cycles']:
            hold = p['response_hold_cycles']
            checks['stable-response-until-ready'] = stable and all(ev.get('responses', 0) > 0 and ev.get('held_rsp_cycles') == hold * ev['responses']
                                                                   for ev in events.values())
        else:
            checks['stable-response-until-ready'] = stable
        if p['reset_and_reissue']:
            checks['no-spurious-pre-reset-completion'] = complete and all(
                len(ev.get('resets', [])) == 1 and ev['resets'][0]['busy_at_reset'] == 1 for ev in events.values())
            checks['reissued-command-passes'] = complete and comparison.get('status') == 'PASS' and all(
                len(ev.get('reissues', [])) == 1 and ev['reissues'][0]['busy_after_start'] == 1 for ev in events.values())
        actual_events = sorted(k for k, ok in checks.items() if ok)
        status = 'PASS' if (complete and same and comparison.get('status') == 'PASS' and all(checks.values())
                            and actual_events == sorted(vector['golden']['expected_events'])) else 'FAIL'
        if status != 'PASS':
            failures.append(ordinal)
        records.append(dict(ordinal=ordinal, case_id=vector['case']['id'], seed=vector['seed'], setting=r0.get('protocol_parameters'),
                            events=e, events_by_class={str(k): v for k, v in events.items()}, observation=observation,
                            numeric_match=comparison.get('status') == 'PASS', checks=checks, actual_events=actual_events,
                            expected_events=vector['golden']['expected_events'], status=status))
    result = dict(status='GPU_PROTOCOL_QUALIFICATION_PASS' if not failures else 'GPU_PROTOCOL_QUALIFICATION_FAIL',
                  interface='GPU memory request/response handshakes, host command response, reset (vortex_physical_top ports)',
                  bindings=bindings, records=records, failures=failures)
    key = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    out = ROOT / 'build/student-mini/gpu-protocol-results' / key
    out.mkdir(parents=True, exist_ok=True)
    (out / 'completion.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(path=str(out / 'completion.json'), status=result['status'], failures=failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
