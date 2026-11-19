"""Bind the CPU's actual negative detailed-placement path to its program ROM."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.student_mini_cpu_rom_cut import rom_parts


def worst_setup(report,wns):
    if type(wns) not in (int,float) or not math.isfinite(wns) or wns>=0:raise ValueError('negative finite setup metric required')
    candidates=[]
    for block in re.findall(r'(?ms)^Startpoint: .*?^\s*-?\d+\.\d+\s+slack \((?:MET|VIOLATED)\)',report):
        fields={name:re.findall(r'^'+name+r': (.+)$',block,re.M) for name in ('Startpoint','Endpoint','Path Group','Path Type')}
        if any(len(v)!=1 for v in fields.values()):raise ValueError('malformed STA path')
        if fields['Path Type']!=['max'] or fields['Path Group']!=['core_clock']:continue
        slack=float(re.findall(r'^\s*(-?\d+\.\d+)\s+slack ',block,re.M)[0])
        candidates.append(dict(startpoint=fields['Startpoint'][0],endpoint=fields['Endpoint'][0],slack_ns=slack,path_group='core_clock'))
    if not candidates:raise ValueError('no core setup path')
    worst=min(candidates,key=lambda p:p['slack_ns'])
    if abs(worst['slack_ns']-wns)>.011:raise ValueError('raw setup path and metric disagree')
    return worst


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placement',type=Path,required=True);parser.add_argument('--mapping',type=Path,required=True)
    args=parser.parse_args();work=args.placement.resolve();mapping=args.mapping.resolve()
    completion=work/'completion.json';parent=json.loads(completion.read_text())
    if parent['status']!='HOLD' or parent['macro_power_connected'] is not True or parent['clock_period_ns']!=10:raise ValueError('observed power-connected CPU timing HOLD required')
    metrics=Path(parent['metrics_directory'])/'3_5_place_dp.json'
    report=Path(parent['reports_directory'])/'3_detailed_place.rpt'
    for path in (metrics,report):
        if parent['artifacts'].get(str(path))!=sha(path):raise ValueError('unbound raw timing artifact')
    mapped=mapping/'mapped.v'
    if parent['bindings'].get(str(mapped))!=sha(mapped):raise ValueError('not this CPU ROM')
    wns=json.loads(metrics.read_text())['detailedplace__timing__setup__ws'];path=worst_setup(report.read_text(),wns)
    _,_,words=rom_parts(mapped.read_text())
    if not path['startpoint'].startswith('VexRiscv.dBus_cmd_payload_size[') or not path['endpoint'].startswith('_5442_['):raise ValueError('CPU path root differs from observed ROM read')
    files=[Path(__file__),ROOT/'scripts/student_mini_cpu_rom_cut.py',completion,metrics,report,mapped]
    bindings={str(p):sha(p) for p in files}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'grading/evidence/student-mini-v1/cpu-timing'/identity;out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(report,out/'worst-path.rpt');shutil.copyfile(metrics,out/'placement-metrics.json')
    result=dict(status='HOLD_NEGATIVE_100MHZ_SETUP',formal_baseline=False,physical_evidence_complete=False,
        clock_period_ns=10,wns_ns=wns,path=path,bindings=bindings,rom_words=len(words),
        diagnosis='Actual worst core-clock path ends at the synchronous 12558-word program ROM output; reset recovery is a separate passing path',
        next_single_variable='Distribute ROM output registers into 512-word banks with captured selector; preserve all ROM words and one-cycle bus-visible latency',
        artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()})
    output=out/'audit.json';output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),sha256=sha(output),wns_ns=wns)))

if __name__=='__main__':main()
