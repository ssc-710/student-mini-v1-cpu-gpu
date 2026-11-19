"""Summarize the complete alternating five-pair same-binary CPU experiment."""
import hashlib
import json
from pathlib import Path
import re
import statistics
BASE=Path(__file__).resolve().parents[1]
run=BASE/'runs/cpu-ablation-retry'
binding=json.loads((run/'binding.json').read_text())
rows=[];reference=None
for i in range(10):
    mode=i%2;folder=run/f'mode-{i:02d}-{mode}';log=folder/'execute.log';text=log.read_text()
    assert text.count('STUDENT_NATIVE_CPU_COMPLETE count=11 p1=1 p2=10 p3=40')==1
    assert f'P3_ABLATION mode={mode} ' in text
    tokens=[re.sub(r' elapsed_cycles=\d+:\d+','',s) for s in text.splitlines() if s.startswith('STUDENT_NATIVE_TOKEN ')]
    assert len(tokens)==11
    if reference is None:reference=tokens
    assert tokens==reference
    m=re.search(r'STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+)',text);assert m
    cycles=(int(m[1])<<32)+int(m[2])
    m=re.search(r'STUDENT_NATIVE_OPERATOR op=3 cycles=(\d+):(\d+)',text);assert m
    receipt=json.loads((folder/'execute.receipt.json').read_text())
    rows.append(dict(sequence=i,mode=mode,cycles=cycles,p3_cycles=(int(m[1])<<32)+int(m[2]),
        process_wall_seconds=receipt['elapsed_seconds'],log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
summary={}
for mode in [0,1]:
    selected=[r for r in rows if r['mode']==mode]
    summary[str(mode)]={key:dict(median=statistics.median(r[key] for r in selected),
        min=min(r[key] for r in selected),max=max(r[key] for r in selected)) for key in ['cycles','p3_cycles','process_wall_seconds']}
result=dict(status='SAME_BINARY_FIVE_PAIR_NATIVE_EXACT_PASS',summary=summary,records=rows,
    generation_speedup=summary['0']['cycles']['median']/summary['1']['cycles']['median'],
    p3_speedup=summary['0']['p3_cycles']['median']/summary['1']['p3_cycles']['median'],
    binding=binding,limitation='Diagnostic UART mode, not final clean-mode performance. Same core/ELF/ROM, expert executed footprints differ. No physical clock qualification.')
(run/'comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
