import json
from pathlib import Path
import sys

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/'sources'))
from scripts.assemble_student_mini_cpu_results import parse as cpu_parse
from scripts.assemble_student_mini_gpu_results import parse as gpu_parse
from scripts.student_mini_release_records import compare
vectors=[json.loads(s) for s in (here.parent/'data/golden/vectors.jsonl').read_text().splitlines()]
out=here/'fresh-baselines'
result={}
for name,parser,log in [('gpu',gpu_parse,'gpu-execute.log'),('cpu',cpu_parse,'cpu-console.log')]:
    path=out/log
    if not path.exists():continue
    text=path.read_text(errors='replace')
    try:actual=parser(text,1000)
    except ValueError as e:
        result[name]=dict(complete=False,reason=str(e));continue
    records=[]
    for g,a in zip(vectors,actual):
        c=compare(g['golden'],a,g['case']['operator'])
        records.append(dict(case_id=g['case']['id'],operator=g['case']['operator'],seed=g['seed'],observation=a,comparison=c))
    result[name]=dict(complete=True,records=1000,matched=sum(r['comparison']['status']=='PASS' for r in records),
        mismatches=[dict(case_id=r['case_id'],seed=r['seed'],expected=r['comparison']['expected_status'],actual=r['comparison']['actual_status']) for r in records if r['comparison']['status']!='PASS'],
        protocol_qualification='NOT_RERUN')
    (out/(name+'-results.json')).write_text(json.dumps(records,indent=2)+'\n')
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
