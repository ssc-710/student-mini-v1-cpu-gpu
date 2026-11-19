"""Check newly integrated processor RTL output against the executed SimX candidate."""
import hashlib
import json
from pathlib import Path
import re
import argparse
BASE=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--run-id',default='gpu-rtl-native-stub-retry');args=parser.parse_args()
assert '/' not in args.run_id and '\\' not in args.run_id and args.run_id not in ['.','..']
paths=[BASE/'runs/gpu-algorithm-abs-fix/execute.log',BASE/'runs'/args.run_id/'execute.log']
rows=[];perf=[]
for path in paths:
    text=path.read_text()
    assert text.count('STUDENT_NATIVE_GPU_COMPLETE count=11 p1=1 p2=10 p3=40')==1
    assert text.count('STUDENT_NATIVE_GPU status=0 count=11')==1
    tokens=[s for s in text.splitlines() if s.startswith('STUDENT_NATIVE_TOKEN ')]
    assert len(tokens)==11;rows.append(tokens)
    m=re.search(r'PERF: instrs=(\d+), cycles=(\d+)',text);assert m
    perf.append(dict(instructions=int(m[1]),cycles=int(m[2])))
assert rows[0]==rows[1]
assert perf[0]['instructions']==perf[1]['instructions']
result=dict(status='INTEGRATED_GPU_RTLSIM_NATIVE_EXACT_PASS',simx=perf[0],rtlsim=perf[1],
    aggregate_cycle_relative_difference=abs(perf[0]['cycles']-perf[1]['cycles'])/perf[0]['cycles'],
    bindings={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    limitation='One processor RTL native session, not full AFU/platform fault/protocol/all-case coverage or official model_parity gate. Baseline RTL performance NOT_RUN.')
(BASE/'runs'/args.run_id/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
