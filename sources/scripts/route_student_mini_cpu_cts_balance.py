"""One CTS delay-buffer insertion change; keep all setup/hold/route gates."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.route_student_mini_cpu_drive_eco import derive as eco_route, eco_checker
from scripts.route_student_mini_platform import nonnegative


def config(source):
    if any(key in source for key in ('CTS_ARGS', 'CTS_CLUSTER', 'CTS_BUF_', 'SKIP_CTS_REPAIR_TIMING')):
        raise ValueError('only observed default CTS configuration supported')
    return source+'\n# One physical feasibility variable; timing constraints unchanged.\nexport CTS_ARGS = -sink_clustering_enable -repair_clock_nets -delay_buffer_derate 0.5\n'


def check_hold(metrics):
    return nonnegative(metrics.get('cts__timing__hold__ws'), 'CTS hold slack')


def derive(source, root):
    source = eco_route(source, root)
    old = "config = work/'config.mk'; shutil.copyfile(parent['config'], config); bindings[str(config)] = sha(config)"
    new = "config = work/'config.mk'; config.write_text(cts_config(Path(parent['config']).read_text())); bindings[str(config)] = sha(config)"
    if source.count(old) != 1: raise ValueError('route config seam changed')
    source = source.replace(old,new)
    source = source.replace('def main():', 'from scripts.route_student_mini_cpu_cts_balance import config as cts_config, check_hold\n\ndef main():',1)
    needle = '                    check_cts(cts_metrics)'
    if source.count(needle) != 1: raise ValueError('strict CTS gate seam changed')
    source = source.replace(needle, needle+"\n                    result['cts_hold_slack_ns'] = check_hold(cts_metrics)")
    return source.replace('paths = [Path(__file__),', "paths = [Path(__file__), ROOT/'scripts/route_student_mini_cpu_cts_balance.py',",1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-route',type=Path,required=True)
    args = parser.parse_args(); packet = args.prior_route.resolve()/'completion.json'
    prior = json.loads(packet.read_text())
    report = Path(prior['reports_directory'])/'4_cts_final.rpt'
    if (prior['status'] != 'HOLD' or prior['clock_period_ns'] != 10 or prior['platform'] != 'cpu'
        or abs(prior.get('cts_wns_ns',0)-(-.130249)) > .000001
        or prior['artifacts'].get(str(report)) != sha(report)
        or 'Endpoint: serial_source_data[7]' not in report.read_text()):
        raise ValueError('actual CTS output-path HOLD required')
    verify(prior['bindings']); placement = Path(prior['placement'])
    parent = json.loads((placement/'completion.json').read_text()); eco_checker(parent)
    config(Path(parent['config']).read_text())
    original = ROOT/'scripts/route_student_mini_platform.py'
    files = [Path(__file__),original,ROOT/'scripts/route_student_mini_cpu_drive_eco.py',
        ROOT/'scripts/student_mini_route_cts_gate.py', packet,report,
        Path('/home/soclab/src/OpenROAD-clean-90e29809/src/cts/README.md')]
    bindings = {str(p):sha(p) for p in files}
    key = hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work = ROOT/'build/student-mini/cpu-cts-balance'/key; work.mkdir(parents=True,exist_ok=False)
    producer = work/'producer.py'; producer.write_text(derive(original.read_text(),ROOT)); bindings[str(producer)] = sha(producer)
    result = dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        single_variable='CTS delay_buffer_derate 1.0 -> 0.5',precision_changed=False,constraints_changed=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n'); verify(bindings)
    print(json.dumps(dict(work=str(work),stage='CTS_BALANCE_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code = subprocess.call([sys.executable,str(producer),'--platform','cpu','--placement',str(placement)],
            cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    rows = [json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows: result['child'] = rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status') == 'PLATFORM_ROUTE_STAGE_PASS':
        result['status'] = 'CPU_CTS_BALANCE_ROUTE_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__ == '__main__': raise SystemExit(main())
