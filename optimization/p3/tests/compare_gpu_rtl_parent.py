"""Compare actual vendor/limb processor RTL on the same device program."""
import hashlib
import json
from pathlib import Path
import re
BASE=Path(__file__).resolve().parents[1]
names=['gpu-vendor-rtl-native-device-bound','gpu-rtl-native-device-bound']
rows=[];tokens=[];images=[];bindings={}
for name in names:
    run=BASE/'runs'/name;receipt=json.loads((run/'receipt.json').read_text());assert receipt['complete'] and receipt['exit_code']==0
    log=run/'execute.log';text=log.read_text()
    assert text.count('STUDENT_NATIVE_GPU_COMPLETE count=11 p1=1 p2=10 p3=40')==1
    token=[s for s in text.splitlines() if s.startswith('STUDENT_NATIVE_TOKEN ')];assert len(token)==11;tokens.append(token)
    match=re.search(r'PERF: instrs=(\d+), cycles=(\d+)',text);assert match
    timing=re.search(r'P3_HOST_TIMING kernel_sync_seconds=([\d.]+) qa_compute_readback_seconds=([\d.]+)',text);assert timing
    image=list((run/'device').glob('*-device.vxbin'));assert len(image)==1
    images.append(hashlib.sha256(image[0].read_bytes()).hexdigest())
    rows.append(dict(run=name,instructions=int(match[1]),aggregate_cycles=int(match[2]),
        kernel_sync_wall_seconds=float(timing[1]),process_wall_seconds=receipt['wall_seconds'],device_vxbin_sha256=images[-1]))
    bindings[str(log.relative_to(BASE))]=hashlib.sha256(log.read_bytes()).hexdigest()
assert tokens[0]==tokens[1] and rows[0]['instructions']==rows[1]['instructions']
assert images[0]==images[1],'Not the same actual device executable; do not attribute cycles to RTL'
result=dict(status='VENDOR_LIMB_SAME_DEVICE_PROGRAM_EXACT_PASS',records=rows,
    rtl_cycle_speedup=rows[0]['aggregate_cycles']/rows[1]['aggregate_cycles'],bindings=bindings,
    limitation='One processor RTL session per variant, not full AFU/fault/protocol. Wall times are simulator implementation cost, not chip performance. No full-chip physical clock qualification.')
(BASE/'runs/gpu-rtl-parent-comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
