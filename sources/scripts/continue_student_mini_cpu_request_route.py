"""Route the request-cut CPU only after its exact placement passes 100 MHz."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def bound_checker(parent,checker,producer,platform,count):
    if platform!='cpu' or count!=29:raise ValueError('29-macro CPU only')
    for path in (checker,producer):
        if parent['bindings'].get(str(path))!=sha(path):raise ValueError('current placement checker/producer not bound')
    values=[]
    for node in ast.walk(ast.parse(producer.read_text())):
        if (isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and n.id=='checker' for n in node.targets)
            and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='Path'
            and len(node.value.args)==1 and isinstance(node.value.args[0],ast.Constant)):
            values.append(node.value.args[0].value)
    if values!=[str(checker)]:raise ValueError('checker is not the one actually executed by this placement')
    return [checker]


def router_source(source,root,checker,producer):
    edits={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_request_route.py',ROOT/'scripts/route_student_mini_platform.py',",
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('request route source seam changed')
        source=source.replace(old,new)
    begin=source.index('        checker_names = ')
    end=source.index('        if len(checkers) != 1:',begin)
    source=source[:begin]+('        from scripts.continue_student_mini_cpu_request_route import bound_checker\n'
        '        checkers = bound_checker(parent,Path('+repr(str(checker))+'),Path('+repr(str(producer))+'),args.platform,count)\n')+source[end:]
    return source


def continuation_source(source,root,router):
    edits={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        "router = ROOT/'scripts/route_student_mini_platform.py'":'router = Path('+repr(str(router))+')',
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_request_route.py',ROOT/'scripts/continue_student_mini_platform_route.py',",
        "'CPU_TAG_PHYSICAL_PREFLIGHT_STAGE_PASS'":"'CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS'",
        "    child = parent.get('placement', {})":"    if platform != 'cpu' or parent.get('read_latency_cycles') != 2:\n        raise ValueError('new two-edge CPU only')\n    child = parent.get('placement', {})",
        "'build/student-mini/platform-route-continuation'":"'build/student-mini/cpu-request-route-continuation'",
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError('request route continuation seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--physical-continuation',type=Path,required=True)
    args=parser.parse_args();physical=args.physical_continuation.resolve()
    original=ROOT/'scripts/continue_student_mini_platform_route.py';router=ROOT/'scripts/route_student_mini_platform.py'
    checker=physical/'power.tcl';placement=physical/'placement-producer.py'
    paths=[Path(__file__),original,router,physical/'inputs.json',checker,placement]
    bindings={str(p):sha(p) for p in paths};key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-request-route-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private_router=work/'route-producer.py';private_router.write_text(router_source(router.read_text(),ROOT,checker,placement))
    continuation=work/'producer.py';continuation.write_text(continuation_source(original.read_text(),ROOT,private_router))
    bindings.update({str(p):sha(p) for p in (private_router,continuation)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_NEW_CPU_PHYSICAL_PREFLIGHT')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(continuation),'--physical-continuation',str(physical),'--platform','cpu'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='PLATFORM_ROUTING_CONTINUATION_STAGE_PASS':
        packet=Path(result['child']['work'])/'completion.json';child=json.loads(packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(packet)]=sha(packet)
        result['status']='CPU_REQUEST_ROUTING_CONTINUATION_STAGE_PASS'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return 0 if result['status']=='CPU_REQUEST_ROUTING_CONTINUATION_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
