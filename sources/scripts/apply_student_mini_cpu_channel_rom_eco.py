"""Adopt only the measured minimum effective ROM gate drive on the wider die."""
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
from scripts.retry_student_mini_route import verify
from scripts.resume_student_mini_interrupted import replace_once


def parse_single(log,expected):
    if log.splitlines().count('CPU_DRIVE_ECO_COMPLETE gates=1 macros=29 topology_preserved=1')!=1:
        raise ValueError('actual one-gate topology witness required')
    rows=re.findall(r'(?m)^CPU_DRIVE_ECO stage=(original|legalized)\nworst slack max (-?\d+\.\d+)\s*$',log)
    if [s for s,v in rows]!=['original','legalized'] or '[ERROR' in log or 'Error:' in log:
        raise ValueError('actual legal placement/timing reports required')
    if abs(float(rows[0][1])-expected)>.001:raise ValueError('original timing not reproduced')
    result=float(rows[1][1])
    if result<0:raise ValueError('legalized ROM gate ECO fails 100 MHz: '+str(result))
    return result


def sources(producer,hook,root,hook_path):
    changes={
        'ROOT = Path(__file__).resolve().parents[1]':'ROOT = Path('+repr(str(root))+')',
        'from scripts.probe_student_mini_cpu_two_gates import equivalent_cells':
            'from scripts.probe_student_mini_cpu_channel_rom_drive import equivalent_cells',
        "'CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE'":"'CPU_CHANNEL_ROM_DRIVE_DIAGNOSTIC_COMPLETE'",
        "probe['worst_slack_ns_by_strength']['4']":"probe['worst_slack_ns_by_strength']['1']",
        "hook = ROOT/'integration/student-mini/cpu_multiplier_drive_eco.tcl'":'hook = Path('+repr(str(hook_path))+')',
        "paths = [Path(__file__),":"paths = [Path(__file__), ROOT/'scripts/apply_student_mini_cpu_channel_rom_eco.py', ROOT/'scripts/apply_student_mini_cpu_drive_eco.py', ROOT/'scripts/probe_student_mini_cpu_channel_rom_drive.py',",
        "parse_eco((work/'eco.log').read_text(), parent['placement_wns_ns'])":"parse_single((work/'eco.log').read_text(), parent['placement_wns_ns'])",
        'def main():':'from scripts.apply_student_mini_cpu_channel_rom_eco import parse_single\n\ndef main():',
        'Two equivalent drive changes legalized':'One equivalent ROM gate drive change legalized',
    }
    for old,new in changes.items():producer=replace_once(producer,old,new)
    for old,new in {
        '_074408_ sky130_fd_sc_hd__a21boi_0 _096034_ sky130_fd_sc_hd__nor3_1':'_125420_ sky130_fd_sc_hd__o21ai_0',
        '_074408_ sky130_fd_sc_hd__a21boi_4 _096034_ sky130_fd_sc_hd__nor3_4':'_125420_ sky130_fd_sc_hd__o21ai_1',
        'replace_cell _074408_ sky130_fd_sc_hd__a21boi_4\nreplace_cell _096034_ sky130_fd_sc_hd__nor3_4':'replace_cell _125420_ sky130_fd_sc_hd__o21ai_1',
        'gates=2 macros=29':'gates=1 macros=29',
    }.items():hook=replace_once(hook,old,new)
    return producer,hook


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    args=parser.parse_args();packet=args.placement.resolve()/'completion.json';proof=args.probe.resolve()/'completion.json'
    parent=json.loads(packet.read_text());probe=json.loads(proof.read_text())
    if (parent['geometry']['gap']!=160 or probe['status']!='CPU_CHANNEL_ROM_DRIVE_DIAGNOSTIC_COMPLETE'
        or probe['worst_slack_ns_by_strength']['1']<0 or probe['bindings'].get(str(packet))!=sha(packet)):
        raise ValueError('same wider die and positive actual single-gate diagnostic required')
    verify(parent['bindings']);verify(probe['bindings'])
    original=ROOT/'scripts/apply_student_mini_cpu_drive_eco.py';hook_source=ROOT/'integration/student-mini/cpu_multiplier_drive_eco.tcl'
    bindings={str(p):sha(p) for p in (Path(__file__),packet,proof,original,hook_source)}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-channel-rom-eco-launch'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';hook=work/'eco.tcl'
    body,tcl=sources(original.read_text(),hook_source.read_text(),ROOT,hook)
    producer.write_text(body);hook.write_text(tcl)
    bindings.update({str(p):sha(p) for p in (producer,hook)})
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='SINGLE_ROM_GATE_LEGALIZATION_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),'--placement',str(args.placement.resolve()),'--probe',str(args.probe.resolve())],
                             cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    verify(bindings);rows=[json.loads(line) for line in (work/'child.log').read_text().splitlines() if line.startswith('{')]
    if rows:result['child']=rows[-1]
    if not code and result.get('child',{}).get('status')=='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS':result['status']='CPU_CHANNEL_SINGLE_GATE_ECO_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
