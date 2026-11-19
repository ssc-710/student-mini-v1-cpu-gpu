"""DFI candidate route continuation with an immediate post-CTS stop gate."""
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
from scripts.continue_student_mini_cpu_request_route import router_source,continuation_source
from scripts.student_mini_route_cts_gate import inject


def guarded_router_source(source,root,checker,producer):
    value=inject(router_source(source,root,checker,producer))
    needle='paths = [Path(__file__),'
    return value.replace(needle,needle+"ROOT/'scripts/continue_student_mini_cpu_dfi_route.py',",1)


def dfi_continuation_source(source,root,router):
    value=continuation_source(source,root,router)
    changes={
        "'CPU_ROM_REQUEST_PHYSICAL_PREFLIGHT_STAGE_PASS'":"'CPU_DFI_OUTPUT_PHYSICAL_PREFLIGHT_STAGE_PASS'",
        "parent.get('read_latency_cycles') != 2:":"parent.get('read_latency_cycles') != 2 or parent.get('dfi_output_latency_cycles') != 1:",
        "'build/student-mini/cpu-request-route-continuation'":"'build/student-mini/cpu-dfi-route-continuation'",
        'paths = [Path(__file__),':"paths = [Path(__file__),ROOT/'scripts/continue_student_mini_cpu_dfi_route.py',",
    }
    for old,new in changes.items():
        if value.count(old)!=1:raise ValueError('DFI route parent seam changed')
        value=value.replace(old,new)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-continuation',type=Path,required=True);args=parser.parse_args()
    physical=args.physical_continuation.resolve()
    original=ROOT/'scripts/continue_student_mini_platform_route.py';router=ROOT/'scripts/route_student_mini_platform.py'
    checker=physical/'power.tcl';placement=physical/'placement-producer.py'
    paths=[Path(__file__),original,router,checker,placement,physical/'inputs.json',
           ROOT/'scripts/student_mini_route_cts_gate.py',ROOT/'scripts/continue_student_mini_cpu_request_route.py']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-route-launch'/key;work.mkdir(parents=True,exist_ok=False)
    private_router=work/'route-producer.py';private_router.write_text(guarded_router_source(router.read_text(),ROOT,checker,placement))
    private=work/'producer.py';private.write_text(dfi_continuation_source(original.read_text(),ROOT,private_router))
    bindings.update({str(p):sha(p) for p in (private_router,private)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='WAITING_FOR_DFI_PHYSICAL_PREFLIGHT')),flush=True)
    with (work/'child.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--physical-continuation',str(physical),'--platform','cpu'],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='PLATFORM_ROUTING_CONTINUATION_STAGE_PASS':
        result['status']='CPU_DFI_ROUTE_LAUNCH_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
