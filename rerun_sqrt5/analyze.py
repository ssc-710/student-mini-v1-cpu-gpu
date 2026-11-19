"""Decode and audit only the fresh logs produced by experiment.py."""
import json
from pathlib import Path
import re
from experiment import HERE, ROOT, save, sha

model=ROOT/'sources/build/student-mini/native-nano/876398eac822028468e275044f350988a847429d5c3a2f3aed2be1e74ca47572'
tokenizer=json.loads((model/'inputs.json').read_text())['tokenizer']
decode={int(v):k for k,v in tokenizer['characters'].items()}
manifest=json.loads((HERE/'image/manifest.json').read_text())
results={}
for name in ('cpu','gpu'):
    log=(HERE/(name+'.log')).read_text()
    receipt=json.loads((HERE/(name+'.receipt.json')).read_text())
    assert receipt['complete'] and receipt['log_sha256']==sha(HERE/(name+'.log'))
    assert re.search(r'STUDENT_NATIVE_'+name.upper()+r' status=0 count=11',log)
    rows=[]
    for line in log.splitlines():
        if not line.startswith('STUDENT_NATIVE_TOKEN '):continue
        fields=dict(x.split('=',1) for x in line.split()[1:])
        row=dict(step=int(fields['step']),token=int(fields['token']),text=decode.get(int(fields['token']),'<EOS>'),
            hidden=fields['hidden'].split(','),logits=fields['logits'].split(','))
        assert len(row['hidden'])==16 and len(row['logits'])==256
        if 'elapsed_cycles' in fields:
            hi,lo=map(int,fields['elapsed_cycles'].split(':'));row['elapsed_cycles']=(hi<<32)+lo
        rows.append(row)
    assert [x['step'] for x in rows]==list(range(11)) and rows[-1]['token']==4
    total=receipt['completion_seconds']
    results[name]=dict(answer=''.join(decode.get(x['token'],'') for x in rows),
        tokens=[x['token'] for x in rows],generated_tokens_including_eos=len(rows),answer_tokens_excluding_eos=10,
        qa_wall_seconds=total,wall_tokens_per_second_including_eos=len(rows)/total,
        wall_answer_tokens_per_second=10/total,started_at_utc=receipt['started_at_utc'])
    if name=='cpu':
        results[name]['generation_boundary_wall_seconds']=receipt['generation_summary_seconds']-receipt['generation_begin_seconds']
        results[name]['generation_cycles']=int(re.search(r'count=11 cycles=0:(\d+)',log)[1])
    save(name+'.token-stream.json',rows)
same=all(a[k]==b[k] for a,b in zip(json.loads((HERE/'cpu.token-stream.json').read_text()),
    json.loads((HERE/'gpu.token-stream.json').read_text())) for k in ('step','token','hidden','logits'))
assert same
save('results.json',dict(question=manifest['question'],prompt_tokens=manifest['prompt_tokens'],
    unknown_characters=manifest['unknown_characters'],image_sha256=manifest['image_sha256'],
    model_ptq_sha256=sha(model/'ptq.npz'),cpu_gpu_token_hidden_logits_equal=same,results=results,
    timing_definition='Monotonic host wall time from fresh process launch to reception of COMPLETE. Excludes build; CPU includes boot and UART state dump; GPU includes initialization/JIT/input upload/compute/readback/state dump. Not physical chip performance.',
    token_timing_limit='Both targets dump tokens after generation. CPU has actual per-step simulated cycle counters; GPU has no per-step generation timing. Event timestamps are reception timestamps, not live token emission.'))
