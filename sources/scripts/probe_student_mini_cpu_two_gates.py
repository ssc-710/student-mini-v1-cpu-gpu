"""Drive-only residual-path experiments following the preserved single-gate diagnosis."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.retry_student_mini_cpu_drive_probe import producer_source


def equivalent_cells(liberty):
    all_signatures=[]
    for base,strengths in [('a21boi',(0,4)),('nor3',(1,2,4))]:
        signatures=[]
        for strength in strengths:
            name='sky130_fd_sc_hd__'+base+'_'+str(strength)
            blocks=re.findall(r'(?ms)^    cell \("'+name+r'"\) \{.*?(?=^    cell |\Z)',liberty)
            if len(blocks)!=1:raise ValueError('unique actual Liberty cell required')
            pins=re.findall(r'(?ms)^        pin \("([^\"]+)"\)\s*\{(.*?)(?=^        (?:pin|pg_pin) |\Z)',blocks[0])
            signature=[]
            for pin,body in pins:
                direction=re.findall(r'\bdirection\s*:\s*"?(input|output)"?\s*;',body)
                function=re.findall(r'\bfunction\s*:\s*"([^"]+)"',body)
                if len(direction)!=1 or (direction==['output'] and len(function)!=1):raise ValueError('explicit pin function required')
                signature.append((pin,direction[0],function))
            expected=['A1','A2','B1_N','Y'] if base=='a21boi' else ['A','B','C','Y']
            if sorted(p[0] for p in signature)!=expected:raise ValueError('actual cell pin contract differs')
            signatures.append(sorted(signature))
        if any(x!=signatures[0] for x in signatures[1:]):raise ValueError('cell functions differ')
        all_signatures.append(signatures[0])
    return all_signatures


def parse_stages(log,expected):
    rows=re.findall(r'(?m)^CPU_TWO_GATE_PROBE stage=(\d+) [^\n]*\nworst slack max (-?\d+\.\d+)\s*$',log)
    if [r[0] for r in rows]!=['0','1','2','4'] or 'Error:' in log:raise ValueError('complete four-stage max-slack measurement required')
    if log.count('CPU_TWO_GATE_PROBE_COMPLETE diagnostic_only=1 no_checkpoint_written=1')!=1:raise ValueError('topology witness missing')
    values={k:float(v) for k,v in rows}
    if not all(math.isfinite(x) for x in values.values()) or abs(values['0']-expected)>.001:raise ValueError('original timing not reproduced')
    if abs(values['1']-(-.354790))>.001:raise ValueError('previous single-gate experiment not reproduced')
    return values


def derive(source,root,hook):
    value=producer_source(source,root,hook)
    marker='def main():'
    if value.count(marker)!=1:raise ValueError('probe main seam changed')
    value=value.replace(marker,'from scripts.probe_student_mini_cpu_two_gates import equivalent_cells as equivalent_drive_cells, parse_stages as parse_probe\n\n\n'+marker)
    marker='(Path(__file__),'
    if value.count(marker)!=1:raise ValueError('probe bindings seam changed')
    return value.replace(marker,marker+"ROOT/'scripts/probe_student_mini_cpu_two_gates.py',")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic',type=Path,required=True);parser.add_argument('--placement',type=Path,required=True)
    args=parser.parse_args();prior=args.diagnostic.resolve();audit=json.loads(prior.read_text());verify(audit['bindings'])
    if audit['status']!='CPU_DRIVE_DIAGNOSTIC_PARSED' or audit['one_cell_upsizing_closes_timing'] is not False:
        raise ValueError('actual insufficient single-gate measurement required')
    if audit['bindings'].get(str(args.placement.resolve()/'completion.json'))!=sha(args.placement.resolve()/'completion.json'):
        raise ValueError('different physical baseline')
    original=ROOT/'scripts/probe_student_mini_cpu_multiplier_drive.py';hook=ROOT/'integration/student-mini/cpu_multiplier_two_gate_probe.tcl'
    paths=[Path(__file__),original,hook,prior,ROOT/'scripts/retry_student_mini_cpu_drive_probe.py']
    bindings={str(p):sha(p) for p in paths}
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-two-gate-drive-launch'/key;work.mkdir(parents=True,exist_ok=False)
    producer=work/'producer.py';producer.write_text(derive(original.read_text(),ROOT,hook));bindings[str(producer)]=sha(producer)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,diagnostic_only=True)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    print(json.dumps(dict(work=str(work),stage='RESIDUAL_GATE_DIAGNOSTIC_QUEUED')),flush=True)
    with (work/'child.log').open('x') as output:
        code=subprocess.call([sys.executable,str(producer),'--placement',str(args.placement.resolve())],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'child.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['child']=rows[-1]
    verify(bindings)
    if not code and result.get('child',{}).get('status')=='CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE':result['status']='CPU_TWO_GATE_DRIVE_DIAGNOSTIC_COMPLETE'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],child=result.get('child'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
