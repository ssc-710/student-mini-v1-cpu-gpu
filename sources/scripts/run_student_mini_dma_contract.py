"""Prove the mini DMA boundary and kill eight isolated RTL protocol mutants."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def main():
    names=['shared/rtl/litex_native_dma_bridge.sv','shared/rtl/student_mini_native_dma_bridge.sv','shared/formal/student_mini_dma_contract_harness.sv']
    files={Path(name).name:(ROOT/name).read_text() for name in names}
    tools=Path('/home/soclab/tools/oss-cad-suite/bin')
    bindings={name:sha(ROOT/name) for name in names};bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__))
    tool_hashes={name:sha((tools/name).resolve()) for name in ('yosys','sby','yosys-smtbmc','boolector')}
    identity=hashlib.sha256(json.dumps(dict(bindings=bindings,tools=tool_hashes),sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/dma-contract'/identity;work.mkdir(parents=True,exist_ok=False)
    mutants=[
        ('bad-region','student_mini_native_dma_bridge.sv',"(req_addr_i[31:28]!=4'h4)","1'b0"),
        ('unaligned','student_mini_native_dma_bridge.sv','(req_addr_i[3:0]!=0)',"1'b0"),
        ('missing-error','student_mini_native_dma_bridge.sv','rsp_error_o=core_error || error_pending_q','rsp_error_o=core_error'),
        ('response-ready-gating','student_mini_native_dma_bridge.sv','rsp_valid_o=core_valid || error_pending_q','rsp_valid_o=core_valid || (error_pending_q && rsp_ready_i)'),
        ('wrong-address','litex_native_dma_bridge.sv','native_cmd_addr_o = addr_q[4 +: NATIVE_ADDR_WIDTH]','native_cmd_addr_o = addr_q[4 +: NATIVE_ADDR_WIDTH] ^ 1'),
        ('wrong-data','litex_native_dma_bridge.sv','native_wdata_o = wdata_q','native_wdata_o = wdata_q ^ 1'),
        ('wrong-mask','litex_native_dma_bridge.sv','native_wstrb_o = wstrb_q','native_wstrb_o = wstrb_q ^ 1'),
        ('early-write-completion','student_mini_native_dma_bridge.sv',"parameter bit WRITE_FENCE = 1'b1","parameter bit WRITE_FENCE = 1'b0"),
    ]
    env=dict(os.environ,PATH=str(tools)+':/usr/local/bin:/usr/bin:/bin')
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
    records=[]
    for tag,filename,old,new in [('baseline',None,None,None),*mutants]:
        directory=work/tag;directory.mkdir()
        content=dict(files)
        if filename:
            if content[filename].count(old)!=1:raise ValueError('mutation target is not unique: '+tag)
            content[filename]=content[filename].replace(old,new)
        for name,text in content.items():(directory/name).write_text(text)
        modes=['bmc','cover'] if tag=='baseline' else ['bmc']
        for mode in modes:
            config=f'[options]\nmode {mode}\ndepth 32\n[engines]\nsmtbmc boolector\n[script]\nread -formal '+ ' '.join(files)+'\nprep -top student_mini_dma_contract_harness\ndelete t:$print\n[files]\n'+'\n'.join(files)+'\n'
            (directory/(mode+'.sby')).write_text(config)
            result=subprocess.run([str(tools/'sby'),'-d',str(directory/mode),str(directory/(mode+'.sby'))],cwd=directory,env=env,capture_output=True,timeout=60)
            (directory/(mode+'.log')).write_bytes(result.stdout+result.stderr)
            status=(directory/mode/'status').read_text().split()[0] if (directory/mode/'status').exists() else 'ERROR'
            expected='PASS' if tag=='baseline' else 'FAIL'
            record=dict(name=tag,mode=mode,tool_status=status,expected_status=expected,accepted=status==expected,exit_code=result.returncode)
            records.append(record);print(json.dumps(record),flush=True)
            if tag=='baseline' and status!='PASS':break
        if tag=='baseline' and not all(row['accepted'] for row in records):break
    passed=len(records)==10 and all(row['accepted'] for row in records)
    report=dict(status='PASS' if passed else 'HOLD',scope='mini native DMA boundary only, not complete SoC protocol or operator qualification',
                formal_baseline=False,depth=32,mutants_killed=sum(r['name']!='baseline' and r['accepted'] for r in records),
                bindings=bindings,tool_hashes=tool_hashes,records=records,
                artifacts={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()})
    (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(work/'report.json'),status=report['status'],mutants_killed=report['mutants_killed'])),flush=True)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
