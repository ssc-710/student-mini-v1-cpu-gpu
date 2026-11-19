#!/usr/bin/env python3
"""Source-bound mini RTL replay. A partial functional run never grants B0."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors',type=Path,required=True)
    parser.add_argument('--operator',choices=['p1','p2','p3'],required=True)
    parser.add_argument('--limit',type=int,default=0)
    args=parser.parse_args()
    tool=Path('/home/soclab/tools/verilator-5.040/bin/verilator')
    paths=[Path(__file__),ROOT/'tests/rtl/test_student_mini_p3.py',ROOT/'tests/rtl/test_student_mini_p1.py',ROOT/'tests/rtl/test_p1_litex_b0.py',ROOT/'tests/rtl/test_p1_b2_divider_dot_beat_page_validate_exp_input_visible_meta_validate_recovery.py',ROOT/'tests/rtl/test_p3_litex_b0.py',ROOT/'tests/rtl/test_p3_b12_output_row_base_litex.py',ROOT/'tests/rtl/runner.py',args.vectors.resolve(),tool]
    paths+=list((ROOT/'shared/rtl').glob('*.sv'))+list((ROOT/'shared/rtl').glob('*.svh'))+list((ROOT/'shared/rtl').glob('*.mem'))
    paths += [ROOT/'tests/rtl/test_student_mini_p2.py',ROOT/'tests/rtl/test_p2_b0_timing_foundation.py',ROOT/'tests/rtl/test_p2_litex_b0.py']
    inputs={'files':{str(p):sha(p) for p in paths},'operator':args.operator,'limit':args.limit,'max_threads':2}
    identity=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/rtl'/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'shared/python'),COURSE_VERILATOR_BIN=str(tool),MAKEFLAGS='-j2',
             STUDENT_MINI_VECTORS=str(args.vectors.resolve()),STUDENT_MINI_ACTUAL=str(work/'actual.jsonl'),STUDENT_MINI_LIMIT=str(args.limit))
    started=time.monotonic();result={'status':'HOLD','hardware_complete':False,'input_sha256':identity,'operator':args.operator}
    try:
        with (work/'run.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/f'tests/rtl/test_student_mini_{args.operator}.py')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            print(json.dumps({'work':str(work),'pid':child.pid,'status':'RUNNING'}),flush=True)
            code=child.wait(timeout=1500)
        result['exit_code']=code
        if any(sha(Path(p))!=expected for p,expected in inputs['files'].items()):raise ValueError('inputs changed during replay')
        actual=work/'actual.jsonl'
        rows=[json.loads(line) for line in actual.read_text().splitlines()] if actual.exists() else []
        result.update(records=len(rows),numeric_pass=sum(r.get('numeric_match') is True for r in rows),
                      holds=sum(r['status']=='HOLD' for r in rows),failures=sum(r['status']=='FAIL' for r in rows),
                      reason='RTL numeric replay only; full protocol/primitive witnesses, physical and Nano acceptance remain required')
        if code:
            result['reason']=f'RTL runner exited {code}; inspect SHA-bound run.log'
    except BaseException as exc:
        if 'child' in locals() and child.poll() is None:child.terminate();child.wait(timeout=30)
        result['reason']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        result['elapsed_seconds']=time.monotonic()-started
        result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
        (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(work=str(work),**result),indent=2),flush=True)
    return result.get('exit_code',1)


if __name__=='__main__':raise SystemExit(main())
