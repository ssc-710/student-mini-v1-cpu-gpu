"""Actual parameterized P3 RTL replay of the explicit mini golden corpus.

Unimplemented primitive/reset witnesses stay HOLD; numeric replay cannot
silently stand in for the full required test or a physical baseline.
"""
import json
import os
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'shared/python')]

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import numpy as np

from tests.rtl.test_p3_litex_b0 import put, descriptor, reset, issue, hardware_counters
from soc_ai_labs.rtl_oracle import fp32_bits


async def memory(dut, contents, transactions, seed, probability=0., fault=None):
    import random
    rng=random.Random(seed);pending=None
    dut.mem_req_ready_i.value=1
    while True:
        await RisingEdge(dut.clk_i)
        accepted=None
        if not dut.rst_ni.value:
            pending=None;dut.mem_rsp_valid_i.value=0;dut.mem_rsp_error_i.value=0
            continue
        if dut.mem_req_valid_o.value and dut.mem_req_ready_i.value:
            accepted=(int(dut.mem_req_addr_o.value),int(dut.mem_req_write_o.value),int(dut.mem_req_wdata_o.value),int(dut.mem_req_wstrb_o.value))
        if dut.mem_rsp_valid_i.value and dut.mem_rsp_ready_o.value:
            dut.mem_rsp_valid_i.value=0;dut.mem_rsp_error_i.value=0
        if pending is not None and not dut.mem_rsp_valid_i.value:
            address,write,data,strobe=pending
            if write:
                raw=data.to_bytes(16,'little')
                for lane in range(16):
                    if strobe & (1<<lane):contents[address+lane]=raw[lane]
                dut.mem_rsp_rdata_i.value=0
            else:dut.mem_rsp_rdata_i.value=int.from_bytes(bytes(contents.get(address+i,0) for i in range(16)),'little')
            dut.mem_rsp_error_i.value=int(address==fault);dut.mem_rsp_valid_i.value=1;pending=None
        if accepted is not None:transactions.append(accepted[:2]);pending=accepted
        dut.mem_req_ready_i.value=int(rng.random()>=probability)


async def reset_inflight(dut,opcode,reset_fn):
    """Abort a real accepted command, check silence, then allow clean reissue."""
    dut.cmd_opcode_i.value=opcode;dut.cmd_desc_addr_i.value=0x1000;dut.cmd_valid_i.value=1
    for _ in range(100):
        if dut.cmd_ready_o.value:break
        await RisingEdge(dut.clk_i)
    else:raise AssertionError('reset probe command was not accepted')
    await RisingEdge(dut.clk_i);dut.cmd_valid_i.value=0
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        assert not dut.rsp_valid_o.value, 'probe completed before reset injection'
    await reset_fn(dut)
    for _ in range(8):
        await RisingEdge(dut.clk_i);await Timer(1,unit='ns')
        assert not dut.rsp_valid_o.value, 'spurious completion after reset'
    return dict(command_accepted=True,abort_after_cycles=20,silent_post_reset_cycles=8)


def fill(item):
    inputs=item['inputs'];shape=item['case']['shape'];data={}
    q,tile,route,weights,scales,out=0x2000,0x3000,0x4000,0x5000,0x9000,0xa000
    put(data,q,np.asarray(inputs['activations'],dtype=np.int8).tobytes())
    stride=shape['hidden']*shape['intermediate']*3
    for expert in range(2):
        put(data,weights+expert*stride,b''.join(np.asarray(inputs[key][expert],dtype=np.int8).tobytes() for key in ('gate','up','down')))
    put(data,route,np.asarray(inputs['route_weights'],dtype='<f4').tobytes())
    scale_values=[inputs['scales'][key] for key in ('input','gate','up','intermediate','down')]
    special={'NaN':float('nan'),'+Inf':float('inf'),'-Inf':float('-inf')}
    put(data,scales,struct.pack('<5I',*(fp32_bits(special.get(v,v) if isinstance(v,str) else v) for v in scale_values)))
    for row,expert in enumerate(inputs['expert_ids']):put(data,tile+16*row,struct.pack('<4I',row,1,expert,0))
    # Build a valid envelope, then inject the illegal wire field. The host-side
    # descriptor validator must not replace the RTL's negative-input test.
    raw=bytearray(descriptor(rows=shape['rows'],tiles=shape['rows'],hidden=max(1,shape['hidden']),intermediate=max(1,shape['intermediate']),experts=2,q_addr=q,tile_addr=tile,route_addr=route,weight_addr=weights,scale_addr=scales,output_addr=out))
    struct.pack_into('<I',raw,12,shape['hidden'])
    struct.pack_into('<I',raw,56,shape['intermediate'] | (2<<16))
    put(data,0x1000,raw)
    return data,out


