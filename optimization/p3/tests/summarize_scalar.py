"""Recompute only the summary from fresh executed observations, not target results."""
import hashlib
import json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
run=BASE/'runs/gpu-scalar-algorithm-retry'
records=json.loads((run/'records.json').read_text())
assert len(records)==1000 and [r['ordinal'] for r in records]==list(range(1000))
summary={}
for op in ['p1','p2','p3']:
    rows=[r for r in records if r['operator'].lower()==op]
    summary[op]=dict(records=len(rows),cases=len(set(r['case_id'] for r in rows)),
        matched=sum(r['comparison']['status']=='PASS' for r in rows),
        failures=[dict(case_id=r['case_id'],seed=r['seed'],status=r['comparison']['actual_status']) for r in rows if r['comparison']['status']!='PASS'])
receipt=json.loads((run/'receipt.json').read_text())
receipt['p3_records']=summary['p3']['records'];receipt['by_operator']=summary
receipt['records_sha256']=hashlib.sha256((run/'records.json').read_bytes()).hexdigest()
(run/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(summary,indent=2))
