# P3 实施现状：HOLD，尚未最终验收

已补fenced GPU五对fresh SimX重复门及generic新fence两臂320exact/10unsupported门，详见CONTINUATION最新入口。CPU inline两次fresh RTL均10,235,712生成周期、757,580 P3周期（相对parent整体约+0.237%、P3约+1.533%吞吐）。当前新ROM bank0 met5在1200s剩9DRC超时FAIL，无新WNS；不能转移旧bank结果。整体仍缺同wrapper完整330故障协议、native330和整核物理/功耗签核。

最新GPU fenced02已完成fresh RTLSIM并审计：生成14,148,604→14,003,538cycles（1.010359x），P3 2,392,124→2,260,888（1.058046x），11state exact；实际ELF global fence已检查。宿主QA94.986882→93.547509s，host .115805→.117587 tokens/s，不能称物理吞吐。详见 `../runs/gpu-full-4t-leader-fenced-rtlsim-20261108-01/audit.json`。旧缺fence观测保持HOLD，不覆盖失败父链。

最新完整root5已fresh执行：CPU baseline/candidate/narrow生成周期12088215/10260016/10260016，11步state exact；1MHz下.909977/1.072123/1.072123 tokens/s，实际回答“我无法获知实时天气。”。GPU 4T-S/C完整诊断生成14563928/14436680 cycles，11步state exact，约1.008814x；非P3仍四lane私有重复，尚非最终协作实现。详细分域时长、证据与下一步见CONTINUATION顶部，以下旧“进行中”字段以该入口为准。

当前新custom/narrow核已fresh跑完1000条冻结benchmark，P1/P2/P3为330/340/330全exact，100case各seed1–10；`runs/cpu-generated-custom-narrow-frozen1000-audit-20261108-01/result.json`已重构输入并审计实际输出。该门非native ABI或MINI31–33专门协议。CPU最终两臂各五次RTL问答周期/状态完全一致。GPU四线程完整诊断两臂11token exact，生成14563928→14436680cycles（1.008814x）、P32351672→2231192（1.053998x），非P3仍四lane重复计算，尚非最终leader-only集成。

最新CPU有效问答：counter三臂各fresh执行完成并逐hash/token-state审计PASS。baseline12088215cycles→P3 custom10260016（1.178187x组合集成收益）；narrow相同10260016cycles。配置1MHz下0.909977→1.072123tokens/s，生成12.088215→10.260016秒，真实回答仍“我无法获知实时天气。”。宿主BEGIN→COMPLETE分别18.830884/18.553527/17.459449秒。证据 `runs/cpu-generated-counter-root5-audit-20261108-01/result.json`。新330及GPU四线程完整LLM和整核PPA仍未完成。

2026-11-08 D026：新生成CPU baseline/candidate首轮完整root5各11步token/state exact，但周期全0；已成对生成开放计数CSR的新核，完整固件重建进行中。P3窄位宽RTL通过SAT、七拍有界等价、1813笔elastic协议及真实新核ISA/reset；同流程route/OpenRCX面积14400→9397um2，局部WNS+3.72→+5.49ns，两臂0路由DRC，逐hash审计PASS。GPU四臂20次fresh SimX完成，4T算法1.11336x、1T-S到4T-C组合3.38394x；只属固定微核。ROM同面积fanout修复剩9DRC超时FAIL。尚无这轮完整问答加速验收；详见PLAN D026和CONTINUATION。

只保留当前状态；历史决策和纠正见 `../PLAN.md` D001起各项，原始成功/失败日志保留在 `../runs/`、`../physical/`。本文件不替代执行证据。

> 2026-11-08 已恢复执行。当前实际工作区为 `D:/college/codex/student-mini-v1-cpu-gpu`。GPU单写者分歧编译修复两臂fresh SimX烟测通过；CPU真实MulPlugin源码集成推进中。最新入口见 `CONTINUATION.md` 顶部。总体仍HOLD，尚无新增完整LLM速度验收。

## 当前状态

