"""Mini P1 wire replay; independent V inputs are rejected, never silently mapped."""
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
from tests.rtl.test_p1_litex_b0 import reset,issue,hardware_counters,put
from tests.rtl.test_student_mini_p3 import memory,reset_inflight
from soc_ai_labs.deepseek_v32 import CommandDescriptor,CommandFlag,Opcode
from soc_ai_labs.rtl_oracle import fp32_bits


def fill(item):
    inputs=item['inputs'];shape=item['case']['shape'];layout=inputs['layout'];data={}
    if inputs['values']!=[row[:8] for row in inputs['keys']]:raise ValueError('P1 MLA wire contract requires values=latent key[:8]; independent V is not supported')
    q,kv,pages,lengths,scales,out,aux,scratch=0x2000,0x4000,0x6000,0x7000,0x8000,0x9000,0xa000,0xb000
    encode=lambda values:bytes(v&255 for v in values)+bytes(32-len(values))
    for i,row in enumerate(inputs['query']):put(data,q+32*i,encode(row+inputs['index_query'][i]))
    page_size=layout['page_size'];page_ids=layout['pages'];capacity=(max(page_ids)+1)*page_size
    for token,row in enumerate(inputs['keys']):put(data,kv+(page_ids[token//page_size]*page_size+token%page_size)*32,encode(row+inputs['index_keys'][token]))
    # Fill every invalid lane with the declared poison rather than silently zeroing it.
    used={page_ids[t//page_size]*page_size+t%page_size for t in range(shape['length'])}
    for token in range(capacity):
        if token not in used:put(data,kv+32*token,bytes([layout['padding_value']&255])*32)
    put(data,pages,struct.pack('<'+'I'*len(page_ids),*page_ids))
    put(data,lengths,struct.pack('<5I',0,shape['query'],0,len(page_ids),(shape['length']-1)%page_size+1))
    special={'NaN':float('nan'),'+Inf':float('inf'),'-Inf':float('-inf')}
    scale=inputs['scales']['score'];scale=special.get(scale,scale) if isinstance(scale,str) else scale
    put(data,scales,struct.pack('<3I',fp32_bits(2**-11),fp32_bits(scale),fp32_bits(inputs['scales']['value'])))
    flags=CommandFlag.SPARSE_DSA|CommandFlag.PAGED
    if layout['causal']:flags|=CommandFlag.CAUSAL
    put(data,0x1000,CommandDescriptor(Opcode.PREFILL,flags=flags,operator_arg=shape['topk'],batch=1,q_tokens=shape['query'],kv_tokens=capacity,q_addr=q,kv_addr=kv,page_addr=pages,length_addr=lengths,scale_addr=scales,output_addr=out,aux0_addr=aux,scratch_addr=scratch,page_size=page_size,splits=1).pack())
    return data,out,q


@cocotb.test()
async def replay_explicit_mini_vectors(dut):
    records=[json.loads(s) for s in Path(os.environ['STUDENT_MINI_VECTORS']).read_text().splitlines()]
    records=[r for r in records if r['case']['operator']=='p1']
    limit=int(os.environ.get('STUDENT_MINI_LIMIT','0'))
    if limit:records=records[:limit]
    cocotb.start_soon(Clock(dut.clk_i,10,unit='ns').start())
    statuses={0:'OK',1:'BAD_DESCRIPTOR',2:'BAD_LENGTH',3:'BAD_PAGE',4:'NUMERIC_ERROR',5:'BUS_ERROR'}
    failures=[]
    with Path(os.environ['STUDENT_MINI_ACTUAL']).open('x') as handle:
        for item in records:
            case=item['case'];inputs=item['inputs'];seed=item['seed']
            row=dict(platform='accelerator',operator='p1',case_id=case['id'],seed=seed)
            await reset(dut);data,out,fault=fill(item);trace=[]
            server=cocotb.start_soon(memory(dut,data,trace,seed,inputs['protocol']['backpressure_probability'],fault if inputs['protocol']['inject_dma_error'] else None))
            reset_observation=None
            if case['scenario']=='reset-recovery':reset_observation=await reset_inflight(dut,1,reset)
            status,cycles=await issue(dut,0x1000,hold=inputs['protocol']['response_hold_cycles'])
            counters=hardware_counters(dut);server.cancel()
            bits=[int.from_bytes(bytes(data.get(out+2*i+j,0) for j in range(2)),'little') for i in range(case['shape']['query']*8)] if status==0 else []
            actual=[struct.unpack('<f',struct.pack('<I',b<<16))[0] for b in bits]
            match=statuses.get(status)==item['golden']['expected_status'] and bits==item['golden']['output_bits']
            selected=[]
            if status==0:
                for query,expected in enumerate(item['golden']['selected_token_ids']):
                    selected.append([int.from_bytes(bytes(data.get(0xa000+(query*4+i)*4+j,0) for j in range(4)),'little') for i in range(len(expected))])
                match=match and selected==item['golden']['selected_token_ids']
            missing=['primitive-witness-executed-on-target'] if 'primitive_witness' in inputs else []
            row.update(status='FAIL' if not match else 'HOLD' if missing else 'PASS',actual=actual,actual_bits=bits,actual_status=statuses.get(status),cycles=cycles,**counters,backend='verilator-rtl',numeric_match=match,missing_witnesses=missing,transactions=trace,reset_observation=reset_observation,selected_token_ids=selected,physical_complete=False)
            if not match:failures.append((case['id'],seed))
            handle.write(json.dumps(row,allow_nan=False)+'\n');handle.flush()
            print('STUDENT_MINI '+json.dumps({k:v for k,v in row.items() if k!='transactions'}),flush=True)
            await Timer(1,unit='ns')
    assert not failures, f'bit-exact/status/selection failures: {failures}'


if __name__=='__main__':
    from runner import launch
    tree=ast.parse((ROOT/'tests/rtl/test_p1_b2_divider_dot_beat_page_validate_exp_input_visible_meta_validate_recovery.py').read_text())
    call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='launch')
    launch('student_mini_p1','p1_b2_bf16_pipeline_litex_top',ast.literal_eval(call.args[2]),parameters={'HEADS':1,'K_MAX':4,'PIPELINED_SOFTMAX':1,'PIPELINED_SCORE_SCALE':1,'PIPELINED_PAGE_VALIDATE':1},defines=[f'EXP_Q15_MEM_FILE="{ROOT / "shared/rtl/exp_q15_q6.mem"}"','P1_SHARED_SOFTMAX_VECTOR','P1_SOFTMAX_GROUP1','P1_SERIAL_OUTPUT','P1_EXTERNAL_BF16_PIPELINE'],include_dirs=['shared/rtl'],test_module='student_mini_p1',trace=False)
