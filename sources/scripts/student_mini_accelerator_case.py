"""Student-owned, isolated actual RTL replay of one frozen accelerator case.

This does not certify a baseline. Existing evidence/builds are never overwritten.
The existing cocotb harness supplies only test inputs to hardware, not goldens.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha, compare_outputs, summarize_seeds


def select_case(rows, case_id, seed):
    seen = set(); selected = []
    for row in rows:
        key = (row['case']['id'], row['seed'])
        if type(key[1]) is not int or key[1] not in range(1,11) or key in seen:
            raise ValueError('duplicate/invalid frozen case seed')
        seen.add(key)
        if key[0] == case_id: selected.append(row)
    if sorted(r['seed'] for r in selected) != list(range(1,11)):
        raise ValueError('selected frozen case must contain exactly seeds 1..10')
    operators = {r['case']['operator'] for r in selected}
    if len(operators) != 1 or not operators <= {'p1','p2','p3'}: raise ValueError('ambiguous operator')
    if seed is not None and (type(seed) is not int or seed not in range(1,11)): raise ValueError('seed must be 1..10')
    return sorted([r for r in selected if seed is None or r['seed'] == seed], key=lambda r:r['seed'])


def compare_selected(goldens, actuals):
    actual = {}
    for row in actuals:
        key = (row['case_id'], row['seed'])
        if type(key[1]) is not int or key in actual: raise ValueError('duplicate/invalid actual seed')
        actual[key] = row
    expected = {(g['case']['id'],g['seed']) for g in goldens}
    if actual.keys() != expected: raise ValueError('actual case/seed set differs')
    result = []
    for g in goldens:
        row = actual[(g['case']['id'],g['seed'])]; golden = g['golden']
        if row['backend'] != 'verilator-rtl' or row['platform'] != 'accelerator' or row['operator'] != g['case']['operator']:
            raise ValueError('actual target identity differs')
        for name in ('cycles','instructions','dma_bytes','cache_bytes'):
            if type(row.get(name)) is not int or row[name] < 0: raise ValueError('missing actual hardware counter: '+name)
        matched = row['actual_status'] == golden['expected_status']
        if golden['output_values']:
            delta = compare_outputs(golden['output_values'],row['actual'],golden['output_bits'],row['actual_bits'])
            matched = matched and delta['status'] == 'PASS'
        else:
            matched = matched and row['actual'] == [] and row['actual_bits'] == []
            delta = dict(kind='error-status',expected=golden['expected_status'],actual=row['actual_status'],delta=None)
        if g['case']['operator'] == 'p1' and golden['output_values']:
            matched = matched and row.get('selected_token_ids') == golden['selected_token_ids']
        if g['case']['scenario'] == 'reset-recovery':
            reset = row.get('reset_observation') or {}
            matched = matched and reset == dict(command_accepted=True,abort_after_cycles=20,silent_post_reset_cycles=8)
        missing = list(row.get('missing_witnesses', []))
        # Keep the immutable harness's auxiliary HOLD. Components cannot be
        # declared executed merely because output bits agree.
        if 'primitive_witness' in g['inputs'] and 'primitive-witness-executed-on-target' not in missing:
            raise ValueError('unproven primitive witness removed')
        if g['case']['scenario'] == 'arrival-order' and 'out-of-order-split-protocol-witness' not in missing:
            raise ValueError('unproven arrival-order witness removed')
        result.append(dict(case=g['case'],seed=g['seed'],prng=g['prng'],inputs=g['inputs'],golden=golden,
                           observation=row,comparison=delta,status='FAIL' if not matched else 'HOLD' if missing else 'PASS'))
    return result


def verify(bindings):
    if any(sha(Path(path)) != digest for path,digest in bindings.items()): raise ValueError('source/input changed')


def worker(work):
    manifest = json.loads((work/'inputs.json').read_text()); verify(manifest['bindings'])
    op = manifest['operator']
    sys.path.insert(0,str(ROOT/'tests/rtl'))
    import runner
    original = runner.launch
    def isolated(name, *args, **kwargs):
        if name != 'student_mini_'+op: raise ValueError('unexpected harness entry')
        return original(manifest['build_name'], *args, **kwargs)
    runner.launch = isolated
    runpy.run_path(str(ROOT/f'tests/rtl/test_student_mini_{op}.py'), run_name='__main__')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors', type=Path); parser.add_argument('--golden-sha256')
    parser.add_argument('--case', dest='case_id')
    seeds = parser.add_mutually_exclusive_group(); seeds.add_argument('--seed',type=int,choices=range(1,11)); seeds.add_argument('--all-seeds',action='store_true')
    parser.add_argument('--verilator',type=Path)
    parser.add_argument('--queue-lock',type=Path,default=ROOT/'build/student-mini/student-queue.lock')
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker: worker(args.worker.resolve()); return 0
    if os.name != 'posix': parser.error('Run actual RTL in Ubuntu/WSL2; Windows can read the offline reports.')
    if not all((args.vectors,args.golden_sha256,args.case_id,args.verilator)) or not (args.seed or args.all_seeds):
        parser.error('supply vectors, published SHA, case, seed/all-seeds and explicit Verilator')
    vectors = args.vectors.resolve(); tool = args.verilator.resolve()
    if sha(vectors) != args.golden_sha256: raise ValueError('frozen golden SHA differs')
    expected_tools = {'verilator':'491c95e1a949a3df1f370c9d39318e159d08b246edf4363fb42d05ea88f74dbe',
                      'verilator_bin':'8b14fd2d01a0a45735938fdd0e361e6511063d77a68bf6009d9625256e17dbb7'}
    for name,digest in expected_tools.items():
        if sha(tool.parent/name) != digest: raise ValueError('CPU/accelerator Verilator binary differs: '+name)
    if tool.name != 'verilator': raise ValueError('explicit Verilator launcher required')
    selected = select_case([json.loads(line) for line in vectors.read_text().splitlines()],args.case_id,args.seed)
    op = selected[0]['case']['operator']
    files = [Path(__file__),ROOT/'scripts/student_mini.py',vectors,tool,tool.parent/'verilator_bin']
    files += list((ROOT/'tests/rtl').glob('*.py'))
    files += [p for p in (ROOT/'shared/rtl').iterdir() if p.is_file() and p.suffix in ('.sv','.svh','.mem')]
    bindings = {str(p):sha(p) for p in files}
    key = hashlib.sha256(json.dumps(dict(bindings=bindings,case=args.case_id,seed=args.seed),sort_keys=True).encode()).hexdigest()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work = ROOT/'build/student-mini/student-case-replays'/(key[:16]+'-'+stamp); work.mkdir(parents=True,exist_ok=False)
    subset = work/'vectors.jsonl'; subset.write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in selected),encoding='utf-8')
    bindings[str(subset)] = sha(subset)
    build_name = 'student_case_'+op+'_'+key[:12]+'_'+stamp
    manifest = dict(bindings=bindings,operator=op,build_name=build_name,case=args.case_id,seeds=[r['seed'] for r in selected])
    (work/'inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result = dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,selected_case_only=True,bindings=bindings)
    begin = time.monotonic(); print(json.dumps(dict(work=str(work),status='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    import fcntl
    args.queue_lock.parent.mkdir(parents=True,exist_ok=True)
    try:
        with args.queue_lock.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX); verify(bindings)
            env = dict(os.environ,PYTHONPATH=str(ROOT/'shared/python'),COURSE_VERILATOR_BIN=str(tool),MAKEFLAGS='-j2',
                       COURSE_EVIDENCE_TAG=build_name,STUDENT_MINI_VECTORS=str(subset),STUDENT_MINI_ACTUAL=str(work/'actual.jsonl'),STUDENT_MINI_LIMIT='0')
            os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
            with (work/'run.log').open('x') as output:
                child = subprocess.Popen([sys.executable,str(Path(__file__)),'--worker',str(work)],cwd=ROOT,env=env,
                                         stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try: code = child.wait(timeout=1500)
                except subprocess.TimeoutExpired:
                    import signal
                    os.killpg(child.pid,signal.SIGTERM)
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(child.pid,signal.SIGKILL); child.wait()
                    raise ValueError('actual RTL timeout; original log retained')
            result['exit_code'] = code
            if code: raise ValueError('actual RTL failed; inspect run.log')
            records = compare_selected(selected,[json.loads(line) for line in (work/'actual.jsonl').read_text().splitlines()])
            numeric = [dict(seed=r['seed'],**r['comparison']) for r in records if 'golden_bits' in r['comparison']]
            result.update(records=records,ten_seed_summary=summarize_seeds(numeric) if len(numeric)==10 else None,
                          counter_summary={name:dict(raw=[r['observation'][name] for r in records],mean=sum(r['observation'][name] for r in records)/len(records))
                                           for name in ('cycles','instructions','dma_bytes','cache_bytes')})
            verify(bindings)
            if any(r['status']=='FAIL' for r in records): raise ValueError('actual selected output/status differs from golden')
            result.update(status='SELECTED_CASE_RTL_STAGE_PASS' if all(r['status']=='PASS' for r in records) else 'HOLD',
                          reason='Actual selected RTL replay; any auxiliary/protocol HOLD remains, never a whole baseline certificate')
    except Exception as error: result['reason'] = f'{type(error).__name__}: {error}'
    result['elapsed_seconds'] = time.monotonic()-begin
    result['artifacts'] = {p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='SELECTED_CASE_RTL_STAGE_PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
