"""Parse preserved real OpenSTA max-slack output; do not rerun or adopt hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.audit_student_mini_cpu_timing import worst_setup


def parse(log,expected):
    chunks=re.split(r'(?m)^CPU_MULT_DRIVE_PROBE strength=(\d+)\s*$',log)
    if chunks[1::2]!=['0','1','2','4']:raise ValueError('four unique ordered strengths required')
    if log.count('CPU_MULT_DRIVE_PROBE_COMPLETE diagnostic_only=1 no_checkpoint_written=1')!=1 or 'Error:' in log:
        raise ValueError('complete successful topology witness required')
    result={}
    for strength,body in zip(chunks[1::2],chunks[2::2]):
        values=re.findall(r'(?m)^worst slack max (-?\d+\.\d+)\s*$',body)
        if len(values)!=1:raise ValueError('one real max-slack measurement required')
        value=float(values[0]);path=worst_setup(body,value)
        if 'execute_to_memory_MUL_HH[26]' not in path['endpoint']:raise ValueError('critical path changed; separate diagnosis required')
        if '_074408_/Y (sky130_fd_sc_hd__a21boi_'+strength+')' not in body:raise ValueError('actual measured drive witness missing')
        result[strength]=dict(wns_ns=value,path=path)
    if abs(result['0']['wns_ns']-expected)>.001:raise ValueError('original checkpoint timing not reproduced')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--placement',type=Path,required=True);args=parser.parse_args()
    packet=args.probe.resolve()/'completion.json';parent=json.loads(packet.read_text())
    log=args.probe.resolve()/'probe.log';place=args.placement.resolve()/'completion.json'
    if (parent['status']!='HOLD' or parent['reason']!='ValueError: incomplete drive probes'
        or parent['artifacts'].get('probe.log')!=sha(log) or parent['bindings'].get(str(place))!=sha(place)):
        raise ValueError('exact immutable parser HOLD required')
    verify(parent['bindings']);placement=json.loads(place.read_text())
    rows=parse(log.read_text(),placement['placement_wns_ns'])
    bindings=dict(parent['bindings']);bindings.update({str(p):sha(p) for p in (Path(__file__),packet,log,place)})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'grading/evidence/student-mini-v1/cpu-drive-diagnostic'/key;out.mkdir(parents=True,exist_ok=False)
    result=dict(status='CPU_DRIVE_DIAGNOSTIC_PARSED',bindings=bindings,measurements=rows,
                physical_evidence_complete=False,formal_baseline=False,hardware_adopted=False,
                one_cell_upsizing_closes_timing=all(row['wns_ns']>=0 for row in [rows['4']]),
                reason='Same saved layout reproduced; stronger output gate improves slack but the multiplier path still fails. This is not legalized or routed evidence.')
    output=out/'audit.json';output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(path=str(output),sha256=sha(output),slacks={s:r['wns_ns'] for s,r in rows.items()},physical_evidence_complete=False)))


if __name__=='__main__':main()
