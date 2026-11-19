#!/usr/bin/env python3
"""Freeze explicit student-mini inputs and independent golden outputs.

Golden generation is not a platform run. No actual field or hardware PASS is
emitted here. Protocol observations and primitive witnesses are separate from
the numeric expected output and must also be collected on the target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'shared/python')]
from scripts.student_mini import read_contracts, sha
from soc_ai_labs.rtl_oracle import (FixedSoftmaxState, int32_scale_to_q5_11,
    merge_split_states_canonical, moe_expert_rtl_oracle, bf16_rne_bits, _round_divide_even)


class LCG32:
    def __init__(self, seed):
        self.state = seed

    def array(self, shape):
        values = []
        for _ in range(int(np.prod(shape))):
            self.state = (1664525*self.state + 1013904223) & 0xffffffff
            values.append(((self.state >> 24) & 15)-8)
        return np.array(values, dtype=np.int8).reshape(shape)


def case_catalog():
    p1 = [('minimum',1,1,1), ('full-page',1,4,2), ('tail-page',1,5,2),
          ('causal',2,5,2), ('noncausal',2,5,2), ('score-tie',1,4,1),
          ('late-maximum',1,5,2), ('topk-exceeds-length',1,1,4),
          ('shuffled-pages',1,5,2), ('poison-padding',1,5,2), ('random-maximum',2,8,4),
          ('bad-length',0,1,1)]
    p2 = [('minimum',1,1), ('two-splits',2,2), ('full-page',4,1), ('unequal-splits',5,2),
          ('four-splits',8,4), ('late-maximum',5,2), ('exp-clamp',5,2), ('arrival-order',8,4),
          ('shuffled-pages',5,2), ('poison-padding',5,2), ('bad-length',0,1), ('bad-split',5,3)]
    p3 = ['minimum', 'balanced', 'single-hot', 'inactive-expert-poison', 'route-tie',
          'route-zero', 'route-one', 'route-half', 'row-permutation', 'cancellation', 'bad-expert', 'bad-hidden']
    common = ['all-zero','int8-min','int8-max','alternating','scale-min','scale-max',
              'rne-positive-even','rne-positive-odd','rne-negative-even','rne-negative-odd',
              'saturate-min','saturate-max','scale-zero','scale-negative','scale-nan',
              'scale-positive-inf','scale-negative-inf','dma-error','backpressure','response-hold','reset-recovery']
    rows = []
    for operator in ('p1','p2','p3'):
        base = p1 if operator == 'p1' else p2 if operator == 'p2' else p3
        for index, item in enumerate(base, 1):
            if operator == 'p1':
                name,q,n,k = item; shape=dict(query=q,length=n,topk=k)
            elif operator == 'p2':
                name,n,splits = item; shape=dict(query=1,length=n,splits=splits)
            else:
                name=item; shape=dict(rows=1 if name=='minimum' else 2,hidden=0 if name=='bad-hidden' else 16,intermediate=16,experts=2,active=1)
            rows.append(dict(id=f'{operator.upper()}-MINI-{index:02}',operator=operator,scenario=name,shape=shape))
        for index, name in enumerate(common, 13):
            shape = dict(rows=2,hidden=16,intermediate=16,experts=2,active=1) if operator=='p3' else dict(query=1,length=5,**({'topk':2} if operator=='p1' else {'splits':2}))
            rows.append(dict(id=f'{operator.upper()}-MINI-{index:02}',operator=operator,scenario=name,shape=shape))
    # Append, never renumber existing case IDs when filling a coverage gap.
    rows.append(dict(id='P2-MINI-34',operator='p2',scenario='two-query-maximum',shape=dict(query=2,length=8,splits=4)))
    return rows


def numeric_inputs(case, seed):
    rng=LCG32(seed)
    shape=case['shape']; op=case['operator']; pattern=case['scenario']
    if op in ('p1','p2'):
        q,n=shape['query'],shape['length']
        data=dict(query=rng.array((q,12)),keys=rng.array((n,12)),values=rng.array((n,8)),
                  index_query=rng.array((q,8)),index_keys=rng.array((n,8)))
    else:
        r,h,d=shape['rows'],shape['hidden'],shape['intermediate']
        data=dict(activations=rng.array((r,h)),gate=rng.array((2,d,h)),up=rng.array((2,d,h)),down=rng.array((2,h,d)))
    for value in data.values():
        if pattern=='all-zero': value.fill(0)
        elif pattern=='int8-min': value.fill(-128)
        elif pattern=='int8-max': value.fill(127)
        elif pattern in ('alternating','cancellation'): value.flat[:]=np.resize([-128,127],value.size)
    if op in ('p1','p2'):
        if pattern=='score-tie': data['index_query'].fill(0); data['query'].fill(0)
        if pattern=='late-maximum':
            data['query'].fill(1);data['keys'].fill(-2);data['keys'][-1].fill(7)
            data['index_query'].fill(1);data['index_keys'].fill(-2);data['index_keys'][-1].fill(7)
        if pattern=='exp-clamp': data['query'].fill(127);data['keys'].fill(-128);data['keys'][-1].fill(127)
        # P1's frozen MLA boundary shares latent KV: the value vector is the
        # first NOPE_DIM key lanes, not an independently addressable V tensor.
        if op=='p1':data['values']=data['keys'][:,:8].copy()
    data={key:value.tolist() for key,value in data.items()}
    scale=2**-16 if pattern=='scale-min' else 2**16 if pattern=='scale-max' else 2**-6
    invalid={'scale-zero':0.,'scale-negative':-1.,'scale-nan':'NaN','scale-positive-inf':'+Inf','scale-negative-inf':'-Inf'}
    data['scales']=dict(input=1.,gate=2**-6,up=2**-6,intermediate=2**-6,down=scale,score=scale,value=scale)
    if pattern in invalid:
        data['scales']['input' if op=='p3' else 'score']=invalid[pattern]
    if op=='p3':
        r=shape['rows']; ids=[i%2 for i in range(r)]
        if pattern in ('single-hot','inactive-expert-poison','route-tie'): ids=[0]*r
        if pattern=='bad-expert':ids[0]=3  # ID 2 is reserved for Nano's shared expert.
        if pattern=='inactive-expert-poison':
            for key in ('gate','up','down'):data[key][1]=np.full_like(np.asarray(data[key][1]),127).tolist()
        if pattern=='row-permutation':data['activations'].reverse();ids.reverse()
        data['expert_ids']=ids
        data['router_logits']=[[0,0] if pattern=='route-tie' else [1 if e==chosen else 0 for e in range(2)] for chosen in ids]
        data['route_weights']=[0. if pattern=='route-zero' else 1. if pattern=='route-one' else .5]*r
    page=1 if pattern=='minimum' else 4
    length=shape.get('length',shape.get('rows',1))
    pages=list(range((length+page-1)//page))
    if pattern in ('shuffled-pages','poison-padding'):pages=[3,0][:len(pages)]
    data['layout']=dict(page_size=page,pages=pages,causal=pattern=='causal',padding_value=127 if pattern=='poison-padding' else 0)
    data['protocol']=dict(backpressure_seed=seed,backpressure_probability=.5 if pattern=='backpressure' else 0,
                          response_hold_cycles=17 if pattern=='response-hold' else 0,
                          inject_dma_error=pattern=='dma-error',reset_and_reissue=pattern=='reset-recovery')
    if pattern.startswith('rne-'):
        numerator={'rne-positive-even':5,'rne-positive-odd':7,'rne-negative-even':-5,'rne-negative-odd':-7}[pattern]
        data['primitive_witness']=dict(kind='rne-integer-division',numerator=numerator,denominator=2)
    if pattern.startswith('saturate-'):
        data['primitive_witness']=dict(kind='int8-saturation',value=-129 if pattern=='saturate-min' else 128)
    return data


def golden(case, inputs):
    name=case['scenario'];op=case['operator'];shape=case['shape']
    status = 'BAD_LENGTH' if name=='bad-length' else 'BAD_DESCRIPTOR' if name in ('bad-split','bad-expert','bad-hidden') else 'NUMERIC_ERROR' if name in ('scale-zero','scale-negative','scale-nan','scale-positive-inf','scale-negative-inf') else 'BUS_ERROR' if name=='dma-error' else 'OK'
    result=dict(expected_status=status,oracle='soc_ai_labs.rtl_oracle',hardware_execution=False,actual=None)
    if status!='OK':
        result.update(output_shape=[],output_bits=[],output_values=[],expected_events=['error-response','no-output-commit'])
        result['expected_events'].append('no-new-payload-dma-after-error')
        return result
    if op=='p3':
        a=lambda key:np.asarray(inputs[key],dtype=np.int8)
        s=inputs['scales']
        values=moe_expert_rtl_oracle(a('activations'),a('gate'),a('up'),a('down'),np.asarray(inputs['expert_ids']),np.asarray(inputs['route_weights'],dtype=np.float32),input_scale=s['input'],gate_scale=s['gate'],up_scale=s['up'],intermediate_scale=s['intermediate'],down_scale=s['down'],rows_per_tile=1)
    else:
        q=np.asarray(inputs['query'],dtype=np.int32);keys=np.asarray(inputs['keys'],dtype=np.int32);v=np.asarray(inputs['values'],dtype=np.int8)
        outputs=[];selected=[]
        for row in range(shape['query']):
            visible=shape['length']-shape['query']+row+1 if inputs['layout']['causal'] else shape['length']
            ids=list(range(visible))
            if op=='p1':
                scores=np.asarray(inputs['index_keys'],dtype=np.int32) @ np.asarray(inputs['index_query'][row],dtype=np.int32)
                ids=sorted(ids,key=lambda i:(-int(scores[i]),i))[:shape['topk']]
                # Stable selector emits score order; physical reference consumes that same order.
                states=[ids]
            else:
                # The scalar B0 scans ceil(L / splits) contiguous tokens per
                # split, stopping at L; canonical merge ignores empty tails.
                chunk=(len(ids)+shape['splits']-1)//shape['splits']
                states=[ids[start:start+chunk] for start in range(0,len(ids),chunk)]
                result['split_token_ids']=states
            built={}
            for split,chunk in enumerate(states):
                state=FixedSoftmaxState.empty(8)
                for token in chunk:
                    state.update(score_q5_11=int32_scale_to_q5_11(int(q[row]@keys[token]),inputs['scales']['score']),value=v[token])
                built[split]=state
            order=list(reversed(built)) if name=='arrival-order' else list(built)
            state=merge_split_states_canonical(built,order)
            outputs.append(state.value_bf16(value_scale=inputs['scales']['value']))
            selected.append(ids)
        values=np.asarray(outputs,dtype=np.float32)
        result['selected_token_ids']=selected
    result.update(output_shape=list(values.shape),output_values=values.astype(float).reshape(-1).tolist(),
                  output_bits=[bf16_rne_bits(float(value)) for value in values.reshape(-1)],expected_events=['exactly-one-completion','stable-response-until-ready'])
    if name=='reset-recovery':result['expected_events']+=['no-spurious-pre-reset-completion','reissued-command-passes']
    witness=inputs.get('primitive_witness')
    if witness:
        result['primitive_witness_result']=_round_divide_even(witness['numerator'],witness['denominator']) if witness['kind']=='rne-integer-division' else max(-128,min(127,witness['value']))
        result['expected_events'].append('primitive-witness-executed-on-target')
    return result


def build(output):
    spec,_=read_contracts();cases=case_catalog()
    source_paths=[Path(__file__),ROOT/'grading/student-mini/spec.json',ROOT/'shared/python/soc_ai_labs/rtl_oracle.py',ROOT/'shared/python/soc_ai_labs/numeric.py']
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in source_paths}
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    destination=output/identity
    destination.mkdir(parents=True,exist_ok=False)
    records=[]
    for case in cases:
        for seed in spec['seeds']:
            inputs=numeric_inputs(case,seed)
            item=dict(case=case,seed=seed,prng='LCG32:1664525,1013904223,mod2^32;high-byte-low4-minus8',inputs=inputs,golden=golden(case,inputs))
            records.append(item)
    path=destination/'vectors.jsonl'
    with path.open('w',encoding='utf-8') as handle:
        for row in records:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    manifest=dict(schema_version=1,release_id=spec['release_id'],kind='golden-only',status='HOLD',hardware_complete=False,
                  input_sha256=identity,bindings=bindings,cases=cases,seeds=spec['seeds'],record_count=len(records),
                  artifacts={'vectors.jsonl':sha(path)},boundary='Golden is not actual. Error events, primitive witnesses, physical power and source-bound hardware replay remain required.')
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return destination,manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'grading/evidence/student-mini-v1/golden')
    args=parser.parse_args()
    destination,manifest=build(args.output)
    print(json.dumps(dict(path=str(destination),cases=len(manifest['cases']),records=manifest['record_count'],status='HOLD',hardware_complete=False),ensure_ascii=False,indent=2))
