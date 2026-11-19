"""Strictly compare the new CPU target transcript after its full completion."""
import hashlib
import json
from pathlib import Path
import sys
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
sys.path.insert(0,str(ROOT/'sources'))
from scripts.assemble_student_mini_cpu_results import parse
from scripts.student_mini_release_records import compare
log=BASE/'runs/cpu-scalar-execute.log'
actual=parse(log.read_text(),1000)
vectors=[json.loads(line) for line in (ROOT/'data/golden/vectors.jsonl').read_text().splitlines()]
records=[dict(ordinal=i,case_id=g['case']['id'],operator=g['case']['operator'],seed=g['seed'],
    observation=a,comparison=compare(g['golden'],a,g['case']['operator'])) for i,(g,a) in enumerate(zip(vectors,actual))]
assert len(records)==1000
summary={}
for op,expected in [('p1',330),('p2',340),('p3',330)]:
    rows=[r for r in records if r['operator']==op];assert len(rows)==expected
    for case in set(r['case_id'] for r in rows):
        assert sorted(r['seed'] for r in rows if r['case_id']==case)==list(range(1,11))
    summary[op]=dict(records=len(rows),matched=sum(r['comparison']['status']=='PASS' for r in rows))
files=[log,BASE/'src/p3_scalar_candidate.c',BASE/'build/cpu-scalar/bios/student_mini_scalar.c',
    BASE/'build/cpu-scalar/soc/software/bios/bios.bin',BASE/'build/cpu-scalar/soc/gateware/obj_dir/Vsim',
    BASE/'build/cpu-scalar/loader.bin',ROOT/'sources/build/vexriscv-profiles/VexRiscv_Full_4k.v']
result=dict(status='TARGET_EXECUTED',by_operator=summary,
    matched=sum(r['comparison']['status']=='PASS' for r in records),
    protocol_qualification='MINI31/32/33 specialized stimuli NOT_RUN; MINI30 status comes from actual DMA adapter',
    bindings={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
(BASE/'runs/cpu-scalar-records.json').write_text(json.dumps(records,indent=2)+'\n')
(BASE/'runs/cpu-scalar-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
