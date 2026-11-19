"""Publish complete current-CPU case results without claiming protocol/signoff."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify
from scripts.assemble_student_mini_cpu_results import parse,join
from scripts.export_student_mini_input import encode
from scripts.student_mini_cpu_loader_banks import checked_original


def assemble(qualified,vectors):
    receipt=qualified/'completion.json';parent=json.loads(receipt.read_text())
    if (parent.get('status')!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'
        or parent.get('independent_external_memory') is not True
        or parent.get('transcript_join',{}).get('baseline_records')!=1000):
        raise ValueError('complete independently executed current CPU required')
    verify(parent['bindings'])
    for name,digest in parent['artifacts'].items():
        if sha(qualified/name)!=digest:raise ValueError('rechecked measurement artifact changed')
    source=Path(parent['source_replay']);cpu=Path(parent['parent_cpu']);mapping=Path(parent['parent_mapping'])
    original=json.loads((cpu/'inputs.json').read_text())
    if original.get('runtime_input_contains_golden') is not False or original.get('baseline_count')!=1000:
        raise ValueError('input-only complete baseline workload required')
    sources=original['input_manifest']['bindings']
    if sources.get(vectors.relative_to(ROOT).as_posix())!=sha(vectors):raise ValueError('mixed golden revision')
    for path,digest in sources.items():
        if sha(ROOT/path)!=digest:raise ValueError('frozen input source changed')
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    if len(goldens)!=1000:raise ValueError('full frozen corpus required')
    baseline=b''.join(encode(row,i) for i,row in enumerate(goldens))
    loader=(cpu/'loader.bin').read_bytes()
    if original['native_image_offset']!=len(baseline) or loader[:len(baseline)]!=baseline:
        raise ValueError('actual loaded inputs differ from complete golden corpus')
    checked_original(loader,[(source/f'sim_mem_{i}.init').read_text() for i in range(1,5)])
    text=(qualified/'uart-records.log').read_text()
    if text.splitlines().count('STUDENT_CPU_DMA_PROBE status=0 bytes=0:64')!=1:
        raise ValueError('actual DMA byte calibration missing')
    report=join(goldens,parse(text,1000))
    paths=[Path(__file__),receipt,vectors,qualified/'uart-records.log',qualified/'measurements.json',
           source/'completion.json',cpu/'inputs.json',cpu/'loader.bin',mapping/'completion.json',mapping/'mapped.v',
           *[source/f'sim_mem_{i}.init' for i in range(1,5)]]
    paths += [ROOT/'scripts'/name for name in ('student_mini.py','assemble_student_mini_cpu_results.py',
        'export_student_mini_input.py','student_mini_cpu_loader_banks.py')]
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    report.update(bindings=bindings,hardware_boundary_sha256=sha(mapping/'mapped.v'),
        same_rom_baseline_and_nano=True,independent_external_memory=True,read_latency_cycles=2,
        performance_eligible=False,
        reason='1000 complete current two-edge-ROM CPU observations and fresh counters; full protocol, selected model, physical and release gates remain HOLD')
    key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    output=ROOT/'grading/evidence/student-mini-v1/results'/key;output.mkdir(parents=True,exist_ok=False)
    path=output/'results.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return dict(path=str(path),sha256=sha(path),numeric_matches=report['numeric_matches'],counts=report['counts'],formal_baseline=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualified',type=Path,required=True);parser.add_argument('--vectors',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(assemble(args.qualified.resolve(),args.vectors.resolve())),flush=True)


if __name__=='__main__':main()