| 项目 | 已取得的实际证据 | 尚未覆盖 |
|---|---|---|
| CPU通用候选 | RTL 1000/1000 golden，P3 330/330 | CSA/物理网表不能继承资格 |
| CPU native scale-context | fresh root5 exact；GC/布局候选五次独立RTL稳定为11,389,357生成周期 | native ABI冻结case、P1/P2/十二问/协议及宏化整核后端 |
| GPU通用候选 | SimX 970/1000，P3 320/330 | 旧记录缺MINI30真实fault，不追溯改写 |
| GPU真实fault | 新processor RTL P3 MINI30十seed及普通seed1通过，独立后审通过 | 同wrapper全330、MINI31～33、完整AFU/xrt |
| CPU协议 | 原核scalar MINI31～33共30条UART背压/hold/reset通过 | DFI、CSA与物理接口 |
| 十二问语义回归 | GPU 12/12新配对SimX；CPU 12/12新配对VexRiscv RTL，逐token/hidden/logits一致 | 语义回归不是性能归因或物理资格 |
| CPU当前ROM | 11,735 words/23bank，35,205次定义地址检查及新整核原ROM/banked配对通过 | 全case、未定义地址等价、物理实现 |
| GPU硬件候选 | limb三enabled-edge乘法器本地RTL/SAT、实际LLM RTLSIM | 全核协议与物理签核 |
| GPU局部物理 | 同约束vendor/limb CTS、详细route、OpenRCX输出绑定对照 | 整核IO/全角/PDN/天线/LVS/活动功耗 |
| GPU P3独立计数 | 五对新SimX逐SHA/ELF lowering/20/20/0/40/token-state审计通过，isolated 6,124,279→5,827,334 cycles（1.0509572645x） | 该收益不是RTLSIM/四线程/物理token/s；尚需四线程微核330与isolated RTLSIM |
| CPU prepared-scale RTL | finish合法域SAT、1006笔流水协议通过；复制单元映射超时，单周期finish局部10ns slack -3.3633ns | 复用MUL的分段/多周期前端、decode/hazard、330、root5与宏化整核后端 |
| GPU四线程微核 | pair22同值多writer数据竞争，撤回晋升资格；恢复单writer后显式divergence阈值10000，两臂fresh SimX smoke/独立expected/错误路径PASS，默认阈值对照FAIL | runtime setup复核、完整target wrapper与330；1T-S/1T-C/4T-S/4T-C性能、RTLSIM、full LLM |
| CPU三拍finish/阻塞oracle | 当前SHA reduced SAT；elastic 1813=1791+22；固定seed阻塞复用接口fresh 304=284+20、3344 cycles，Yosys无`$mul`；elastic局部ideal-wire setup/hold +4.3962/+0.1043ns | oracle的8-bit tag不进入生产Vex；尚需stage owner/isRemoved/launched单体接入、330/root5/宏化整核 |
| CPU真实MulPlugin源码接入 | 私有baseline02/candidate03 Scala编译、Spinal1.7.0a整核Verilog生成成功；candidate+finish lint rc0；异常环已修 | 与包内Spinal1.9.4不同，需新配对ISA/LLM验证；尚无330/root5/物理资格 |
| GPU通用4T新目标门 | target13/14两臂各330输入实际SimX，320状态/BF16/primitive exact，10MINI30 unsupported | runtime全局发布竞争、真实fault和MINI31～33协议；不计330合规/速度通过 |

所有新实体产物位于 `optimization/p3/`；`/tmp/p3-workspace` 仅是ASCII软链接，不承载外部文档。未改模型、词表、LUT、golden，未以golden回填目标输出。

## 有效性能结论

- CPU四模式同ELF/ROM/Vsim各五次交错新结果：scalar、block4-i64、block4-i32、scale-context 的P3周期为1,895,648/1,351,410/1,397,090/980,264，生成周期为12,664,245/12,119,748/12,164,349/11,754,128。scale-context相对scalar为P3 1.9338x、生成1.0774x；i32比i64慢3.38%，已否决。20轮token/hidden/logits精确一致，审计见`runs/cpu-ablation-v2/comparison-audited.json`。benchmark-layout冻结1000条Vex RTL已1000/1000通过。
- CPU native root5 的源码顺序布局实验因最终载入二进制相同而REJECT。新GC/布局候选五次独立fresh Vex RTL均为生成11,389,357周期、P3 880,673周期、I-bus 2,417,024 bytes，逐token/hidden/logits exact；相对standalone生成1.08754x、相对mode3 1.03203x。P3比standalone多40周期，因此只称链接布局/I-cache集成收益，见`runs/cpu-native-ctx-gc-root5-repeat5/result.json`。
- CPU同ELF/ROM/模拟器五对交错：生成11,422,367→10,771,704周期（1.0604×），P3 1,843,453→1,194,876周期（1.5428×），见 `runs/cpu-ablation-retry/comparison.json`。此前不同ELF的1.2317×包含布局/缓存影响，不能称纯P3收益。
- CPU实际1MHz、RV32IM/ILP32 softfloat；含EOS 11 token约0.9630→1.0212 token/s，生成模拟时间11.422367→10.771704s。进程墙钟含boot/诊断输出，不是芯片吞吐；100MHz只是物理目标。
- GPU同应用同vxbin vendor/limb实际RTLSIM均1,713,555条指令、17,077,421周期，speedup=1.000×。墙钟不同不是硬件收益，见 `runs/gpu-rtl-parent-comparison.json`。
- GPU私有诊断PoCL下五对新SimX device CSR计数完全一致：baseline/candidate bracketed-inclusive P3为6,124,279/5,827,334 cycles，isolated speedup 1.0509572645×。这只证明现有单线程candidate算术的isolated SimX周期收益，不是RTLSIM、四线程微核或物理token/s，见`runs/gpu-p3-counter-v1-qualified-repeat5/result.json`。
- GPU局部TT/10ns/u30提取后WNS −1.31→+0.37ns；hold +0.35→+0.34ns；cell面积50,518→53,510µm²（+5.92%）。面积换时序，不是全核Fmax/PPA。有效对照 `physical/gpu-multiplier-routed-outputbound-comparison.json`。
- CPU实际部分积局部理想连线WNS +0.27→+0.47ns，面积6,411.1488→6,449.936µm²，不能外推整核，见 `physical/cpu-merge-shaped/comparison.json`。

