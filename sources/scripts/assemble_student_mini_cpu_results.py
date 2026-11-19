"""Verify all raw VexRiscv outputs; missing adapter evidence remains HOLD."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from statistics import fmean
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import compare_outputs,summarize_seeds,sha
from scripts.export_student_mini_input import encode

PATTERN=re.compile(r'^STUDENT_CPU ordinal=(\d+) status=(\d+) cycles=(\d+):(\d+) instructions=(\d+):(\d+) ibus_bytes=(\d+):(\d+) dbus_bytes=(\d+):(\d+) dma_bytes=(\d+):(\d+) primitive=(-?\d+) bits=([\da-f,]*) selected=([\d,]*)$')
STATUS={0:'OK',1:'BAD_DESCRIPTOR',2:'BAD_LENGTH',3:'BAD_PAGE',4:'NUMERIC_ERROR',5:'BUS_ERROR',6:'UNSUPPORTED_BUS_INJECTION'}

def parse(text,count):
    rows={};terminal=[]
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('STUDENT_CPU_COMPLETE '):terminal.append(line)
        if not line.startswith('STUDENT_CPU '):continue
        match=PATTERN.fullmatch(line)
        if not match:raise ValueError('malformed CPU record')
        fields=match.groups();ordinal=int(fields[0])
        if ordinal in rows:raise ValueError('duplicate CPU ordinal')
        row=dict(ordinal=ordinal,actual_status=STATUS[int(fields[1])],primitive=int(fields[12]),actual_bits=[int(v,16) for v in fields[13].split(',') if v],selected=[int(v) for v in fields[14].split(',') if v])
        for name,at in [('cycles',2),('instructions',4),('ibus_bytes',6),('dbus_bytes',8),('dma_bytes',10)]:
            hi,lo=map(int,fields[at:at+2])
            if hi>=2**32 or lo>=2**32:raise ValueError('invalid counter word')
            row[name]=(hi<<32)|lo
        if not row['cycles'] or not row['instructions']:raise ValueError('non-progressing hardware counter')
        rows[ordinal]=row
    if set(rows)!=set(range(count)) or terminal!=[f'STUDENT_CPU_COMPLETE count={count}']:raise ValueError('incomplete CPU transcript')
    return [rows[i] for i in range(count)]

def join(goldens,observations):
    if len(goldens)!=len(observations):raise ValueError('missing case/seed')
    rows=[];groups=defaultdict(list)
    for golden,observed in zip(goldens,observations,strict=True):
        case=golden['case'];expected=golden['golden'];observed=dict(observed)
        observed.update(platform='cpu',operator=case['operator'],seed=golden['seed'],backend='vexriscv-rtl',case_id=case['id'],cache_bytes=observed['ibus_bytes']+observed['dbus_bytes'],counter_source='mcycle/minstret CSR, accepted VexRiscv I/D Wishbone bytes, and accepted 128-bit DMA payload bytes')
        observed['actual']=[struct.unpack('<f',struct.pack('<I',b<<16))[0] for b in observed['actual_bits']]
        missing=['full-adapter-protocol-qualification']
        if observed['actual_status']=='UNSUPPORTED_BUS_INJECTION':
            match=None;comparison=None;missing.append('target-DMA-fault-injection')
        elif expected['output_values']:
            comparison=compare_outputs(expected['output_values'],observed['actual'],expected['output_bits'],observed['actual_bits'])
            match=comparison['status']=='PASS' and observed['actual_status']==expected['expected_status']
            if case['operator']=='p1':
                selection_match=observed['selected']==[x for ids in expected['selected_token_ids'] for x in ids]
                comparison['selection_match']=selection_match;match=match and selection_match
            if 'primitive_witness_result' in expected:
                primitive_match=observed['primitive']==expected['primitive_witness_result'];match=match and primitive_match
                comparison['primitive_match']=primitive_match
        else:
            match=observed['actual_status']==expected['expected_status'] and not observed['actual_bits']
            comparison=dict(kind='error-status',expected=expected['expected_status'],actual=observed['actual_status'],status='PASS' if match else 'FAIL',delta=None)
        observed['numeric_match']=match;observed['missing_witnesses']=missing
        record=dict(case=case,seed=golden['seed'],prng=golden['prng'],inputs=golden['inputs'],golden=expected,observation=observed,comparison=comparison,status='FAIL' if match is False else 'HOLD')
        rows.append(record);groups[case['id']].append(record)
    summaries=[]
    for case_id,group in groups.items():
        if sorted(r['seed'] for r in group)!=list(range(1,11)):raise ValueError('case missing seed')
        numeric=[dict(seed=r['seed'],**r['comparison']) for r in group if r['comparison'] and 'golden_bits' in r['comparison']]
        counters={field:dict(raw=[r['observation'].get(field) for r in group],mean=fmean(r['observation'][field] for r in group) if all(type(r['observation'].get(field)) is int for r in group) else None) for field in ('cycles','instructions','dma_bytes','cache_bytes','ibus_bytes','dbus_bytes')}
        summaries.append(dict(platform='cpu',case_id=case_id,status='FAIL' if any(r['status']=='FAIL' for r in group) else 'HOLD',failed_seeds=[r['seed'] for r in group if r['status']=='FAIL'],held_seeds=[r['seed'] for r in group if r['status']=='HOLD'],numeric=summarize_seeds(numeric) if len(numeric)==10 else None,counters=counters))
    return dict(schema_version=1,platform='cpu',operator='all',status='HOLD',formal_baseline=False,records=rows,cases=summaries,counts={s:sum(r['status']==s for r in rows) for s in ('PASS','FAIL','HOLD')},numeric_matches=sum(r['observation']['numeric_match'] is True for r in rows),semantic_fp32_error_status='NOT_MEASURED',reason='Real VexRiscv output replay; DMA/protocol, physical, resource and Nano gates remain incomplete')

def assemble(vectors,work):
    completion=json.loads((work/'completion.json').read_text())
    if not completion.get('target_run_complete'):raise ValueError('target run incomplete')
    for name,digest in completion['artifacts'].items():
        if sha(work/name)!=digest:raise ValueError('CPU artifact SHA mismatch')
    inputs=json.loads((work/'inputs.json').read_text())
    source_bindings=inputs['input_manifest']['bindings']
    if source_bindings.get(vectors.relative_to(ROOT).as_posix())!=sha(vectors):raise ValueError('mixed golden revision')
    for name,digest in source_bindings.items():
        if sha(ROOT/name)!=digest:raise ValueError('stale scalar source')
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    if (work/'console.log').read_text().splitlines().count('STUDENT_CPU_DMA_PROBE status=0 bytes=0:64')!=1:raise ValueError('DMA counter did not pass real descriptor-transfer calibration')
    if (work/'inputs.bin').read_bytes()!=b''.join(encode(r,i) for i,r in enumerate(goldens)):raise ValueError('input bytes differ from frozen corpus')
    report=join(goldens,parse((work/'console.log').read_text(),len(goldens)))
    report['bindings']={p.relative_to(ROOT).as_posix():sha(p) for p in (vectors,work/'console.log',work/'completion.json',work/'inputs.json',Path(__file__))}
    destination=ROOT/'grading/evidence/student-mini-v1/results'/completion['input_sha256'];destination.mkdir(parents=True,exist_ok=False)
    path=destination/'results.json';path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),counts=report['counts'],numeric_matches=report['numeric_matches'])))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vectors',type=Path,required=True);parser.add_argument('--work',type=Path,required=True);args=parser.parse_args();assemble(args.vectors.resolve(),args.work.resolve())
