"""Join actual target tokens and complete BF16 states to an independent model.

This is a numerical session stage, not quality/physical/package acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
from scripts.student_mini import sha
from soc_ai_labs.student_mini_nano_runtime import MiniNanoRuntime


def bits(value):
    return (np.asarray(value,dtype=np.float32).view(np.uint32)>>16).astype(np.uint16).tolist()


def reference(runtime,prompt):
    rows=[];logits=runtime.prefill(prompt)
    for step in range(12):
        token=int(np.argmax(logits))
        rows.append(dict(step=step,token=token,hidden=bits(runtime.current_hidden()),logits=bits(logits)))
        if token==4:break
        if step<11:logits=runtime.decode(token)
    return rows


def counter(text):
    if not re.fullmatch(r'\d+:\d+',text):raise ValueError('invalid split hardware counter')
    high,low=map(int,text.split(':'))
    if high>=2**32 or low>=2**32:raise ValueError('counter word overflow')
    return (high<<32)|low


def transcript(text,platform,golden,prompt_count):
    if platform not in ('cpu','gpu'):raise ValueError('unsupported target platform')
    tag=platform.upper()
    status_lines=re.findall(r'^STUDENT_NATIVE_'+tag+r' status=(\d+) count=(\d+)([^\n]*)$',text,re.M)
    completed=re.findall(r'^STUDENT_NATIVE_'+tag+r'_COMPLETE count=(\d+) p1=(\d+) p2=(\d+) p3=(\d+)$',text,re.M)
    if len(status_lines)!=1 or len(completed)!=1:raise ValueError('missing/duplicate target completion')
    status,count,extra=status_lines[0];count=int(count)
    if status!='0' or not 1<=count<=12 or count!=len(golden):raise ValueError('target status/count mismatch')
    if tuple(map(int,completed[0]))!=(count,1,count-1,2*(prompt_count+count-1)):
        raise ValueError('operator invocation count mismatch')
    token_lines=[line for line in text.splitlines() if line.startswith('STUDENT_NATIVE_TOKEN ')]
    if len(token_lines)!=count:raise ValueError('missing/duplicate token trace')
    actual=[];elapsed=[]
    for step,line in enumerate(token_lines):
        match=re.fullmatch(r'STUDENT_NATIVE_TOKEN step=(\d+) token=(\d+)(?: elapsed_cycles=(\d+:\d+))? hidden=([0-9a-f,]+) logits=([0-9a-f,]+)',line)
        if not match or int(match[1])!=step:raise ValueError('malformed or reordered token trace')
        values=dict(step=step,token=int(match[2]),hidden=[int(x,16) for x in match[4].split(',')],logits=[int(x,16) for x in match[5].split(',')])
        if len(values['hidden'])!=16 or len(values['logits'])!=256 or values!=golden[step]:
            raise ValueError('full target token/state mismatch at step '+str(step))
        if platform=='cpu':
            if match[3] is None:raise ValueError('CPU token hardware counter missing')
            value=counter(match[3])
            if value<=0 or (elapsed and value<=elapsed[-1]):raise ValueError('nonmonotonic CPU token counters')
            elapsed.append(value)
        elif match[3] is not None:raise ValueError('SimX timing cannot be hardware performance')
        actual.append(values)
    measured=None
    if platform=='cpu':
        pairs=re.findall(r'(\w+)=(\d+:\d+)',extra)
        if len(pairs)!=5 or {key for key,_ in pairs}!=set(('cycles','instructions','ibus_bytes','dbus_bytes','dma_bytes')):
            raise ValueError('CPU raw hardware counters incomplete/duplicate')
        measured={key:counter(value) for key,value in pairs}
        if measured['cycles']<elapsed[-1] or measured['instructions']<=0:raise ValueError('invalid CPU execution interval')
        measured.update(first_token_cycles=elapsed[0],token_elapsed_cycles=elapsed,
                        mean_decode_token_cycles=(elapsed[-1]-elapsed[0])/(count-1) if count>1 else None)
        ops=re.findall(r'^STUDENT_NATIVE_OPERATOR op=(\d+) cycles=(\d+:\d+)$',text,re.M)
        if len(ops)!=3 or sorted(int(op) for op,_ in ops)!=[1,2,3]:raise ValueError('missing/duplicate operator cycles')
        measured['operator_cycles']={op:counter(value) for op,value in ops}
    return dict(records=actual,counters=measured,token_sha256=hashlib.sha256(
        struct.pack('<'+str(count)+'I',*[r['token'] for r in actual])).hexdigest())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--image-dir',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--platform',choices=['cpu','gpu'],required=True)
    args=parser.parse_args();run=args.run.resolve();image_dir=args.image_dir.resolve()
    completion_path=run/'completion.json';completion=json.loads(completion_path.read_text())
    if completion.get('target_run_complete') is not True:raise ValueError('actual target replay incomplete')
    for name,digest in completion['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('target source changed: '+name)
    paths=[]
    for name,digest in completion['artifacts'].items():
        path=Path(name) if Path(name).is_absolute() else run/name
        if sha(path)!=digest:raise ValueError('target artifact changed: '+name)
        paths.append(path)
    manifest_path=image_dir/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if completion['bindings'].get(str(manifest_path))!=sha(manifest_path):raise ValueError('image not bound to this target execution')
    candidate_path=args.candidate.resolve();candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
    if manifest['bindings'].get(candidate_path.relative_to(ROOT).as_posix())!=sha(candidate_path):raise ValueError('wrong checkpoint lineage')
    for name,digest in manifest['bindings'].items():
        if sha(ROOT/name)!=digest:raise ValueError('image source changed')
    checkpoint=candidate_path.parent/candidate['lineage']['qat']['quantized']
    if sha(checkpoint)!=candidate['lineage']['qat']['quantized_sha256']:raise ValueError('checkpoint changed')
    golden=reference(MiniNanoRuntime.from_npz(checkpoint),manifest['prompt_tokens'])
    log=run/('console.log' if args.platform=='cpu' else 'execute.log')
    joined=transcript(log.read_text(),args.platform,golden,len(manifest['prompt_tokens']))
    paths += [completion_path,manifest_path,candidate_path,checkpoint,log,Path(__file__)]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    output=ROOT/'grading/evidence/student-mini-v1/native-sessions'/identity
    output.mkdir(parents=True,exist_ok=False)
    result=dict(status='NUMERICAL_SESSION_STAGE_PASS',accepted_nano_session=False,
        platform=args.platform,backend='vexriscv-rtl' if args.platform=='cpu' else 'simx',
        performance_eligible=False,physical_complete=False,quality_complete=False,
        question=manifest['question'],bindings=bindings,**joined,
        reason='Complete actual tokens/states match; held-out quality and complete physical/package qualification remain mandatory')
    path=output/'session.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path),platform=args.platform,token_sha256=joined['token_sha256'],accepted=False)))


if __name__=='__main__':main()
