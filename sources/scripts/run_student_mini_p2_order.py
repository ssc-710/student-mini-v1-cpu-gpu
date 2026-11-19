"""Fresh full-corpus RTL replay of the serial reverse-split feasibility candidate."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha,compare_outputs
from scripts.student_mini_p2_order import FILES,project,check_arrival
from scripts.retry_student_mini_route import verify,execute_locked_route


def compare(goldens,actuals):
    expected={(r['case']['id'],r['seed']):r for r in goldens}
    actual={(r['case_id'],r['seed']):r for r in actuals}
    if len(expected)!=len(goldens) or len(actual)!=len(actuals) or actual.keys()!=expected.keys():raise ValueError('full P2 case/seed coverage differs')
    reverse=0
    for key,g in expected.items():
        row=actual[key];golden=g['golden']
        if row['platform']!='accelerator' or row['operator']!='p2' or row['backend']!='verilator-rtl':raise ValueError('actual target differs')
        if row['actual_status']!=golden['expected_status'] or row['actual_bits']!=golden['output_bits']:
            raise ValueError('full P2 output or error status differs')
        if golden['output_values']:
            if compare_outputs(golden['output_values'],row['actual'],golden['output_bits'],row['actual_bits'])['status']!='PASS':
                raise ValueError('BF16 output differs')
        elif row['actual']!=[]:raise ValueError('error case fabricated numerical output')
        if g['case']['scenario']=='reset-recovery' and row.get('reset_observation')!=dict(command_accepted=True,abort_after_cycles=20,silent_post_reset_cycles=8):
            raise ValueError('actual reset/recovery witness differs')
        if g['case']['scenario']=='arrival-order':
            if row.get('split_order_witness')!=check_arrival(g,row['transactions']):raise ValueError('missing actual reverse-order witness')
            reverse+=1
        missing=['primitive-witness-executed-on-target'] if 'primitive_witness' in g['inputs'] else []
        if row['missing_witnesses']!=missing or row['status']!=('HOLD' if missing else 'PASS'):
            raise ValueError('incorrect auxiliary HOLD or numeric status')
        for name in ('cycles','instructions','dma_bytes','cache_bytes'):
            if type(row.get(name)) is not int or row[name]<0:raise ValueError('missing real counter')
    if reverse!=10:raise ValueError('all ten frozen reverse-order seeds required')
    return dict(records=len(actuals),numeric_matches=len(actuals),reverse_order_witnesses=reverse,
        retained_auxiliary_holds=sum(bool(r['missing_witnesses']) for r in actuals))


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True)
    args=parser.parse_args();vectors=args.vectors.resolve()
    if sha(vectors)!='b96fc48dc57b6792203c39682dc08c51c65187f03c2e8f54444f32892858b974':
        raise ValueError('frozen full input/golden file differs')
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    goldens=[row for row in goldens if row['case']['operator']=='p2']
    if len(goldens)!=340:raise ValueError('all 340 P2 records required')
    tool=Path('/home/soclab/tools/verilator-5.040/bin/verilator')
    files=[Path(__file__),ROOT/'scripts/student_mini_p2_order.py',ROOT/'scripts/student_mini.py',
        ROOT/'scripts/retry_student_mini_route.py',ROOT/'scripts/resume_student_mini_interrupted.py',vectors,tool,tool.parent/'verilator_bin',
        ROOT/'grading/student-mini/spec.json']
    files+=list((ROOT/'tests/rtl').glob('*.py'))
    files+=[p for p in (ROOT/'shared/rtl').iterdir() if p.is_file() and p.suffix in ('.sv','.svh','.mem')]
    bindings={str(p):sha(p) for p in files}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/p2-serial-order'/key;work.mkdir(parents=True,exist_ok=False)
    rtl=work/'rtl';rtl.mkdir()
    for name in FILES:
        path=rtl/name;path.write_text(project(name,(ROOT/'shared/rtl'/name).read_text()));bindings[str(path)]=sha(path)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        whole_operator_qualified=False,precision_changed=False,transport=dict(header_operator_arg_bit0='reverse serial split execution; canonical ascending merge'),
        reason='Candidate requires real RTL replay, independent numeric joins and a new physical package')
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');start=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);verify(bindings)
            name='student_mini_p2_order_'+key[:12]
            env=dict(PYTHONPATH=str(ROOT/'shared/python'),COURSE_VERILATOR_BIN=str(tool),MAKEFLAGS='-j2',
                STUDENT_MINI_VECTORS=str(vectors),STUDENT_MINI_ACTUAL=str(work/'actual.jsonl'),STUDENT_MINI_LIMIT='0',
                STUDENT_MINI_P2_ORDER_PROJECT=str(rtl),STUDENT_MINI_ORDER_BUILD=name,COURSE_EVIDENCE_TAG=name)
            command=['env',*[f'{k}={v}' for k,v in env.items()],sys.executable,str(ROOT/'tests/rtl/test_student_mini_p2_order.py')]
            if execute_locked_route(command,work/'run.log',1500,lambda _:heartbeat('FULL_340_RTL_REPLAY')):
                raise ValueError('full actual P2 replay failed; original log retained')
            rows=[json.loads(line) for line in (work/'actual.jsonl').read_text().splitlines()]
            summary=compare(goldens,rows);verify(bindings)
            result.update(status='P2_SERIAL_ORDER_FULL_REPLAY_STAGE_PASS',summary=summary,
                reason='All frozen P2 outputs/statuses and ten real reverse execution traces match; auxiliary numeric joins and new physical signoff remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-start
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'],summary=result.get('summary'))),flush=True)
    return 0 if result['status']=='P2_SERIAL_ORDER_FULL_REPLAY_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