## 新整核ROM证据

`runs/cpu-current-rom-core-replay/{receipt,independent-audit}.json`：原ROM/banked ROM均重新构建、实际运行当前CSA根号5固件。11个token、每步hidden/logits/elapsed_cycles与既有CSA实跑一致；生成11,030,645周期，统一重放终点22,527,835周期。此私有driver实际10ns周期，与固件1MHz常量不同，仅作周期/状态等价，不称1MHz实际驱动时间。只改ROM结构，无周期收益，未取得物理资格。独立复核见 `reviews/rom-core-review.md`；索引宽度警告已在生成器修复，须新run确认。

根号5真实回答仍为“我无法获知实时天气。”，token `[67,69,84,97,90,56,71,51,82,8,4]`（含EOS）。词表缺根/号/5，输入含UNK；未改词表修正答案。

## 下一门

1. benchmark-layout scale-context 的1000条冻结Vex RTL及fresh native root5已完成；GC/布局候选下一门为同native ABI的冻结case、P1/P2、十二问和协议回归，不能转移scalar资格。
2. GPU counter五对门已通过；下一步实现4线程column-owned standalone微核，先过P3 330数值记录和isolated RTLSIM cycles，再接完整LLM。禁止以SimX墙钟或现有单线程1.05096×替代四线程/物理收益。
3. CPU CSA真实局部route显示setup退化，停止该路线。prepared-scale算术及流水原型已建立，但复制乘法器和单周期finish均被后端筛选否决；下一版只允许复用现有Vex MUL并分段/多周期finish，以decode/hazard/形式、330 case、root5整轮周期和宏化整核STA/PnR决策。
4. GPU协议wrapper/native脉冲接入和MINI31～33整核门；这是合规门，不当作速度收益。
5. 锁定ORFS归档已实际恢复并校验：507,804,580 bytes，SHA256 `db36562523d92ae66f88117a9b449edcaa5f054ec99769ebe20156ee9a241813`。继续恢复真实宏/整核约束、全角、PDN/天线/LVS/活动功耗；不能从历史abstract反造。

当前GPU四线程已过源码/host门，下一动作改为device编译与最终ELF barrier/atomic lowering，再做严格330和A/B/C/D。CPU三拍finish算术/standalone协议/局部映射成立，但仍必须先接入现有MulPlugin并完成Vex decode/flush/WB/RAW门；不得从局部+3.9407ns推导整核Fmax。

## 清理与审查

持续派发独立技术审查与资深工程视角子智能体。已删除前次失败空构建目录（0文件/0字节，可重建），失败日志仍保留。重复overlay须先完成引用/活动依赖检查及可恢复备份；不删除原始证据。

报告由历史逐次追加整理为现状索引，避免过时pending误导。CPU缺LiteX、GPU缺common.h、非ASCII Icarus路径、物理缺轨道/地网、初轮禁用单元及错误split-reference父链等失败/纠正，仍保留在PLAN和原始日志中。

机器汇总：`current-evidence.json`；CPU完成/缺失列表：`../runs/cpu-prompt-regression-audit.json`。运行进度以最新回执为准，不提前标记PASS。

