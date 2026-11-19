"""Read-only post-audit of actual fault traffic and device provenance."""
import hashlib
import json
from pathlib import Path
import re
BASE=Path(__file__).resolve().parents[1]
run=BASE/'runs/gpu-fault-rtl-ten-seeds';path=run/'receipt.json'
r=json.loads(path.read_text());assert r['status']=='SELECTED_P3_PROCESSOR_RTL_FAULT_PASS'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,digest in r['bindings'].items():assert sha(Path(name))==digest,name
assert len(r['records'])==11
faults=[row for row in r['records'] if row['case_id']=='P3-MINI-30']
assert sorted(row['seed'] for row in faults)==list(range(1,11))
for row in r['records']:
    assert row['comparison']['status']=='PASS'
    for name,digest in row['artifacts'].items():assert sha(Path(name))==digest,name
    folder=run/(row['case_id']+'-seed-'+str(row['seed']));text=(folder/'execute.log').read_text()
    assert len(re.findall(r'^STUDENT_GPU_COMPLETE start=0 count=1$',text,re.M))==1
    captures=list((folder/'device').glob('*-binding.json'));assert captures
    for capture in captures:
        m=json.loads(capture.read_text());assert m['status']=='ACTUAL_JIT_PACKER_OUTPUT'
        assert sha(Path(m['packer']))==m['packer_sha256']
        for f in m['files']:assert sha(capture.parent/f['path'])==f['sha256']
    if row['case_id']=='P3-MINI-30':
        markers=['P3_FAULT_REQUEST ','P3_MEMORY_UNMAPPED_READ ','P3_FAULT_RESPONSE ','P3_FAULT_STATUS busy=0 fault=1','P3_LAUNCH_STATUS value=1 fault=1','STUDENT_GPU ordinal=0 status=6 primitive=0 bits= selected=']
        assert all(text.count(marker)==1 for marker in markers)
        positions=[text.index(marker) for marker in markers];assert positions==sorted(positions)
        assert row['observation']['actual_status']=='BUS_ERROR'
    else:
        assert 'P3_FAULT_REQUEST ' not in text and row['observation']['actual_status']=='OK'
out=run/'independent-post-audit.json';assert not out.exists()
out.write_text(json.dumps(dict(status='TEN_SEED_FAULT_TRAFFIC_ORDER_AND_ARTIFACT_AUDIT_PASS',
    receipt_sha256=sha(path),limitation='Post-run independent ordering/hash audit; processor boundary only, not AFU or protocol cases31-33.'),indent=2)+'\n')
print('TEN_SEED_FAULT_POST_AUDIT_PASS')
