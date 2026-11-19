"""Full-output SimX evidence, explicitly ineligible for hardware performance."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import compare_outputs,summarize_seeds,sha
from scripts.export_student_mini_input import encode
from scripts.assemble_student_mini_cpu_results import STATUS

PATTERN=re.compile(r'^STUDENT_GPU ordinal=(\d+) status=(\d+) primitive=(-?\d+) bits=([\da-f,]*) selected=([\d,]*)$')

def parse(text,count):
    rows={};terminal=[]
    for line in text.splitlines():
        if line.startswith('STUDENT_GPU_COMPLETE '):terminal.append(line)
        if not line.startswith('STUDENT_GPU '):continue
        match=PATTERN.fullmatch(line)
        if not match:raise ValueError('malformed GPU record')
        ordinal,status,primitive,bits,selected=match.groups()
        ordinal=int(ordinal);status=int(status)
        if ordinal in rows or status not in STATUS:raise ValueError('duplicate ordinal/unknown status')
        values=[int(v,16) for v in bits.split(',') if v]
        if any(v>65535 for v in values):raise ValueError('invalid BF16 word')
        rows[ordinal]=dict(ordinal=ordinal,actual_status=STATUS[status],primitive=int(primitive),actual_bits=values,
                           actual=[struct.unpack('<f',struct.pack('<I',v<<16))[0] for v in values],
                           selected=[int(v) for v in selected.split(',') if v])
    if set(rows)!=set(range(count)) or terminal!=[f'STUDENT_GPU_COMPLETE start=0 count={count}']:
        raise ValueError('incomplete GPU transcript')
    return [rows[i] for i in range(count)]

def join(goldens,actuals):
    if len(goldens)!=len(actuals):raise ValueError('missing GPU case/seed')
    rows=[];groups=defaultdict(list)
    for golden,actual in zip(goldens,actuals,strict=True):
        expected=golden['golden'];case=golden['case'];observed=dict(actual)
        observed.update(platform='gpu',backend='vortex-simx',operator=case['operator'],case_id=case['id'],seed=golden['seed'],
                        cycles=None,instructions=None,dma_bytes=None,cache_bytes=None,performance_eligible=False,
                        counter_source='NOT_MEASURED: SimX wall clock and aggregate simulation PERF are not RTL case counters')
        missing=['RTLSIM-case-counters','RTL-protocol-qualification']
        if observed['actual_status']=='UNSUPPORTED_BUS_INJECTION':
            comparison=None;matched=None;missing.append('target-DMA-fault-injection')
        elif expected['output_values']:
            comparison=compare_outputs(expected['output_values'],observed['actual'],expected['output_bits'],observed['actual_bits'])
            matched=comparison['status']=='PASS' and observed['actual_status']==expected['expected_status']
            if case['operator']=='p1':
                comparison['selection_match']=observed['selected']==[t for ids in expected['selected_token_ids'] for t in ids]
                matched=matched and comparison['selection_match']
            if 'primitive_witness_result' in expected:
                comparison['primitive_match']=observed['primitive']==expected['primitive_witness_result']
                matched=matched and comparison['primitive_match']
        else:
            matched=observed['actual_status']==expected['expected_status'] and not observed['actual_bits']
            comparison=dict(kind='error-status',expected=expected['expected_status'],actual=observed['actual_status'],status='PASS' if matched else 'FAIL',delta=None)
        observed.update(numeric_match=matched,missing_witnesses=missing)
        row=dict(case=case,seed=golden['seed'],prng=golden['prng'],inputs=golden['inputs'],golden=expected,
                 observation=observed,comparison=comparison,status='FAIL' if matched is False else 'HOLD')
        rows.append(row);groups[case['id']].append(row)
    cases=[]
    for case_id,group in groups.items():
        if sorted(r['seed'] for r in group)!=list(range(1,11)):raise ValueError('missing or duplicated GPU seed')
        numeric=[dict(seed=r['seed'],**r['comparison']) for r in group if r['comparison'] and 'golden_bits' in r['comparison']]
        cases.append(dict(platform='gpu',case_id=case_id,status='FAIL' if any(r['status']=='FAIL' for r in group) else 'HOLD',
                          failed_seeds=[r['seed'] for r in group if r['status']=='FAIL'],held_seeds=[r['seed'] for r in group if r['status']=='HOLD'],
                          numeric=summarize_seeds(numeric) if len(numeric)==10 else None,
                          counters={name:dict(raw=[None]*10,mean=None) for name in ('cycles','instructions','dma_bytes','cache_bytes')}))
    return dict(schema_version=1,status='HOLD',platform='gpu',operator='all',formal_baseline=False,records=rows,cases=cases,
                counts={s:sum(r['status']==s for r in rows) for s in ('PASS','FAIL','HOLD')},
                numeric_matches=sum(r['observation']['numeric_match'] is True for r in rows),
                reason='Actual SimX full-output replay only; RTLSIM counters/protocol, physical, Nano and release gates remain mandatory')

def assemble(vectors,run):
    completion=json.loads((run/'completion.json').read_text())
    if completion.get('backend')!='simx' or not completion.get('target_run_complete'):raise ValueError('incomplete SimX run')
    for name,digest in completion['artifacts'].items():
        if sha(Path(name))!=digest:raise ValueError('GPU artifact changed: '+name)
    manifest=json.loads((run.parent/'manifest.json').read_text())
    for name,digest in manifest['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('GPU source changed: '+name)
    input_dir=Path(manifest['input_directory'])
    input_manifest=json.loads((input_dir/'manifest.json').read_text())
    if input_manifest['bindings'].get(vectors.relative_to(ROOT).as_posix())!=sha(vectors):raise ValueError('mixed golden SHA')
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    if (input_dir/'inputs.bin').read_bytes()!=b''.join(encode(r,i) for i,r in enumerate(goldens)):raise ValueError('input image differs from frozen cases')
    report=join(goldens,parse((run/'execute.log').read_text(),len(goldens)))
    report['bindings']={p.relative_to(ROOT).as_posix():sha(p) for p in (vectors,run/'completion.json',run/'execute.log',run.parent/'manifest.json',Path(__file__))}
    identity=hashlib.sha256(json.dumps(report['bindings'],sort_keys=True).encode()).hexdigest()
    destination=ROOT/'grading/evidence/student-mini-v1/results'/identity;destination.mkdir(parents=True,exist_ok=False)
    path=destination/'results.json';path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),counts=report['counts'],numeric_matches=report['numeric_matches'])))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True);parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();assemble(args.vectors.resolve(),args.run.resolve())
