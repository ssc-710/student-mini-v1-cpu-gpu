# D027：P3 继续实施的实测结果

所有新文件、运行缓存和日志均在 `optimization/p3/`。模型、词表、LUT与冻结golden未变。当前整体仍为HOLD。

## 新完整问答

问题：根号5等于几？真实回答：我无法获知实时天气。

两平台逐步输出ID均为 `[67,69,84,97,90,56,71,51,82,8,4]`，共11token，含EOS；token、hidden、logits保持一致。

| 测量 | 父/标量 | 新候选 | 口径 |
|---|---:|---:|---|
| CPU生成周期 | 10,260,016 | 10,235,712 | 同counter核+narrow，custom4展开内联，两次新执行 |
| CPU P3周期 | 769,197 | 757,580 | 含调用、寄存器分配与缓存影响 |
| CPU tokens/s | 1.072123 | 1.074669 | 配置1MHz模拟时钟，含EOS |
| CPU生成模拟秒 | 10.260016 | 10.235712 | 尚非物理频率 |
| GPU SimX生成周期 | 14,202,355 | 14,066,408 | global-fenced leader-only，五对新执行各次一致 |
| GPU SimX P3周期 | 2,372,318 | 2,254,057 | 同runtime、同插桩 |
| GPU RTLSIM生成周期 | 14,148,604 | 14,003,538 | 同limb处理器RTL，两臂新执行 |
| GPU RTLSIM P3周期 | 2,392,124 | 2,260,888 | 单次配对 |
| GPU RTLSIM tokens/百万周期 | 0.777462 | 0.785516 | 未指定物理频率 |
| GPU RTLSIM宿主问答秒 | 94.986882 | 93.547509 | 仿真+同步+读回 |
| GPU RTLSIM宿主tokens/s | 0.115805 | 0.117587 | 宿主仿真吞吐 |

CPU新候选两次宿主BEGIN→COMPLETE分别17.824769275、17.677939320秒；整进程18.940655929、18.691412630秒。GPU SimX首对宿主QA9.637211788/9.943232097秒，候选墙钟更慢，不能由设备周期比声称宿主加速。

CPU完整生成周期收益1.002374x，P3 1.015334x；固件42,620→42,684bytes，Ibus806,016→791,328bytes。GPU真实RTLSIM完整生成1.010359x、P3 1.058046x。两者均无整核频率/功耗结论。

## 实现和审查纠正

独立审查在旧GPU leader实现中发现barrier(1)缺global fence，且错误分支可能读未初始化输出。旧05–09 SimX及旧RTLSIM保留观测并HOLD；新实现显式barrier(3)，最终ELF核验全局fence及实参3，五个uniform barrier后以`!stop && out`保护复制。修复版所有结果重新执行，没有复用旧输出。

CPU内联候选保持custom指令编码及算术不变；按实际RTL状态核对，尚需native330/更广回归，不将root5扩展为完整资格。

独立复核：`reviews/fenced-inline-final-20261108.md`，包括RTLSIM、五对SimX、generic输出和CPU两次运行的逐SHA核验。

## 算子资格与后端

新增Q6 INT32候选已fresh RTL root5状态一致，但未改善端到端：P3 757,580→744,771cycles，生成10,235,712→10,254,325cycles、Ibus791,328→817,312bytes。1MHz下1.072718tokens/s，hostQA17.311408615s。该候选暂不晋升；宿主更快不能覆盖设备周期退化。证据 `runs/cpu-generated-counter-inline-q6i32-root5-20261108-01/result.json`。

- CPU当前custom/narrow benchmark1000已逐golden一致；P1/P2/P3=330/340/330。MINI31–33的UART专项30条事件门通过；两者不转移为native ABI或DFI资格。
- 新global-fenced GPU generic wrapper两臂各实际执行330输入：320exact，10MINI30显式unsupported，仍需同wrapper真实fault和协议。MINI31–33仅数值输出不能视为协议资格。
- 新CPU inline固件21bank、10,671words全部重构一致，尾部81word零填充。只属于内容准备门。
- 父固件新ROM bank0 met5在1200秒预算剩9DRC超时，无routed ODB/SPEF/新WNS。第二方案基于global-route RC做负载修复，保持相同die、met5和预算；估计RC阶段19slew/2cap已清零，最终route/OpenRCX待完成。
- 第二方案最终也在1200秒剩9DRC超时，`physical/cpu-counter-candidate-rom-bank0-rc-repair-20261108-01/result.json` 为FAIL。估计RC电气改善未换来布线收敛；无最终提取WNS。下一方案需要保存详细router中间状态并定位pin-access/内部网拓扑，不能继续仅调整电气margin。
- CPU narrow局部物理面积14,400→9,397µm²、WNS+3.72→+5.49ns是已有局部结果，动态die不同；整核PPA仍未完成。

## 证据入口

- `runs/cpu-generated-counter-inline-root5-20261108-01/{result,comparison}.json`
- `runs/cpu-generated-counter-inline-root5-repeat2-20261108-01/result.json`
- `runs/gpu-full-4t-leader-fenced-repeat5-20261108-01/result.json`
- `runs/gpu-full-4t-leader-fenced-rtlsim-20261108-01/{result,audit}.json`
- `runs/gpu-generic-fenced-audit-20261108-01/result.json`
- `physical/cpu-counter-inline-rom-prepared-20261108-01/preparation.audit.json`
- `physical/cpu-counter-candidate-rom-bank0-met5-20261108-01/result.json`

下一步：当前GPU同wrapper真实fault/协议与CPU native330、inline更广回归；继续ROM RC布线及真实SRAM接口适配，之后整核STA/PnR/活动功耗。禁止将局部WNS或宿主墙钟转称物理问答速度。

后续已完成：同generic fenced内核的真实RTL正常+MINI30十seed硬件故障链，以及Q6 int32候选SAT和fresh RTL问答；详细资格及Q6端到端退化见上文，均不扩大为完整330或物理资格。审查 `reviews/senior-inline-q6-sram-20261108.md` 记录实际ELF栈/寄存器问题与真实SRAM时序适配缺口。

十seed03现已实际完成并审计：`runs/gpu-generic-fenced-fault-audit-20261108-01/result.json` 为同内核真实RTL fault10审计PASS，包含正常seed1对照。每次未映射读、匹配tag的错误响应、每launch硬件sticky fault链成立；raw device status保持6，host只有观察完整硬件链后才识别BUS_ERROR。此门未重新运行该fault变体全部330，也未覆盖MINI31–33协议，不与旧320拼成完整330合规。

