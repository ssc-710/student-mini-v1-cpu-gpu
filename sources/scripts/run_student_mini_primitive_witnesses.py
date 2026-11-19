"""Replay frozen numeric witnesses on the actual component RTL, not a host oracle.

P1/P2 INT8 saturation is deliberately not claimed: these attention components
return INT32/BF16, not an INT8 requantizer. Component coverage is supplementary;
it never silently changes whole-operator HOLDs or grants a physical baseline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

SOURCES=['fixed_divider_rne_step_cut_pipeline.sv','fixed_divider_rne_finalize_pipeline.sv',
         'q22_requantize_int8_finalize_pipeline.sv','q22_requantize_int8_low_digit_compat.sv']
PATTERN=re.compile(r'^STUDENT_PRIMITIVE ordinal=(\d+) seed=(\d+) mode=(\d+) actual=(-?\d+) cycles=(\d+) held=(\d+)$',re.M)


def selected_inputs(goldens):
    selected=[];unsupported=[];seen=set()
    for ordinal,row in enumerate(goldens):
        witness=row['inputs'].get('primitive_witness')
        if not witness:continue
        op=row['case']['operator'];key=(row['case']['id'],row['seed'])
        if key in seen or type(row['seed']) is not int or row['seed'] not in range(1,11):
            raise ValueError('duplicate/invalid witness case seed')
        seen.add(key)
        if op not in ('p1','p2','p3'):raise ValueError('unsupported operator')
        if witness['kind']=='int8-saturation' and op!='p3':
            unsupported.append(dict(ordinal=ordinal,case_id=key[0],seed=key[1],operator=op,
                reason='No INT8 saturation stage exists in the selected attention output boundary'))
            continue
        if witness['kind']=='rne-integer-division':
            n,d=witness['numerator'],witness['denominator']
            if d!=2 or n not in (-7,-5,5,7):raise ValueError('frozen half-integer witness differs')
            # Preserve the physical divider FRAC_BITS=16. Scaling its denominator
            # cancels the built-in fractional factor exactly, without host rounding.
            numerator=n;denominator=d<<16;value_q22=n*(1<<21)
        elif witness['kind']=='int8-saturation':
            value=witness['value']
            if value not in (-129,128):raise ValueError('frozen saturation witness differs')
            numerator=0;denominator=1;value_q22=value*(1<<22)
        else:raise ValueError('unknown numeric witness')
        selected.append(dict(ordinal=ordinal,case_id=key[0],seed=key[1],operator=op,
            mode=int(op[1]),numerator=numerator,denominator=denominator,value_q22=value_q22,
            original_witness=witness,expected=row['golden']['primitive_witness_result']))
    if not selected:raise ValueError('no numeric witnesses')
    return selected,unsupported


def check_transcript(text,selected):
    matches=PATTERN.findall(text);records=[]
    if len(matches)!=len(selected):raise ValueError('missing or duplicated primitive records')
    done=re.findall(r'^STUDENT_PRIMITIVE_DONE count=(\d+)$',text,re.M)
    if done!=[str(len(selected))]:raise ValueError('missing/duplicate completion marker')
    for values,row in zip(matches,selected):
        ordinal,seed,mode,actual,cycles,held=map(int,values)
        if (ordinal,seed,mode)!=(row['ordinal'],row['seed'],row['mode']):raise ValueError('primitive input join differs')
        if cycles<=0 or held!=3:raise ValueError('invalid component cycle/protocol witness')
        records.append(dict(row,actual=actual,delta=actual-row['expected'],cycles=cycles,
            response_hold_cycles=held,status='PASS' if actual==row['expected'] else 'FAIL',
            measurement_boundary='component command only, not whole-operator performance'))
    return records


def main():
    import fcntl
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors',type=Path,required=True)
    args=parser.parse_args();vectors=args.vectors.resolve()
    goldens=[json.loads(line) for line in vectors.read_text().splitlines()]
    manifest=vectors.parent/'manifest.json';frozen=json.loads(manifest.read_text())
    if frozen['artifacts']['vectors.jsonl']!=sha(vectors):raise ValueError('golden changed')
    selected,unsupported=selected_inputs(goldens)
    toolroot=Path('/home/soclab/tools/oss-cad-suite/bin')
    paths=[Path(__file__),vectors,manifest,ROOT/'tests/rtl/student_mini_primitive_tb.sv',
        *(ROOT/'shared/rtl'/name for name in SOURCES),toolroot/'iverilog',toolroot/'vvp']
    bindings={str(p):sha(p) for p in paths}
    bindings.update({str(ROOT/p):digest for p,digest in frozen['bindings'].items()})
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/primitive-witnesses'/identity;work.mkdir(parents=True,exist_ok=False)
    # The simulator receives only operands/IDs, never the expected result.
    input_path=work/'inputs.txt'
    input_path.write_text(''.join(f"{r['ordinal']} {r['seed']} {r['mode']} {r['numerator']&((1<<64)-1):016x} {r['denominator']:012x} {r['value_q22']&((1<<48)-1):012x}\n" for r in selected))
    result=dict(status='HOLD',formal_baseline=False,physical_evidence_complete=False,
        scope='Component RTL witnesses; no implied whole-operator integration coverage',
        bindings=bindings,unsupported=unsupported,records=[])
    started=time.monotonic()
    def verify():
        if any(sha(Path(p))!=digest for p,digest in bindings.items()):raise ValueError('witness source changed')
    def execute(command,name):
        with (work/name).open('x') as log:
            code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT,timeout=120).returncode
        if code:raise RuntimeError(name+' failed')
    try:
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            print(json.dumps(dict(work=str(work),stage='WAITING_FOR_SERIAL_QUEUE')),flush=True)
            fcntl.flock(lock,fcntl.LOCK_EX);verify()
            execute([str(toolroot/'iverilog'),'-g2012','-s','student_mini_primitive_tb','-o',str(work/'probe.vvp'),
                *(str(ROOT/'shared/rtl'/name) for name in SOURCES),str(ROOT/'tests/rtl/student_mini_primitive_tb.sv')],'compile.log')
            execute([str(toolroot/'vvp'),str(work/'probe.vvp'),'+INPUT='+str(input_path)],'run.log')
            result['records']=check_transcript((work/'run.log').read_text(),selected);verify()
            result['component_replay_complete']=all(r['status']=='PASS' for r in result['records'])
            result['reason']='Component measurements retained; unsupported attention INT8 saturation and operator integration remain HOLD'
    except Exception as error:
        result.update(component_replay_complete=False,reason=f'{type(error).__name__}: {error}')
    result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),complete=result['component_replay_complete'],reason=result['reason'])),flush=True)
    return 0 if result['component_replay_complete'] else 1


if __name__=='__main__':raise SystemExit(main())
