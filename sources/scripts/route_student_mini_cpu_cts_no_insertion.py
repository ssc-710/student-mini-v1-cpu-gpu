"""Disable CTS insertion-delay balancing only, with unchanged real STA gates."""
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
from scripts.route_student_mini_cpu_cts_balance import derive as balanced_route,config as checked_default
from scripts.route_student_mini_cpu_drive_eco import eco_checker
from scripts.resume_student_mini_interrupted import replace_once


def config(source):
    checked_default(source)
    return source+'\n# CTS construction policy only; SDC and actual STA delays unchanged.\nexport CTS_ARGS = -sink_clustering_enable -repair_clock_nets -no_insertion_delay\n'


def derive(source,root):
    source=balanced_route(source,root)
    source=replace_once(source,
        'from scripts.route_student_mini_cpu_cts_balance import config as cts_config, check_hold',
        'from scripts.route_student_mini_cpu_cts_no_insertion import config as cts_config\nfrom scripts.route_student_mini_cpu_cts_balance import check_hold')
    return replace_once(source,'paths = [Path(__file__),',
        "paths = [Path(__file__), ROOT/'scripts/route_student_mini_cpu_cts_no_insertion.py',")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-route',type=Path,required=True)
    args=parser.parse_args();packet=args.prior_route.resolve()/'completion.json'
    prior=json.loads(packet.read_text());verify(prior['bindings'])
    report=Path(prior['reports_directory'])/'4_cts_final.rpt'
    log=args.prior_route.resolve()/'do-4_1_cts.log'
    if (prior['status']!='HOLD' or abs(prior['cts_wns_ns']+.130249)>1e-6
        or prior['clock_period_ns']!=10 or prior['artifacts'].get(str(report))!=sha(report)
        or prior['artifacts'].get(str(log))!=sha(log) or '-delay_buffer_derate 0.5' not in log.read_text()
        or 'Total number of delay buffers: 4' not in log.read_text()):
        raise ValueError('actual unchanged CTS derate experiment required')
    placement=Path(prior['placement']);eco_checker(json.loads((placement/'completion.json').read_text()))
    original=ROOT/'scripts/route_student_mini_platform.py'
    toolsource=Path('/home/soclab/src/OpenROAD-clean-90e29809/src/cts/src')
    files=[Path(__file__),original,ROOT/'scripts/route_student_mini_cpu_cts_balance.py',
        ROOT/'scripts/route_student_mini_cpu_drive_eco.py',packet,report,log,
        toolsource/'LatencyBalancer.cpp',toolsource/'TritonCTS.cpp',toolsource/'TritonCTS.tcl']
    bindings={str(p):sha(p) for p in files}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-cts-no-insertion'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        single_variable='CTS insertion-delay balancing enabled -> disabled',precision_changed=False,constraints_changed=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),stage='CTS_NO_INSERTION_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),'--platform','cpu','--placement',str(placement)],
            cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    rows=[json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='PLATFORM_ROUTE_STAGE_PASS':result['status']='CPU_CTS_NO_INSERTION_ROUTE_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