@cocotb.test()
async def replay_explicit_mini_vectors(dut):
    path=Path(os.environ['STUDENT_MINI_VECTORS'])
    output=Path(os.environ['STUDENT_MINI_ACTUAL'])
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    records=[r for r in records if r['case']['operator']=='p3']
    limit=int(os.environ.get('STUDENT_MINI_LIMIT','0'))
    if limit:records=records[:limit]
    cocotb.start_soon(Clock(dut.clk_i,10,unit='ns').start())
    output.parent.mkdir(parents=True,exist_ok=True)
    status_names={0:'OK',1:'BAD_DESCRIPTOR',2:'BAD_LENGTH',3:'BAD_PAGE',4:'NUMERIC_ERROR',5:'BUS_ERROR'}
    failures=[]
    with output.open('x',encoding='utf-8') as handle:
        for item in records:
            case=item['case'];seed=item['seed'];inputs=item['inputs']
            await reset(dut)
            data,out=fill(item);transactions=[]
            server=cocotb.start_soon(memory(dut,data,transactions,seed,inputs['protocol']['backpressure_probability'],0x2000 if inputs['protocol']['inject_dma_error'] else None))
            reset_observation=None
            if case['scenario']=='reset-recovery':reset_observation=await reset_inflight(dut,3,reset)
            (status,cycles),_=await issue(dut,0x1000,hold=inputs['protocol']['response_hold_cycles'],timeout=200000)
            counters=hardware_counters(dut);server.cancel()
            bits=[int.from_bytes(bytes(data.get(out+2*i+j,0) for j in range(2)),'little') for i in range(case['shape']['rows']*case['shape']['hidden'])] if status==0 else []
            actual=[struct.unpack('<f',struct.pack('<I',value<<16))[0] for value in bits]
            numeric_match=status_names.get(status)==item['golden']['expected_status'] and bits==item['golden']['output_bits']
            missing=[]
            if 'primitive_witness' in inputs:missing.append('primitive-witness-executed-on-target')
            row=dict(platform='accelerator',operator='p3',case_id=case['id'],seed=seed,backend='verilator-rtl',status='FAIL' if not numeric_match else 'HOLD' if missing else 'PASS',
                     numeric_match=numeric_match,actual_status=status_names.get(status,f'UNKNOWN_{status}'),actual=actual,actual_bits=bits,cycles=cycles,**counters,
                     transactions=transactions,missing_witnesses=missing,reset_observation=reset_observation,source='parameterized-p3-b12-rtl',physical_complete=False)
            if not numeric_match:failures.append((case['id'],seed))
            handle.write(json.dumps(row,allow_nan=False)+'\n');handle.flush()
            print('STUDENT_MINI '+json.dumps({k:v for k,v in row.items() if k!='transactions'}),flush=True)
            await Timer(1,unit='ns')
    assert not failures, f'bit-exact/status failures: {failures}'


if __name__=='__main__':
    import ast
    from runner import launch
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/'tests/rtl/test_p3_b12_output_row_base_litex.py').read_text())
    call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='launch')
    sources=ast.literal_eval(call.args[2])
    launch('student_mini_p3','p3_b12_output_row_base_litex_top',sources,
           parameters={'MAX_HIDDEN':16,'MAX_INTERMEDIATE':16,'PIPELINED_SILU':1,'PIPELINED_SCALE_QUANTIZE':1},
           defines=[f'SILU_Q11_MEM_FILE="{root / "shared/rtl/silu_q11_q6.mem"}"'],include_dirs=['shared/rtl'],test_module='student_mini_p3',trace=False)
