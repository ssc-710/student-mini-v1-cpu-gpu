#!/usr/bin/env python3
"""Train a real tiny causal MLA/MoE model on CPU, without answer lookup.

This producer emits teacher-side candidate evidence, never platform acceptance.
Quantized checkpoint/platform bit-exact replay is a separate mandatory gate.
"""
from __future__ import annotations

import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import torch
from torch import nn
import torch.nn.functional as F

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import read_contracts, sha

DOMAINS = {
 'greeting': {'answer':'你好！','train':['你好','您好','嗨你好','你好朋友','你好啊','大家好','向你问好','哈喽','嗨朋友','早安','晚上好','下午好'], 'validation':['你好朋友呀','午安'], 'test':['你好呀','早上好','嗨']},
 'identity': {'answer':'我是小助手。','train':['介绍你自己','你叫什么名字','告诉我你是谁','请介绍自己','你的名字是啥','你是什么助手','请问你的身份','说说你的名字','怎么称呼你','你是什么','自我介绍一下','你的身份是什么'], 'validation':['请说你的名字','能介绍你吗'], 'test':['你叫什么','你是谁呀','介绍自己']},
 'weather': {'answer':'我无法获知实时天气。','train':['请问天气情况','现在天气如何','外面是什么天气','天气晴朗吗','明天会有雨吗','外面会下雨吗','天气冷吗','我想查询天气','现在是晴天吗','今天温度是多少','外面热不热','能告诉我天气吗'], 'validation':['这会儿天气如何','此刻天气怎样'], 'test':['今天天气怎么样？','今天会下雨吗？','现在冷不冷？']},
 'arithmetic': {'answer':'等于二。','train':['一加一等于多少','计算一加一','请算一加一','1加1','一加上一','求一加一的和','一与一相加','算算1+1','1+1等于多少','一加一是多少','请问一加一','帮我算一加一'], 'validation':['请计算1加1','告诉我一加一'], 'test':['一加一等于几？','1+1是多少？','一加一？']}
}


def dataset():
    # Vocabulary defines the supported character domain, not held-out answers
    # as runtime rules. Split questions must be disjoint byte-for-byte.
    rows={split:[dict(domain=domain,question=q,answer=row['answer']) for domain,row in DOMAINS.items() for q in row[split]] for split in ('train','validation','test')}
    forbidden={r['question'] for split in ('validation','test') for r in rows[split]}
    augmented={}
    for row in rows['train']:
        for prefix in ('','请问','你好，'):
            for suffix in ('','？','呀','呢','。'):
                question=prefix+row['question']+suffix
                if len(question)<=16 and question not in forbidden:
                    augmented[question]=dict(row,question=question)
    rows['train']=list(augmented.values())
    chars=sorted(set(''.join(row['question']+row['answer'] for split in rows.values() for row in split)))
    tokenizer={'special':{'PAD':0,'BOS':1,'USER':2,'ASSISTANT':3,'EOS':4,'UNK':5},'characters':{c:i+6 for i,c in enumerate(chars)},'vocab_capacity':256}
    if len(chars)+6>256:raise ValueError('character vocabulary exceeds frozen capacity')
    sets=[{r['question'] for r in rows[k]} for k in rows]
    if any(sets[i]&sets[j] for i in range(3) for j in range(i+1,3)):raise ValueError('question leakage')
    if '今天天气怎么样？' in sets[0] | sets[1]:raise ValueError('weather holdout leaked')
    return tokenizer,rows


class Expert(nn.Module):
    def __init__(self):
        super().__init__();self.gate=nn.Linear(16,16,bias=False);self.up=nn.Linear(16,16,bias=False);self.down=nn.Linear(16,16,bias=False)
    def forward(self,x):return self.down(F.silu(self.gate(x))*self.up(x))


