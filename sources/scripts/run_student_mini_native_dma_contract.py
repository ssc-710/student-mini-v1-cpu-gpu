"""Full-payload bounded adapter proof and mutations, never whole-SoC approval."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha
from scripts.retry_student_mini_route import execute_locked_route

MUTATIONS=[
    ('address','litex_native_dma_bridge.sv','addr_q <= req_addr_i;','addr_q <= req_addr_i ^ 16;'),
    ('write-data','litex_native_dma_bridge.sv','wdata_q <= req_wdata_i;','wdata_q <= req_wdata_i ^ 1;'),
    ('write-mask','litex_native_dma_bridge.sv','wstrb_q <= req_wstrb_i;','wstrb_q <= req_wstrb_i ^ 1;'),
    ('read-data','litex_native_dma_bridge.sv','rdata_q <= native_rdata_i;','rdata_q <= native_rdata_i ^ 1;'),
    ('write-fence','litex_native_dma_bridge.sv','state_q <= WRITE_FENCE ? ISSUE_WRITE_FENCE : RESPONSE;','state_q <= RESPONSE;'),
    ('response-stall','litex_native_dma_bridge.sv','assign rsp_valid_o = state_q == RESPONSE;','assign rsp_valid_o = state_q == RESPONSE && rsp_ready_i;'),
    ('error-classification','student_mini_native_dma_bridge.sv',"assign invalid_request=(req_addr_i[31:28]!=4'h4) || (req_addr_i[3:0]!=0);","assign invalid_request=1'b0;"),
    ('reset','litex_native_dma_bridge.sv','state_q <= IDLE;', 'state_q <= ISSUE_READ;'),
]


def mutate(files,name):
    _,filename,old,new=next(r for r in MUTATIONS if r[0]==name)
    expected={'read-data':2,'reset':3}.get(name,1)
    if files[filename].count(old)!=expected:raise ValueError('unexpected mutation multiplicity: '+name)
    result=dict(files);result[filename]=result[filename].replace(old,new,1)
    return result


def main():
    import fcntl
    toolroot=Path('/home/soclab/tools/oss-cad-suite/bin')
    sources=[ROOT/'shared/rtl/litex_native_dma_bridge.sv',ROOT/'shared/rtl/student_mini_native_dma_bridge.sv',
        ROOT/'shared/formal/student_mini_native_dma_full_contract_harness.sv']
    files={p.name:p.read_text() for p in sources}
    paths=sources+[Path(__file__),ROOT/'scripts/retry_student_mini_route.py']
    paths += [toolroot/name for name in ('yosys','sby','yosys-smtbmc','boolector')]
    bindings={str(p):sha(p) for p in paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    work=ROOT/'build/student-mini/native-dma-contract'/identity;work.mkdir(parents=True,exist_ok=False)
    result=dict(status='HOLD',formal_baseline=False,whole_soc_protocol=False,depth=32,
        scope='Actual 128-bit native DMA adapter: full address/data/mask, write fence, error, arbitrary stalls and reset recovery',
        excluded='LiteDRAM controller, DFI pins and CPU firmware integration require separate witnesses',
        assumptions=['initial reset','request held until accepted or reset','read response only while ready'],
        bindings=bindings,records=[])
    started=time.monotonic()
    def heartbeat(stage):
        (work/'heartbeat.json').write_text(json.dumps(dict(stage=stage,updated_at=datetime.now(timezone.utc).isoformat()))+'\n')
    def fresh():
        if any(sha(Path(p))!=v for p,v in bindings.items()):raise ValueError('proof source changed')
    try:
        fresh()
        with Path('/mnt/e/open-soc-ai-labs-temp/persistent-ppa/matrix.lock').open('a') as lock:
            heartbeat('WAITING_FOR_SERIAL_QUEUE');fcntl.flock(lock,fcntl.LOCK_EX);fresh()
            for tag in ['baseline',*(r[0] for r in MUTATIONS)]:
                directory=work/tag;directory.mkdir()
                content=files if tag=='baseline' else mutate(files,tag)
                for name,text in content.items():(directory/name).write_text(text)
                for mode in (['bmc','cover'] if tag=='baseline' else ['bmc']):
                    config=directory/(mode+'.sby')
                    config.write_text(f'[options]\nmode {mode}\ndepth 32\n[engines]\nsmtbmc boolector\n[script]\nread -formal '+
                        ' '.join(files)+'\nprep -top student_mini_native_dma_full_contract_harness\ndelete t:$print\n[files]\n'+
                        '\n'.join(str(directory/name) for name in files)+'\n')
                    command=['env','PATH='+str(toolroot)+':/usr/local/bin:/usr/bin:/bin',str(toolroot/'sby'),'-d',str(directory/mode),str(config)]
                    code=execute_locked_route(command,directory/(mode+'.log'),180,lambda _:heartbeat(tag+'-'+mode))
                    statuspath=directory/mode/'status';status=statuspath.read_text().split()[0] if statuspath.exists() else 'ERROR'
                    expected='PASS' if tag=='baseline' else 'FAIL'
                    row=dict(name=tag,mode=mode,status=status,expected=expected,accepted=status==expected,exit_code=code)
                    result['records'].append(row)
                    if not row['accepted']:raise ValueError('proof/mutation failed: '+tag+' '+mode)
            fresh();result.update(status='NATIVE_DMA_ADAPTER_CONTRACT_STAGE_PASS',
                reason='Bounded full-payload safety, four reachable scenarios, eight mutations; integration remains separate')
    except Exception as error:result['reason']=f'{type(error).__name__}: {error}'
    heartbeat(result['status']);result['elapsed_seconds']=time.monotonic()-started
    result['artifacts']={p.relative_to(work).as_posix():sha(p) for p in work.rglob('*') if p.is_file()}
    (work/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(work=str(work),status=result['status'],reason=result['reason'])),flush=True)
    return 0 if result['status']=='NATIVE_DMA_ADAPTER_CONTRACT_STAGE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
