"""Adopt only a reproduced setup/hold-safe single-buffer bypass in a new route."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify,execute_locked_route
from scripts.route_student_mini_cpu_drive_eco import derive as eco_route
from scripts.route_student_mini_platform import nonnegative
from scripts.probe_student_mini_cpu_cts_buffer import parse,check_buffer
from scripts.resume_student_mini_interrupted import replace_once


def eligible(proof):
    if (proof.get('status')!='CPU_CTS_BUFFER_DIAGNOSTIC_COMPLETE' or proof.get('next_adoption_eligible') is not True
        or proof.get('diagnostic_only') is not True or proof.get('physical_evidence_complete') is not False):
        raise ValueError('complete diagnostic, not claimed physical acceptance, required')
    original=proof['measurements']['original'];changed=proof['measurements']['single_buffer_bypassed']
    if abs(original['setup_ns']+.130249)>1e-6:raise ValueError('different CTS parent')
    for name in ('setup_ns','hold_ns'):nonnegative(changed[name],'buffer diagnostic '+name)
    return changed


def checked(prior_path,proof_path):
    prior=json.loads(prior_path.read_text());proof=json.loads(proof_path.read_text());eligible(proof)
    if (prior['status']!='HOLD' or prior['platform']!='cpu' or prior['clock_period_ns']!=10
        or abs(prior['cts_wns_ns']+.130249)>1e-6 or proof['bindings'].get(str(prior_path))!=sha(prior_path)):
        raise ValueError('diagnostic and original 100 MHz route do not match')
    verify(prior['bindings']);verify(proof['bindings'])
    log=proof_path.parent/'probe.log'
    if proof['artifacts'].get('probe.log')!=sha(log) or parse(log.read_text(),prior['cts_wns_ns'])!=proof['measurements']:
        raise ValueError('raw diagnostic report differs')
    return prior,proof


def adoption_hook(source):
    if 'write_db' in source or 'write_sdc' in source or 'remove_buffers $cells' not in source:
        raise ValueError('immutable single-buffer diagnostic hook required')
    return source+'\nputs "CPU_CTS_BUFFER_ADOPTION_SAVING_NEW_CHECKPOINT"\ncheck_placement -verbose\nwrite_db $::env(MINI_OUTPUT)/4_1_cts.odb\nwrite_sdc $::env(MINI_OUTPUT)/4_cts.sdc\n'


def adopt(prior_path,proof_path,results,work,bindings,heartbeat):
    prior,proof=checked(prior_path,proof_path)
    old=Path(prior['result_directory'])
    if results.resolve()==old.resolve() or results.parent!=old.parent:
        raise ValueError('new same-top route directory required; never overwrite parent')
    hook_source=ROOT/'integration/student-mini/cpu_cts_single_buffer_probe.tcl'
    if proof['bindings'].get(str(hook_source))!=sha(hook_source):raise ValueError('diagnostic hook changed')
    hook=work/'adopt-single-buffer.tcl';hook.write_text(adoption_hook(hook_source.read_text()))
    platform=Path('/home/soclab/src/orfs-clean-aabf2a/flow/platforms/sky130hd')
    liberty=platform/'lib/sky130_fd_sc_hd__tt_025C_1v80.lib'
    macro=Path(re.findall(r'^export ADDITIONAL_LIBS = (.+)$',Path(prior['config']).read_text(),re.M)[0])
    check_buffer(liberty.read_text())
    bindings.update(proof['bindings']);bindings.update({str(p):sha(p) for p in (prior_path,proof_path,hook)})
    verify(bindings)
    command=['env',f'MINI_SC_LIB={liberty}',f'MINI_MACRO_LIB={macro}',f'MINI_ODB={old}/4_1_cts.odb',
        f'MINI_SDC={old}/4_cts.sdc',f'MINI_RC={platform}/setRC.tcl',f'MINI_OUTPUT={results}',
        '/home/soclab/.local/bin/openroad','-exit',str(hook)]
    log=work/'adopt-single-buffer.log'
    if execute_locked_route(command,log,240,lambda _:heartbeat('ADOPT_EXACT_SINGLE_BUFFER')):
        raise ValueError('buffer adoption failed; no routing authorized')
    measured=parse(log.read_text(),prior['cts_wns_ns'])
    if measured!=proof['measurements']:raise ValueError('adoption did not reproduce diagnostic timing')
    eligible(dict(proof,measurements=measured))
    if log.read_text().splitlines().count('CPU_CTS_BUFFER_ADOPTION_SAVING_NEW_CHECKPOINT')!=1:
        raise ValueError('new checkpoint marker missing')
    for name in ('4_1_cts.odb','4_cts.sdc'):
        if not (results/name).is_file() or not (results/name).stat().st_size:raise ValueError('adopted checkpoint absent')
    verify(bindings)
    return dict(measurements=measured,diagnostic_sha256=sha(proof_path),setup_ns=measured['single_buffer_bypassed']['setup_ns'],
        hold_ns=measured['single_buffer_bypassed']['hold_ns'],removed_buffers=1,physical_evidence_complete=False)


def derive(source,root,prior,proof):
    source=eco_route(source,root)
    source=replace_once(source,'\ndef main():\n','\nfrom scripts.route_student_mini_cpu_single_buffer import adopt\n\ndef main():\n')
    source=replace_once(source,'paths = [Path(__file__),',
        f"paths = [Path(__file__),ROOT/'scripts/route_student_mini_cpu_single_buffer.py',Path({str(prior)!r}),Path({str(proof)!r}),")
    needle="            stages = [('do-4_1_cts', 1800), ('do-4_cts', 120), ('do-5_1_grt', 1800),"
    source=replace_once(source,needle,
        f"            result['clock_buffer_adoption'] = adopt(Path({str(prior)!r}),Path({str(proof)!r}),results,work,bindings,heartbeat)\n"
        "            stages = [('do-4_cts', 120), ('do-5_1_grt', 1800),")
    needle="            for name in ('6_final.def', '6_final.v', '6_final.sdc', '6_final.spef', '6_final.odb'):"
    return replace_once(source,needle,
        "            result['final_hold_slack_ns'] = nonnegative(json.loads((logs/'6_report.json').read_text()).get('finish__timing__hold__ws'), 'final hold slack')\n"+needle)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-route',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    args=parser.parse_args();prior_path=args.prior_route.resolve()/'completion.json';proof_path=args.probe.resolve()/'completion.json'
    prior,proof=checked(prior_path,proof_path)
    original=ROOT/'scripts/route_student_mini_platform.py'
    bindings=dict(proof['bindings']);bindings.update({str(p):sha(p) for p in (Path(__file__),original,prior_path,proof_path)})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-one-buffer-route-launch'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT,prior_path,proof_path));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
        single_variable='bypass delaybuf_3_core_clock only',constraints_changed=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='QUALIFIED_SINGLE_BUFFER_ROUTE_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),'--platform','cpu','--placement',prior['placement']],
            cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    rows=[json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and rows and rows[-1]['status']=='PLATFORM_ROUTE_STAGE_PASS':
        packet=Path(rows[-1]['work'])/'completion.json';child=json.loads(packet.read_text())
        verify(child['bindings']);bindings.update(child['bindings']);bindings[str(packet)]=sha(packet)
        result['status']='CPU_SINGLE_BUFFER_ROUTE_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return 0 if result['status']=='CPU_SINGLE_BUFFER_ROUTE_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
