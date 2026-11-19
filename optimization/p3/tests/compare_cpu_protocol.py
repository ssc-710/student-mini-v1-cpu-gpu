"""Check complete protocol stimuli/events plus independent frozen golden payload."""
import hashlib
import json
from pathlib import Path
import re
import sys
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1];run=BASE/'runs/cpu-scalar-protocol'
sys.path.insert(0,str(ROOT/'sources'))
from scripts.student_mini_release_records import compare
vectors=[json.loads(line) for line in (ROOT/'data/golden/vectors.jsonl').read_text().splitlines()]
receipt=json.loads((run/'receipt.json').read_text());records=receipt['records'];assert len(records)==30
golden=json.loads((BASE/'runs/cpu-scalar-comparison.json').read_text());assert golden['matched']==1000
seen=set();counts={}
for row in records:
    key=(row['case_id'],row['seed']);assert key not in seen;seen.add(key)
    assert row['exit_code']==0 and len(row['events'])==1
    event=dict(re.findall(r'(\w+)=(-?\d+)',row['events'][0]));event={k:int(v) for k,v in event.items()}
    assert event['payload_match']==1 and event['completions']==1 and event['stability_violations']==0
    assert event['completions_before_reset']==0
    if row['case_id'].endswith('31'):
        assert event['prob256']==128 and event['stalled_cycles']>0
    elif row['case_id'].endswith('32'):
        assert event['hold']==17 and event['stalled_cycles']>=17*event['accepted_bytes']
    else:
        assert event['reset_after']==2000 and event['reset_cycle']-event['armed_cycle']==2000 and event['lines_after_reset']>0
    log=run/(str(row['ordinal'])+'.log')
    assert hashlib.sha256(log.read_bytes()).hexdigest()==row['log_sha256']
    lines=[line for line in log.read_text().splitlines() if line.startswith('STUDENT_CPU ordinal=0 ')]
    assert len(lines)==1
    payload=dict(re.findall(r'(\w+)=([^ ]*)',lines[0]))
    status={'0':'OK','1':'BAD_DESCRIPTOR','2':'NUMERIC_ERROR','5':'BUS_ERROR'}[payload['status']]
    observed=dict(actual_status=status,primitive=int(payload['primitive']),
        actual_bits=[int(x,16) for x in payload['bits'].split(',') if x],
        selected=[int(x) for x in payload['selected'].split(',') if x])
    assert compare(vectors[row['ordinal']]['golden'],observed,'p3')['status']=='PASS'
    counts[row['case_id']]=counts.get(row['case_id'],0)+1
assert counts=={'P3-MINI-31':10,'P3-MINI-32':10,'P3-MINI-33':10}
result=dict(status='CPU_P3_UART_PROTOCOL_30_PASS',counts=counts,receipt_sha256=hashlib.sha256((run/'receipt.json').read_bytes()).hexdigest(),
    limitation='Current scalar candidate original CPU core UART stream/reset only. No DFI protocol, CSA core or physical mapped netlist qualification. Host expected payload derives from current 1000/1000 frozen-golden comparison.')
(run/'comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
