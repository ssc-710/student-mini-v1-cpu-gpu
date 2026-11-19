"""Run real P3 seed workloads at 100 MHz; activity alone never grants signoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.run_gate_activity import sky130_model_roots,verilog_include_closure,compress_vcd,normalize_vcd_to_1ns
from scripts.collect_openroad_activity_power import validate_vcd_window

PATTERN=re.compile(r'^STUDENT_GATE seed=(\d+) status=(\d+) cycles=(\d+) dma_bytes=(\d+) bits=([0-9a-f,]+)$',re.M)

def check_transcript(text,sample):
    matches=PATTERN.findall(text)
    if len(matches)!=1:raise ValueError('missing or duplicate full gate result')
    seed,status,cycles,traffic,bits=matches[0]
    actual=[int(word,16) for word in bits.split(',')]
    if int(seed)!=sample['seed'] or int(status)!=0 or actual!=sample['expected_bits']:
        raise ValueError('gate-level complete output mismatch')
    windows=[]
    for boundary in ('BEGIN','END'):
        markers=re.findall(rf'^STUDENT_ACTIVITY_{boundary} seed=(\d+) time_ns=(\d+)$',text,re.M)
        if len(markers)!=1 or int(markers[0][0])!=sample['seed']:raise ValueError('missing or inconsistent activity window')
        windows.append(int(markers[0][1]))
    if windows[0]<0 or windows[1]<=windows[0] or int(cycles)<=0 or int(traffic)<=0:raise ValueError('invalid workload counters/window')
    result=dict(seed=int(seed),actual_bits=actual,cycles=int(cycles),dma_bytes=int(traffic),begin_ns=windows[0],end_ns=windows[1])
    if sample.get('operator')=='p1':
        selected=re.findall(r'^STUDENT_SELECTED seed=(\d+) ids=([0-9,]+)$',text,re.M)
        if len(selected)!=1 or int(selected[0][0])!=sample['seed'] or [int(x) for x in selected[0][1].split(',')]!=sample['expected_selected']:
            raise ValueError('gate-level Top-K selection mismatch')
    return result

def main():
    import fcntl  # Linux execution only; transcript checks also run on Windows.
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--placement',type=Path,required=True)
    parser.add_argument('--mode',choices=['rtl','synth','gate'],required=True)
    parser.add_argument('--seed',type=int,choices=range(1,11),action='append')
    parser.add_argument('--sky130-library-root',type=Path)
    args=parser.parse_args();manifest=args.manifest.resolve();placement=args.placement.resolve()
    inputs=json.loads(manifest.read_text());physical=json.loads((placement/'inputs.json').read_text())
    tb=ROOT/'tests/rtl/student_mini_attention_gate_activity_tb.sv'
    top='student_mini_attention_gate_activity_tb'
    iverilog=Path('/home/soclab/tools/oss-cad-suite/bin/iverilog').resolve()
    vvp=Path('/home/soclab/tools/oss-cad-suite/bin/vvp').resolve()
    bindings={str(ROOT/p):digest for p,digest in inputs['bindings'].items()}
    bindings.update({str(p):sha(p) for p in (manifest,placement/'inputs.json',tb,Path(__file__),iverilog,vvp)})
    design=physical['design'];operator=inputs['operator']
    if operator not in ('p1','p2'):raise ValueError('attention operator required')
    extra=['-DSTUDENT_ACTIVITY_P1'] if operator=='p1' else []
    if args.mode=='rtl':
        sources=[ROOT/p for p in design['sources']]
        if design['parameters'] != (dict(HEADS=1,K_MAX=4,PIPELINED_SOFTMAX=1,PIPELINED_SCORE_SCALE=1,PIPELINED_PAGE_VALIDATE=1) if operator=='p1' else {}):raise ValueError('unexpected attention RTL profile')
        extra+=['-DSTUDENT_ACTIVITY_RTL','-I',str(ROOT/'shared/rtl'),'-D',f'EXP_Q15_MEM_FILE="{ROOT}/shared/rtl/exp_q15_q6.mem"']
        extra+=['-D'+define for define in design['defines']]
        models=[]
    else:
        parent=json.loads((placement/'completion.json').read_text())
        if args.mode=='gate':
            route=json.loads((placement/'route/completion.json').read_text())
            if route.get('exit_code')!=0 or not route.get('source_freshness_verified'):raise ValueError('route not complete')
            netlist=Path(parent['result_directory'])/'6_final.v'
            if route['artifacts'].get(str(netlist))!=sha(netlist):raise ValueError('routed netlist binding mismatch')
            bindings[str(placement/'route/completion.json')]=sha(placement/'route/completion.json')
        else:
            netlist=Path(parent['result_directory'])/'1_2_yosys.v'
            if parent['artifacts'].get(str(netlist))!=sha(netlist):raise ValueError('synthesized netlist binding mismatch')
            bindings[str(placement/'completion.json')]=sha(placement/'completion.json')
        for path,digest in physical['files'].items():
            if sha(Path(path))!=digest:raise ValueError('physical input changed: '+path)
        bindings.update(physical['files'])
        if args.sky130_library_root is None:raise ValueError('official SKY130 cell library required')
        models=sky130_model_roots(netlist,args.sky130_library_root.resolve())
        sources=[netlist]
        extra+=['-grelative-include','-DFUNCTIONAL']
    for path in sources+verilog_include_closure(models):bindings[str(path)]=sha(path)
    seeds=sorted(args.seed or range(1,11))
    if len(seeds)!=len(set(seeds)):raise ValueError('duplicate seed')
    samples=[r for r in inputs['samples'] if r['seed'] in seeds]
    if len(samples)!=len(seeds):raise ValueError('missing seed input')
    for sample in samples:bindings[str(manifest.parent/sample['image'])]=sample['image_sha256']
    if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('stale activity source')
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,mode=args.mode,seeds=seeds),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/attention-activity'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',physical_evidence_complete=False,mode=args.mode,operator=operator,bindings=bindings,records=[])
    started=time.monotonic()
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
    def execute(command,path,timeout):
        with path.open('x') as log:
            process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,cwd=ROOT)
        if process.returncode:raise RuntimeError(f'{path.name} exited {process.returncode}')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),status='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('activity source changed while queued')
            executable=work/'activity.vvp'
            execute([str(iverilog),'-g2012','-s',top,'-o',str(executable),*extra,*map(str,models),*map(str,sources),str(tb)],work/'compile.log',300)
            for sample in samples:
                seed=sample['seed'];raw=work/f'seed-{seed}.vcd';log=work/f'seed-{seed}.log'
                execute([str(vvp),str(executable),f'+IMAGE={manifest.parent/sample["image"]}',f'+VCD={raw}',f'+SEED={seed}'],log,600)
                row=check_transcript(log.read_text(),sample)
                normalized=work/f'seed-{seed}.1ns.vcd'
                normalization=normalize_vcd_to_1ns(raw,normalized)
                validate_vcd_window(normalized,row['begin_ns'],row['end_ns'])
                compressed=work/f'seed-{seed}.vcd.gz';compress_vcd(normalized,compressed)
                row['timescale_normalization']=normalization
                row.update(case_id=sample['case_id'],input_sha256=sample['input_sha256'],activity=compressed.name,activity_sha256=sha(compressed),clock_hz=100000000,scope=top+'.dut')
                result['records'].append(row)
                print(json.dumps(dict(seed=seed,status='OUTPUT_MATCHED',cycles=row['cycles'])),flush=True)
            if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('activity source changed during run')
            result.update(activity_complete=True,reason='Full output checked; post-route power analysis and final signoff remain separate')
    except Exception as error:result.update(activity_complete=False,reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),complete=result['activity_complete'],reason=result['reason'])),flush=True)
    return 0 if result['activity_complete'] else 1

if __name__=='__main__':raise SystemExit(main())