class MiniNano(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding=nn.Embedding(256,16);self.position=nn.Embedding(32,16)
        self.norm1=nn.RMSNorm(16);self.norm2=nn.RMSNorm(16);self.final_norm=nn.RMSNorm(16)
        self.q=nn.Linear(16,12,bias=False);self.k=nn.Linear(16,12,bias=False);self.v=nn.Linear(16,8,bias=False);self.out=nn.Linear(8,16,bias=False)
        self.iq=nn.Linear(16,8,bias=False);self.ik=nn.Linear(16,8,bias=False)
        self.router=nn.Linear(16,2,bias=False);self.experts=nn.ModuleList([Expert(),Expert()]);self.shared=Expert();self.head=nn.Linear(16,256,bias=False)

    def forward(self,tokens):
        b,t=tokens.shape;x=self.embedding(tokens)+self.position(torch.arange(t,device=tokens.device));h=self.norm1(x)
        # Sparse top-k prefill mask with a straight-through score-free selector.
        index=self.iq(h)@self.ik(h).transpose(-2,-1)
        causal=torch.ones(t,t,dtype=torch.bool,device=x.device).tril()
        index=index.masked_fill(~causal,float('-inf'))
        ids=index.topk(min(4,t),dim=-1).indices
        selected=torch.zeros_like(causal).expand(b,-1,-1).clone().scatter_(-1,ids,True)&causal
        scores=(self.q(h)@self.k(h).transpose(-2,-1))/math.sqrt(12)
        prob=scores.masked_fill(~selected,float('-inf')).softmax(-1)
        x=x+self.out(prob@self.v(h));h=self.norm2(x)
        route=self.router(h).softmax(-1);chosen=route.argmax(-1)
        routed=torch.zeros_like(h)
        for expert_id,expert in enumerate(self.experts):
            routed=routed+expert(h)*(chosen==expert_id).unsqueeze(-1)*route[...,expert_id:expert_id+1]
        return self.head(self.final_norm(x+self.shared(h)+routed))


def encode(text,tokenizer):return [tokenizer['characters'].get(c,5) for c in text]


def generate(model,question,tokenizer):
    prompt=[1,2]+encode(question,tokenizer)+[3]
    result=[]
    with torch.no_grad():
        for _ in range(12):
            if len(prompt)+len(result)>32:raise ValueError('context overflow')
            token=int(model(torch.tensor([prompt+result],dtype=torch.long))[:,-1].argmax(-1))
            result.append(token)
            if token==4:break
    reverse={v:k for k,v in tokenizer['characters'].items()}
    text=''.join(reverse.get(t,'[UNK]') for t in result if t!=4)
    return result,text


def evaluate(model,rows,tokenizer):
    return [dict(row,tokens=(answer:=generate(model,row['question'],tokenizer))[0],actual_text=answer[1],passed=answer[1]==row['answer']) for row in rows]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--steps',type=int,default=2500);parser.add_argument('--output',type=Path,default=ROOT/'build/student-mini/nano')
    args=parser.parse_args();torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(1);torch.use_deterministic_algorithms(True)
    tokenizer,rows=dataset();spec,_=read_contracts()
    inputs=dict(source_sha256=sha(Path(__file__)),spec_sha256=sha(ROOT/'grading/student-mini/spec.json'),torch_version=torch.__version__,device='cpu',seed=1,threads=2,steps=args.steps,dataset=rows,tokenizer=tokenizer)
    identity=hashlib.sha256(json.dumps(inputs,sort_keys=True,ensure_ascii=False).encode()).hexdigest();work=args.output/identity;work.mkdir(parents=True,exist_ok=False)
    (work/'inputs.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    model=MiniNano().cpu();optimizer=torch.optim.AdamW(model.parameters(),lr=.006,weight_decay=.01)
    sequences=[];labels=[]
    for row in rows['train']:
        prompt=[1,2]+encode(row['question'],tokenizer)+[3];seq=prompt+encode(row['answer'],tokenizer)+[4]
        if len(seq)>32:raise ValueError('training sequence exceeds context')
        inp=seq[:-1];lab=[-100]*(len(prompt)-1)+seq[len(prompt):]
        sequences.append(inp+[0]*(31-len(inp)));labels.append(lab+[-100]*(31-len(lab)))
    x=torch.tensor(sequences,dtype=torch.long);y=torch.tensor(labels,dtype=torch.long);started=time.monotonic()
    log=[];best_state=None;best_rank=(-1,float('-inf'));best_step=None
    for step in range(1,args.steps+1):
        selected=torch.randperm(len(x))[:16];optimizer.zero_grad(set_to_none=True)
        loss=F.cross_entropy(model(x[selected]).reshape(-1,256),y[selected].reshape(-1),ignore_index=-100)
        loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step()
        if step%100==0:
            val=evaluate(model,rows['validation'],tokenizer);passed=sum(v['passed'] for v in val)
            entry=dict(step=step,loss=float(loss.detach()),validation_passed=passed,validation_total=len(val),elapsed_seconds=time.monotonic()-started)
            print(json.dumps(entry),flush=True);log.append(entry)
            rank=(passed,-entry['loss'])
            if rank>best_rank:
                best_rank=rank;best_step=step
                best_state={name:value.detach().cpu().clone() for name,value in model.state_dict().items()}
            if passed==len(val) and step>=500:break
    if best_state is None:raise ValueError('at least 100 steps required for validation-based selection')
    model.load_state_dict(best_state)
    torch.save(model.state_dict(),work/'fp32.pt')
    quantized={};scales={}
    with torch.no_grad():
        for name,value in model.state_dict().items():
            scale=max(float(value.abs().max())/127,2**-16);scales[name]=scale
            quantized[name]=torch.round(value/scale).clamp(-128,127).to(torch.int8)
    torch.save(dict(weights=quantized,scales=scales,source_sha256=sha(work/'fp32.pt')),work/'int8.pt')
    fp32_report=evaluate(model,rows['test'],tokenizer)
    model.load_state_dict({name:value.float()*scales[name] for name,value in quantized.items()})
    ptq_report=evaluate(model,rows['test'],tokenizer)
    payload=dict(schema_version=1,status='HOLD',kind='teacher-cpu-model-candidate',hardware_complete=False,release_id=spec['release_id'],input_sha256=identity,
                 parameters=sum(p.numel() for p in model.parameters()),architecture={'layers':1,'hidden':16,'heads':1,'intermediate':16,'experts':2,'active_experts':1,'shared_experts':1,'vocab':256},
                 elapsed_seconds=time.monotonic()-started,device=str(next(model.parameters()).device),threads=torch.get_num_threads(),training_log=log,selected_step=best_step,selection='validation pass count, then training loss; test never used for selection',fp32=fp32_report,ptq_weight_dequantized=ptq_report,
                 boundary='Teacher CPU candidate only. PTQ report dequantizes weights; it does not establish exact INT8 accumulator/BF16/LUT deployment, RoPE, P2 cache execution, or three-platform Nano acceptance.',
                 artifacts={p.name:sha(p) for p in work.iterdir() if p.is_file()})
    (work/'candidate.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(work=str(work),parameters=payload['parameters'],fp32_pass=sum(r['passed'] for r in fp32_report),ptq_pass=sum(r['passed'] for r in ptq_report),total=len(ptq_report),status='HOLD',elapsed_seconds=payload['elapsed_seconds']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
