"""Compare integrated core candidate against same algorithm on original core."""
import hashlib
import json
from pathlib import Path
import re
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
logs=[BASE/'runs/cpu-algorithm-diagnostic.log',BASE/'runs/cpu-rtl-diagnostic.log']
def records(p):
    text=p.read_text()
    assert text.count('STUDENT_NATIVE_CPU_COMPLETE count=11 p1=1 p2=10 p3=40')==1
    rows=[re.sub(r' elapsed_cycles=\d+:\d+','',s) for s in text.splitlines() if s.startswith('STUDENT_NATIVE_TOKEN ')]
    assert len(rows)==11 and 'STUDENT_NATIVE_CPU status=0 count=11' in text
    return rows
assert records(logs[0])==records(logs[1])
cycles=[]
for p in logs:
    m=re.search(r'STUDENT_NATIVE_CPU status=0 count=11 cycles=(\d+):(\d+)',p.read_text());cycles.append((int(m[1])<<32)+int(m[2]))
files=logs+[BASE/'build/cpu-rtl/soc/software/bios/bios.bin',BASE/'build/cpu-rtl/soc/gateware/obj_dir/Vsim',
    BASE/'build/cpu-rtl/soc/gateware/build_sim.sh',BASE/'build/rtl-csa/VexRiscv_Full_4k.v']
result=dict(status='INTEGRATED_CPU_RTL_NATIVE_EXACT_PASS',generation_cycles=cycles,
    same_cycles=cycles[0]==cycles[1],bindings={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    limitation='One actual full-core LLM diagnostic, not complete instruction/protocol/formal equivalence or mapped PPA. CSA has no cycle benefit by design; timing benefit NOT_MEASURED.')
(BASE/'runs/cpu-rtl-comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
