"""Route only the accepted one-buffer CPU placement, preserving every old HOLD."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.route_student_mini_platform import checked_parent
from scripts.continue_student_mini_cpu_request_route import router_source,bound_checker


def actual_checker(parent):
    if checked_parent(parent,'cpu')!=29 or parent.get('one_buffer_topology_checked') is not True:
        raise ValueError('qualified one-buffer 29-macro CPU placement required')
    actual=ROOT/'scripts/resume_student_mini_cpu_read_buffer.py'
    if parent['bindings'].get(str(actual))!=sha(actual): raise ValueError('actual buffer placement producer changed')
    checkers=[Path(p) for p in parent['bindings'] if Path(p).name=='power.tcl' and 'cpu-request-physical-continuation' in p]
    if len(checkers)!=1: raise ValueError('actual supply checker not unique')
    checker=checkers[0];producer=checker.parent/'placement-producer.py'
    bound_checker(parent,checker,producer,'cpu',29)
    return checker,producer


def derive(source,root,checker,producer):
    result=router_source(source,root,checker,producer)
    needle='paths = [Path(__file__),'
    if result.count(needle)!=1: raise ValueError('route source binding seam changed')
    result=result.replace(needle,needle+"ROOT/'scripts/route_student_mini_cpu_read_buffer.py',")
    needle='parent = json.loads(packet.read_text()); count = checked_parent(parent, args.platform)'
    if result.count(needle)!=1: raise ValueError('route parent gate seam changed')
    return result.replace(needle,needle+'\n        from scripts.route_student_mini_cpu_read_buffer import actual_checker\n        actual_checker(parent)')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();placement=args.placement.resolve();packet=placement/'completion.json'
    parent=json.loads(packet.read_text());checker,producer=actual_checker(parent);verify(parent['bindings'])
    original=ROOT/'scripts/route_student_mini_platform.py'
    paths=[Path(__file__),original,ROOT/'scripts/continue_student_mini_cpu_request_route.py',packet,checker,producer]
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-read-buffer-route-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private=work/'producer.py';private.write_text(derive(original.read_text(),ROOT,checker,producer));bindings[str(private)]=sha(private)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='QUALIFIED_CPU_BUFFER_ROUTE_QUEUED')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--placement',str(placement),'--platform','cpu'],
                             cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['child']=rows[-1]
    verify(bindings)
    if code==0 and result.get('child',{}).get('status')=='PLATFORM_ROUTE_STAGE_PASS':
        result['status']='CPU_READ_BUFFER_ROUTE_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return 0 if result['status']=='CPU_READ_BUFFER_ROUTE_STAGE_PASS' else 1


if __name__=='__main__': raise SystemExit(main())
