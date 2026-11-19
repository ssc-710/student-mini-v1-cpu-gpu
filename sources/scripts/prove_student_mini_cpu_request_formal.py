"""24-step bounded request/response proof and four deliberate RTL mutations."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import verify


def main():
    rtl=ROOT/'tests/rtl/student_mini_cpu_rom_request_cut.sv'
    bench=ROOT/'tests/rtl/student_mini_cpu_rom_request_formal.sv'
    tool=Path('/home/soclab/tools/oss-cad-suite/bin/yosys')
    paths=[Path(__file__),rtl,bench,tool,tool.parent.parent/'libexec/yosys']
    bindings={str(p):sha(p) for p in paths};key=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/cpu-rom-request-formal'/key;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',bindings=bindings,formal_baseline=False,physical_evidence_complete=False,
                scope='local ROM request boundary only; not whole Wishbone/LiteDRAM or warm-reset software',
                bounded_steps=24,rtl_sha256=sha(rtl),unbounded_proof=False)
    (work/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    mutations={'original':None,
        'wrong-address':('rom_address <= address;',"rom_address <= address+15'd1;"),
        'early-ack':('(state == 2)','(state == 1)'),
        'ignore-cancel':('reset || !cyc || !stb','reset'),
        'ignore-reset':('reset || !cyc || !stb','!cyc || !stb')}
    try:
        outcomes=[]
        for name,change in mutations.items():
            text=rtl.read_text()
            if change:
                old,new=change
                if text.count(old)!=1:raise ValueError('formal mutation seam changed')
                text=text.replace(old,new)
            source=work/(name+'.sv');source.write_text(text)
            script=work/(name+'.ys')
            script.write_text(f'read_verilog -formal -sv {source} {bench}\nprep -top contract -flatten\nsat -verify -prove-asserts -seq 24 -set-init-zero -show-public\n')
            proc=subprocess.run([str(tool),'-Q','-T','-s',str(script)],capture_output=True,text=True,timeout=60)
            output=proc.stdout+proc.stderr;(work/(name+'.log')).write_text(output)
            if name=='original':
                if proc.returncode or 'SAT proof finished - no model found: SUCCESS!' not in output:
                    raise ValueError('positive bounded request proof failed')
            elif not proc.returncode or 'proof did fail' not in output:
                raise ValueError('mutation did not produce a checked counterexample: '+name)
            outcomes.append(dict(name=name,exit_code=proc.returncode,expected_result='PASS' if name=='original' else 'COUNTEREXAMPLE'))
        verify(bindings)
        result.update(status='CPU_ROM_REQUEST_BOUNDED_FORMAL_STAGE_PASS',outcomes=outcomes,
            reason='24-step arbitrary-input local control/address proof passes; all four mutants fail; whole bus/platform formal and physical acceptance remain')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    result['artifacts']={p.name:sha(p) for p in work.iterdir() if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='CPU_ROM_REQUEST_BOUNDED_FORMAL_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