c,g=results['cpu'],results['gpu']
report=f'''# 根号5：全新 RTL / SimX 问答

问题：根号5等于几？

本轮 CPU VexRiscv RTL、GPU Vortex SimX 都实际完成了一次自回归推理，回答均为：**{c['answer']}**。这是模型的真实错误回答；数学上 √5 ≈ 2.23606797749979。

## 输入与执行

原始 tokenizer 不含“根、号、5”，模型实际收到 `[UNK][UNK][UNK]等于几？`，完整输入 ID：`{manifest['prompt_tokens']}`。未修改权重、词表或预填答案；镜像 `contains_expected_tokens=false`。

新问题编码后的镜像与旧问题逐字节相同（SHA256 `{manifest['image_sha256']}`）。CPU 核对完整补齐后的 loader 一致后，复用已编译的 Vsim，启动新进程并重新采集输出；没有复用旧推理结果。GPU 生成新的 hash 目录、重新编译 native_nano，复用匹配配置的 SimX 运行库，再启动新进程执行。GPU 配置 RV32 / 1 core / 2 warps / 4 threads / STD FPU，整个会话由单个设备线程执行。

## 本轮结果与计时

| 后端 | UTC 开始 | 问答总墙钟秒 | token/s（含 EOS） | token/s（不含 EOS） |
|---|---|---:|---:|---:|
| CPU RTL | {c['started_at_utc']} | {c['qa_wall_seconds']:.6f} | {c['wall_tokens_per_second_including_eos']:.6f} | {c['wall_answer_tokens_per_second']:.6f} |
| GPU SimX | {g['started_at_utc']} | {g['qa_wall_seconds']:.6f} | {g['wall_tokens_per_second_including_eos']:.6f} | {g['wall_answer_tokens_per_second']:.6f} |

口径：单调时钟，从本轮目标进程启动到接收到 COMPLETE；不含编译。CPU 包含启动、输入装载和 UART 输出完整状态；GPU 包含运行库初始化、可能的 JIT、上传、计算、回读和状态输出。两端输出开销不同，不能据此直接比较硬件算力。这是仿真器实际墙钟吞吐，不是物理 CPU/GPU 的 token/s。含 EOS 计 11 token，不含 EOS 计 10 token。

CPU BEGIN 到生成摘要接收耗时 {c['generation_boundary_wall_seconds']:.6f} 秒（仍含边界 UART 开销），生成计数 {c['generation_cycles']:,} 个模拟周期。没有把此计数换算成未经验证的物理芯片时间。GPU 未加独立 kernel 或逐 token 计时，因此不声称测得纯生成吞吐、TTFT 或逐 token 延迟。

## token 流与一致性

两端 ID 均为 `{c['tokens']}`。

解码顺序：`我 → 无 → 法 → 获 → 知 → 实 → 时 → 天 → 气 → 。 → <EOS>`。

11 步的 token ID、每步 16 项 hidden、256 项 logits 全部逐项相等。CPU 每步累计模拟周期保存在 cpu.token-stream.json。

注意：两端程序都在生成完成后批量打印 token。events.jsonl 的时间戳是日志接收时间，不是实时 token 生成时间；CPU 的 elapsed_cycles 才是回调记录的模拟生成时间。GPU 只记录 token 顺序与状态，没有逐 token 生成时间。

## 可复核文件

- cpu.log / gpu.log：本轮原始输出，包含 status=0 与 COMPLETE count=11 p1=1 p2=10 p3=40。
- cpu.token-stream.json / gpu.token-stream.json：逐步 token、解码、hidden、logits；CPU 另有 elapsed_cycles。
- cpu.events.jsonl / gpu.events.jsonl：逐行单调时钟接收记录。
- cpu.receipt.json / gpu.receipt.json：新进程 PID、UTC、命令、耗时、日志摘要。CPU 在 COMPLETE 后正常主动终止持续运行的 SoC 仿真，退出码 -15；GPU 退出码见 receipt。
- cpu-bindings.json / gpu-bindings.json：运行二进制、输入与库的 SHA256；gpu-build.log 为本轮新编译记录；gpu-command.txt 为运行环境与命令展开。
- results.json：机器可读汇总；experiment.py、analyze.py：准备、执行、核对过程。

首次准备使用系统 Python 缺少所需依赖而失败，尚未执行目标；切换工作包已备好的 cpu-venv 后准备成功。本报告只使用随后成功的新运行日志。
'''
(HERE/'REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
