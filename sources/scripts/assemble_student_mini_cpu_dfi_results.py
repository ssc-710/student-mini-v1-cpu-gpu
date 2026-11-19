"""Publish complete new DFI-boundary observations, retaining all release HOLDs."""
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


def derive(source,root):
    changes={
        'ROOT=Path(__file__).resolve().parents[1]':'ROOT=Path('+repr(str(root))+')',
        "'CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'":"'CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'",
        'paths=[Path(__file__),receipt,':"paths=[Path(__file__),ROOT/'scripts/assemble_student_mini_cpu_dfi_results.py',ROOT/'scripts/assemble_student_mini_cpu_request_results.py',receipt,",
        'read_latency_cycles=2,':'read_latency_cycles=2,dfi_output_latency_cycles=1,native_read_valid_added_cycles=1,',
        '1000 complete current two-edge-ROM CPU observations and fresh counters; full protocol, selected model, physical and release gates remain HOLD':
        '1000 complete current two-edge-ROM, common DFI output and aligned read-valid CPU observations with fresh counters; full protocol, selected model, physical and release gates remain HOLD',
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('DFI result assembler seam changed')
        source=source.replace(old,new)
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,required=True);parser.add_argument('--vectors',type=Path,required=True)
    args=parser.parse_args();source=args.replay.resolve();receipt=source/'completion.json'
    parent=json.loads(receipt.read_text())
    if (parent['status']!='CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'
        or parent.get('independent_external_memory') is not True
        or parent.get('dfi_output_latency_cycles')!=1
        or parent['transcript_join']['baseline_records']!=1000):raise ValueError('complete fresh actual DFI replay required')
    verify(parent['bindings'])
    mapping=json.loads((Path(parent['parent_mapping'])/'completion.json').read_text())
    if mapping.get('native_read_valid_added_cycles')!=1:raise ValueError('all three read-valid paths must be aligned')
    original=ROOT/'scripts/assemble_student_mini_cpu_request_results.py'
    bindings=dict(parent['bindings'])
    for name,digest in parent['artifacts'].items():
        path=source/name
        if sha(path)!=digest:raise ValueError('actual DFI replay artifact changed')
        bindings[str(path)]=digest
    bindings.update({str(p):sha(p) for p in (Path(__file__),original,receipt,args.vectors.resolve())})
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-dfi-results'/key;work.mkdir(parents=True,exist_ok=False)
    compact=work/'qualified';compact.mkdir();records=compact/'uart-records.log'
    with (source/'console.log').open() as raw,records.open('x') as output:
        for line in raw:
            if line.startswith(('STUDENT_CPU ','STUDENT_CPU_','STUDENT_NATIVE_','CPU_BOUNDARY_REPLAY_COMPLETE ')):output.write(line)
    measured=compact/'measurements.json';measured.write_text(json.dumps(parent['transcript_join'],indent=2)+'\n')
    bindings.update({str(p):sha(p) for p in (records,measured)})
    qualified=dict(parent,bindings=dict(bindings),source_replay=str(source),fresh_rtl_execution_performed=False,
        source_receipt_sha256=sha(receipt),artifacts={p.name:sha(p) for p in (records,measured)})
    packet=compact/'completion.json';packet.write_text(json.dumps(qualified,indent=2)+'\n');bindings[str(packet)]=sha(packet)
    private=work/'producer.py';private.write_text(derive(original.read_text(),ROOT));bindings[str(private)]=sha(private)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');verify(bindings)
    with (work/'assemble.log').open('x') as log:
        code=subprocess.call([sys.executable,str(private),'--qualified',str(compact),'--vectors',str(args.vectors.resolve())],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows=[json.loads(x) for x in (work/'assemble.log').read_text().splitlines() if x.startswith('{')]
    if rows:result['report']=rows[-1]
    verify(bindings)
    if code==0 and result.get('report',{}).get('numeric_matches')==1000:result['status']='CPU_DFI_COMPLETE_RESULT_STAGE_PASS'
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],report=result.get('report'))),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
