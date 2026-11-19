"""Replay full Q/K/V mini P2 inputs through RTL, never host-computed scores."""
import ast
import json
import os
from pathlib import Path
import struct
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from tests.rtl.test_p2_litex_b0 import reset,issue_and_wait,hardware_counters,put
from tests.rtl.test_student_mini_p3 import memory,reset_inflight
from soc_ai_labs.rtl_oracle import fp32_bits


def fill(item):
    inputs=item['inputs'];shape=item['case']['shape'];layout=inputs['layout'];data={}
    query,kv,pages,scales,out=0x2000,0x4000,0x6000,0x8000,0x9000
    for row,values in enumerate(inputs['query']):put(data,query+row*16,bytes(v&255 for v in values)+bytes(4))
    page_size=layout['page_size'];page_ids=layout['pages']
    used=set()
    for token,keys in enumerate(inputs['keys']):
        slot=page_ids[token//page_size]*page_size+token%page_size;used.add(slot)
        put(data,kv+slot*32,bytes(v&255 for v in keys)+bytes(4)+bytes(v&255 for v in inputs['values'][token])+bytes(8))
    capacity=(max(page_ids)+1)*page_size if page_ids else 0
    for token in range(capacity):
        if token not in used:put(data,kv+token*32,bytes([layout['padding_value']&255])*32)
    if page_ids:put(data,pages,struct.pack('<'+'I'*len(page_ids),*page_ids))
    special={'NaN':float('nan'),'+Inf':float('inf'),'-Inf':float('-inf')}
    score=inputs['scales']['score'];score=special.get(score,score) if isinstance(score,str) else score
    put(data,scales,struct.pack('<4I',fp32_bits(score),fp32_bits(inputs['scales']['value']),0,0))
    # Raw descriptor intentionally permits illegal length/split fields to reach RTL.
    words=[1|(2<<8),1,shape['query'],shape['length'],query,kv,pages,0,len(page_ids),0,0,scales,out,0,page_size|(shape['splits']<<16),0]
    put(data,0x1000,struct.pack('<16I',*words))
    return data,out,query


@cocotb.test()
async def replay_explicit_mini_vectors(dut):
    records=[json.loads(line) for line in Path(os.environ['STUDENT_MINI_VECTORS']).read_text().splitlines()]
    records=[row for row in records if row['case']['operator']=='p2']
    limit=int(os.environ.get('STUDENT_MINI_LIMIT','0'))
    if limit:records=records[:limit]
    cocotb.start_soon(Clock(dut.clk_i,10,unit='ns').start())
    statuses={0:'OK',1:'BAD_DESCRIPTOR',2:'BAD_LENGTH',3:'BAD_PAGE',4:'NUMERIC_ERROR',5:'BUS_ERROR'}
    failures=[]
    with Path(os.environ['STUDENT_MINI_ACTUAL']).open('x') as handle:
        for item in records:
            case=item['case'];inputs=item['inputs'];seed=item['seed'];await reset(dut)
            data,out,fault=fill(item);trace=[]
            server=cocotb.start_soon(memory(dut,data,trace,seed,inputs['protocol']['backpressure_probability'],fault if inputs['protocol']['inject_dma_error'] else None))
            reset_observation=None
            if case['scenario']=='reset-recovery':reset_observation=await reset_inflight(dut,2,reset)
            status,cycles=await issue_and_wait(dut,0x1000,hold_cycles=inputs['protocol']['response_hold_cycles'],timeout_cycles=300000)
            counters=hardware_counters(dut);server.cancel()
            bits=[int.from_bytes(bytes(data.get(out+i*2+j,0) for j in range(2)),'little') for i in range(case['shape']['query']*8)] if status==0 else []
            actual=[struct.unpack('<f',struct.pack('<I',b<<16))[0] for b in bits]
            match=statuses.get(status)==item['golden']['expected_status'] and bits==item['golden']['output_bits']
            missing=['primitive-witness-executed-on-target'] if 'primitive_witness' in inputs else []
            if case['scenario']=='arrival-order':missing.append('out-of-order-split-protocol-witness')
            row=dict(platform='accelerator',operator='p2',case_id=case['id'],seed=seed,backend='verilator-rtl',
                     status='FAIL' if not match else 'HOLD' if missing else 'PASS',numeric_match=match,actual_status=statuses.get(status),
                     actual=actual,actual_bits=bits,cycles=cycles,**counters,transactions=trace,missing_witnesses=missing,
                     reset_observation=reset_observation,source='p2-student-mini-full-vector-rtl',physical_complete=False)
            handle.write(json.dumps(row,allow_nan=False)+'\n');handle.flush()
            print('STUDENT_MINI '+json.dumps({k:v for k,v in row.items() if k!='transactions'}),flush=True)
            if not match:failures.append((case['id'],seed))
            await Timer(1,unit='ns')
    assert not failures,f'bit-exact/status failures: {failures}'


if __name__=='__main__':
    from runner import launch
    tree=ast.parse((ROOT/'tests/rtl/test_p2_b0_timing_foundation.py').read_text())
    call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='launch')
    sources=ast.literal_eval(call.args[2])+['shared/rtl/int32_scale_to_q5_11_finalize_pipeline.sv','shared/rtl/p2_student_mini_vector.sv','shared/rtl/p2_student_mini_top.sv']
    launch('student_mini_p2','p2_student_mini_top',sources,
           defines=[f'EXP_Q15_MEM_FILE="{ROOT / "shared/rtl/exp_q15_q6.mem"}"','P2_MERGE_PRODUCT_PIPELINE','P2_MERGE_PRODUCT_STEP_CUT','P2_MERGE_RESCALE_PIPELINE'],
           include_dirs=['shared/rtl'],test_module='student_mini_p2',trace=False)
