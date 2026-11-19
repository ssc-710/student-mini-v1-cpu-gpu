# P3 算法、电路前后端优化与 CPU/GPU LLM 验证计划

整理日期：2026-11-07（Asia/Shanghai）  
状态：实施中，算法已取得目标执行和同ELF消融证据；CPU/GPU新RTL已接入问答，局部后端推进中，全芯片物理签核未完成。

最新执行入口：reports/CURRENT-STATUS.md（D043 暂停检查点）。整体 HOLD_NOT_FINAL_ACCEPTANCE。

## D043 暂停与执行修正

用户要求暂停，全部agent已中断；bank16真实七单元替换后原厂fullGDS DRC0/LVS唯一匹配，最终filled SPEF/512SAT通过；bank17/19局部物理及bank18常量专项通过。详见reports/D043-RESULTS.md的完成项、缺口及续跑顺序。没有新增问答速度收益，G5/G6仍HOLD，下一先独立终态审查和PG绑定，再SRAM/其余bank/整核与统一真实问答。

## D042 执行修正

bank20仅五实例drive4重设计、原始GDS/CDL器件LVS唯一匹配及新整CPU问答已实际PASS；最终填充SPEF+4.10/+2.75ns，功能面积+70um²，未新增速度。SRAM供电/数据channel/rowaddr原生六局部GDS DRC0且拓扑exact，target abstract6→0仍为诊断，不授fullgeometry。bank3 PG9088端子及连续性PASS，两真实300s route失败保留，下一以PG-aware pre-detail实测signal-pin热点修复；禁止无差异重试。当前完整过程见 reports/D042-RESULTS.md。下一必须将runtime overlay绑定真实目标、完成宏fullgeometry/LVS/TT及其余bank/整核CPU/GPU物理，再统一真实问答性能验收。既有算法收益保持，G5/G6仍HOLD。

## D040 执行修正

当前生产P3与算法资格不变。bank10完整512词、常量端点、freshSPEF/driver/SAT独立73项PASS；四bank postroute新整CPU问答exact，generation仍10060264，未新增速度收益。bank14 PG9280端子连续已PASS，但postroute插PG与signal-reset重route均300s失败；采用先PDN再pad2 freshplacement同300umdie亦300s超时，保持所有旧失败，下一按引脚热点精准重布局。bank3定向pad4初次0DRC仍2antenna/489slewFAIL；按测量address3/4加两buf16 root后新route0/antenna0/electrical0，完整512词SAT、提取setup+3.59ns/hold+2.79ns、area17559um2。五bankpostroute整CPU新编译及问答已PASS，11token/state/cycles exact，gen10060264；独立bank3 73项/CPU80项通过。bank20稀疏tap完整GDS文件读回DRC0但LVS仍FAIL，不混淆两门。SRAM第二簇已纠正为row supply landing；目标clockcenter fullDRC/extract失败，局部供电落点+0.085um/单M3轨+0.020um已使abstractDRC10→6且row抽取SPICEexact；仍须generator实现和fullgeometry资格，先修第一簇及验证通道连接。详见CURRENT顶部D040及机器证据。整核PPA/物理tokens/s仍HOLD。

## D036 后端执行更新与下一步

算法资格与两端真实问答已完成，继续G5物理实现，G6仍HOLD。新bank20已通过实际PG端子/连续性、含PG重布线DRC0/antenna0、提取STA+4.11/+2.74ns及有效419词SAT，独立61项PASS。bank5实施同流程。bank14已实测300um die（面积2.16769倍）route0/antenna0，但316slew全部来自address3；自动repair崩溃、全地址分支拥塞、精准18分支超时均保留，改用实际负载定位后的地址树方案推进，不放宽电气约束，不把中途违规当最终结果。 新单A3root buf16方案现已实际通过routeDRC0/antenna0/electrical0/routedSAT，提取setup+3.13ns、hold+2.75ns、TNS0，cellarea17457um2；独立64项终态检查PASS。下一bank10按同明确floorplan实际推进。

新138项独立检查确认真实内存契约：OpenRAM直接连接禁读输出不保持，后续必须实现适配并验证边沿、old-value与hold，不能删除模型X来称等价。80x64目标宏连接修复已真实生成并检查，完整geometry仍712801 DRC；具体修clock金属层和row-address-DFF via landing，先局部验证再目标宏，随后完整DRC/LVS/TT。整核CPU/GPUPG/PDN/GDS/LVS/STA/PPA/活动功耗仍未闭环。

42历史PCH经可恢复归档校验净清理2.91GB，21最终模拟器保持。完整证据和各失败边界见reports/D036-RESULTS.md。模型、词表、LUT、golden和生产候选不变；没有新增问答速度或物理频率收益可声明。

D037–D038已实际新增bank5PG及bank14postroute接回CPU的新问答：token/state/cycles精确，generation10060264/P3585212不变。bank20完整真实GDS在网格精度及标准filler修复后DRC0，但LVS/taps及整核未过。bank10已由实际RC定位address4 slew并新buf16+pad2route，SRAM时钟落点目标宏已真实生成但fullDRC仍失败。详细产物、清理和活动会话见reports/D036-RESULTS.md最新节，不能把中间物理进展当新增问答速度。

## 电路前后端

|局部ROM|cell面积 µm²|setup slack ns|hold slack ns|route DRC|天线违规|
|---|---:|---:|---:|---:|---:|
|新bank5|15572|+4.16|+2.75|0|0|
|新bank20|10167|+4.12|+2.74|0|0|

两bank均从新固件实际重做：RCX、write/read_spef、TNS0、信号driver检查和routedSAT通过。driver计数不等于全线段连续性或PG签核，局部结果不能推出整核WNS/Fmax。其余19bank按实例数排序实际批处理，bank14等在原203.765µm/.40密度下GPL0302容量失败，需明确标注新布局方案或映射面积改进；保留旧失败，不暗改对比预算。

小宏data channel下移四个m3 pitch后395/395器件、409/409网络唯一匹配。四项参考W/L按原始独立Calibre LVS视图显式适配后实际LVS PASS；原Magic参考属性仍FAIL。另两precharge连接M1补片使各leaf DRC3→0，完整宏DRC仍17864，未资格。80×64目标旧完整geometry712801/abstract10亦未通过；六宏18views/TT表征及整核PPA仍缺。


D035新全21bank映射ROM整CPU回放与新干净输入GPU SimX实际PASS。CPU gen10060264/P3585212；GPU gen14055069/P32243858；原模型词表不变。后续G5工程闭环，不重复充分PASS的算法资格。所有新增/缓存仍在工作区，已验证可恢复清理250314879bytes。

## 1. 目标与范围

以现有 NanoChat 的 P3（MoE 专家计算）为优化对象，完成“等价算法优化 → CPU/GPU 实际路径接入 → 全量正确性及协议验证 → 对应电路前后端优化/验证 → 全新问答与性能对比”的闭环。

最终必须在 CPU（VexRiscv RTL）和 GPU（Vortex SimX）上真实重新执行问题：

> 根号5等于几？

记录原始 token 流、token/s 和问答总时长，并提供优化前后的公平对照。优化的是速度，不是回答正确性。

| 平台 | P3 算子验证 | LLM 实际问答 | 硬件性能与物理验证 |
|---|---|---|---|
| CPU | VexRiscv RTL，全 33 case × 10 seed | VexRiscv RTL | RTL 周期；绑定对应实现的 STA/PPA |
| GPU | Vortex SimX；故障和协议由 platform RTL 补充 | Vortex SimX | Vortex RTLSIM 周期；绑定对应实现的全芯片 STA/PPA |

这是 route B（CPU + GPU）。独立专用加速器 route A 不作为默认落地路径。

## 2. 不可变条件

- 不修改原始词表、模型权重、SiLU LUT、输入问题或生成策略；不训练模型、不预填答案或 token。
- golden 只用于目标执行后的比较，不能放入目标输入镜像。
- P3 硬件数值结果要求 bit-exact；语义误差容限不能替代硬件逐位比较。
- 保持原舍入、饱和、浮点运算边界、路由及异常语义；保留 `-ffp-contract=off`、`-fno-fast-math`。
- 先核实并冻结实际 CPU/GPU 配置，不暗中增加核心、硬件线程容量、缓存或指令扩展。
- 优化前后均新执行；不能用历史结果拼接新候选的 PASS。
- 所有阶段区分 PASS、FAIL、HOLD、NOT_RUN；预计收益不当作实测结果。

现有 tokenizer 不包含“根、号、5”，问题会编码为 `[UNK][UNK][UNK]等于几？`，完整输入 ID 为 `[1,2,5,5,5,92,16,27,111,3]`。保留这一限制，不为获得正确数学答案修改词表。验收目标是同一计算更快，且不引入数值或行为变化。

## 3. 已知基线与证据边界

- 根号5 CPU 本轮生成共 13,586,292 模拟周期，其中 P3 为 1,944,817 周期，占 14.31%，调用 40 次。
- P3 加速 2×/4× 时，按当前 CPU 占比估算整体生成分别约加速 1.077×/1.120×；理想零耗时上限约 1.167×。这是预测，不是优化实测。
- GPU 尚无对应分算子计时，不能套用 CPU 占比。
- 旧 CPU 问答墙钟包含大量 UART hidden/logits 输出，不能直接用于归因 P3 加速。
- 既往普通全量执行中 CPU P3 数值/状态等匹配 330/330；GPU SimX 为 320/330，MINI-30 的 10 个 seed 缺少真实 bus-fault 注入能力。
- 既往普通执行未重新施加 MINI-31/32/33 的专项协议刺激，不能视作完整协议资格通过。
- 新 native 仿真与归档物理网表尚未完成绑定，不能直接继承历史 WNS/PPA。

主要本地依据（路径相对工作区）：

- `SPEC.json`、`sources/grading/student-mini/spec.json`、`sources/grading/student-mini/rubric.json`。
- `data/golden/vectors.jsonl`、`data/summary/cases.csv`。
- `sources/software/student_mini_scalar.c`：完整基准算子路径。
- `sources/software/student_mini_native_nano.c`：实际问答路径。
- `sources/software/operator_scalar.c`：精确 primitive 及部分语义参考；其中浮点 `course_w8a8_expert` 不能替代 bit-exact oracle。
- `sources/shared/python/soc_ai_labs/rtl_oracle.py`。
- `sources/integration/vortex/student_mini_native_host.inc`、`sources/scripts/prepare_student_mini_native_gpu.py`。
- `rerun_sqrt3/fresh-baselines/REPORT.md`、`rerun_sqrt5/cpu.log`、`rerun_sqrt5/results.json`。

## 4. P3 完整算法与等价优化

### 4.1 算法契约

对每个合法输入行及其专家：

1. 按目标接口校验描述符、维度、专家 ID、scale、route weight 及地址要求，保持错误优先级与输出行为。
2. gate/up：INT8 乘法、INT32 累加；显式检查合法形状下的累加上界。
3. 按既有 FP32 运算边界组合 input/weight scale，不随意改变括号或引入 FMA。
4. gate/up 转 Q5.11，保持 RNE ties-even、符号及饱和规则。
5. gate 经过原 SiLU LUT，保持索引量化、舍入、clamp 和读延迟语义。
6. `activated_q22 = int64(silu_q11) * up_q11`，保留原宽中间量契约。
7. 按 intermediate scale 精确重量化，先 RNE 再饱和到 INT8。
8. down：INT8 乘法、INT32 累加。
9. 基准路径按原 `(intermediate_scale * down_scale) * route_weight` 边界缩放，BF16-RNE；route=0 保持规范要求的 canonical `+0`。
10. LLM 分别计算 routed/shared expert，再在原位置按原 BF16/残差顺序合并，不跨舍入边界融合。

基准权重采用输出行连续布局，native 使用 `k*16+j` 访问；native 还有独立 shared expert，intermediate scale 固定为 `2^-6`。必须显式适配 layout、stride、scale 与专家选择，不能直接替换函数。

### 4.2 候选及顺序

| 候选 | 内容 | 必须验证的约束 |
|---|---|---|
| A1 | 提前计算尺度、offset、行基址；复用 activation | 不改变 FP32 边界、校验和异常优先级 |
| A2 | 16×16 特化、输出通道分块、适度展开、多独立累加器 | 寄存器压力、代码尺寸、cache、整数不溢出 |
| A3 | 权重预打包或纯布局转换 | 仅置换不改数值；可逆校验；记录准备时间及额外存储 |
| A4 | native 固定 `2^-6` 重量化精确特化 | 从 helper 公式推导等价性；通用 scale 保留正确路径 |
| A5 | GPU 输出通道及独立专家并行 | barrier 一致、无竞态、合并和舍入顺序不变 |

采用“冻结参考实现 + 共享精确 primitive + 基准适配层 + LLM 适配层”。保留独立未优化 oracle，不让候选自证正确。通用 330 条通过不能代替 native 特化验证，反之亦然。

不默认采用近似 SiLU/倒数、降低精度、剪枝、改路由、fast-math 或 FMA。整数归约重排先证明合法形状下无溢出；primitive 特化还需边界、差分及可行的域覆盖证明，不只依赖 330 条。

## 5. CPU、GPU 与电路前后端

### 5.1 CPU 实际热路径

- 优先保持现有 VexRiscv 架构，优化 P3 C 实现、访存和编译结果。
- gate/up 共享输入，多独立累加器，减少索引、分支与重复加载；比较不同输出分块。
- 检查实际 RV32 汇编、指令数、cache 流量和 P3 周期；不假定 packed INT8 自动获得 SIMD。
- 核实实际 `-march/-mabi`、生成 RTL、4 KiB I/D cache 与规范的对应关系，明确此前浮点配置和 RV32IM 标签之间的差异。

### 5.2 GPU 会话内协作

当前 `<<<1,1>>>` 仅一个设备线程计算整个自回归会话。探索固定硬件配置内 4 或 8 个工作线程，但先核查锁定工具链的 launch/workgroup/local-memory 支持。

1. leader 保留原控制流程及非 P3 部分。
2. 所有参与线程一致进入 P3。
3. 按输出通道分配 gate/up，保持必要的累加语义。
4. 写共享 intermediate 后统一 barrier。
5. 并行 down，同步后按原规则完成专家合并和后续计算。

不能简单删除非 0 线程 return，否则会导致整段模型重复计算、竞态或死锁。优先会话内协作，不为每个极小专家单独 launch。专家并行需分离工作区，保持最后合并顺序。保留一致语义的回退路径，不按 case ID、seed 或期望答案挑选路径。

### 5.3 RTL 前端

`sources/shared/rtl/p3_*` 为独立专用加速器路径，仅可参考其精确量化流水、地址预计算、权重缓存等机制，不能直接作为 route B CPU/GPU 成果。

- 由实测周期、访存和 STA 定位真实 CPU/GPU 关键路径，再选择流水切分、扇出处理、存储布局与控制优化。
- 验证 stall、flush、valid 对齐、异常、backpressure、response hold、复位和重发。
- 比较总延迟，不能将流水更深或 Fmax 提高直接等同于会话更快。
- 新增点积指令、MAC 单元、MMIO/协处理器属于独立架构候选，不默认实施；需要单列配置变化、编译器/驱动、缓存一致性、模型接入、SimX/RTLSIM 一致性和物理验证，再决定是否采用。

### 5.4 物理后端

同口径采用 SKY130HD、TT、1.8 V、25°C、10 ns 目标及一致资源条件：

- 综合：单元面积、寄存器/宏数量、组合深度、latch 与未约束路径。
- PnR：利用率、宏布局、供数路径、拥塞、线长、局部缓冲及 setup/hold 修复。
- 签核：setup/hold 裕量、DRC、天线、macro pin coverage、PDN；GPU 使用 top + 4 blocks 拼装后全芯片 STA。
- 以周期和已签核时钟共同评价延迟，不单独以周期或频率宣称收益。
- 功耗绑定新网表、SPEF、SDC 和真实负载活动；报告功耗、能耗、流量与资源副作用。
- 披露 OpenRAM 动态访问能量、主机、外部 DRAM、板级功耗等模型边界。

软件候选也需核对固件是否进入硬化 ROM。若 ROM 字节改变，不能假定网表面积和时序不变。历史报告中的异常通用功耗汇总值不能替代有效活动功耗。任何历史 WNS/PPA 复用均需证明对应实现绑定；否则重新生成或标明缺失。

## 6. 正确性及协议验收

每平台 P3 为 33 case × seeds 1–10 = 330 条；任一 seed 失败，该 case 不通过。

| Case | 覆盖 |
|---|---|
| MINI-01～10 | 最小、均衡、单热点、非活动专家 poison、路由 tie/zero/one/half、行置换、抵消 |
| MINI-11～12 | 非法 expert、hidden，预期 BAD_DESCRIPTOR |
| MINI-13～18 | 全零、INT8 min/max、交替、scale min/max |
| MINI-19～24 | 正负 RNE 奇偶、INT8 饱和；同时验证 primitive witness |
| MINI-25～29 | zero/negative/NaN/+Inf/-Inf scale，预期 NUMERIC_ERROR |
| MINI-30 | 真实 DMA bus fault，预期 BUS_ERROR |
| MINI-31～33 | 背压、响应保持、in-flight reset recovery |

分层报告：

1. 数值与参数：逐条比较 status、BF16 位模式、primitive；检查唯一 ordinal 和完整完成标记。
2. 总线与协议：在对应 CPU/GPU RTL 接口实际施加 fault/stall/hold/reset，保存稳定性、重发和完成证据。
3. LLM：确认实际调用优化 P3，逐 token、hidden、logits 对照未优化版本。

GPU SimX MINI-30 的 unsupported 必须保留原始结果；用同候选 GPU platform RTL 实际注入、读取设备 fault 寄存器验证 BUS_ERROR。不能把 kernel 返回值无条件改成 5。组合资格必须标明每项来自哪个后端，不得声称 SimX 单独 330/330。

专项入口参考：

- `sources/scripts/run_student_mini_cpu_protocol.py`。
- `sources/scripts/run_student_mini_gpu_platform_rtl.py`。
- `sources/scripts/run_student_mini_gpu_protocol_rtl.py`。

接入后完整回归 P1/P2，防共享 primitive、构建和同步改动产生影响；执行原 12 个冻结问题及根号5。缺条、重复、超时、异常退出和缺失证据均不能算 PASS。

## 7. 问答与性能实验

### 7.1 公平 baseline

优化前重新建立 baseline；baseline/candidate 相同输入、模型、词表、工作量、时钟、硬件配置和计时边界。若架构候选不同，明确单列条件，不能假装同配置比较。

- 诊断模式：保存完整 token、hidden、logits。
- 性能模式：保留 token，减少大体积状态输出；优化前后使用相同记录方式。
- 不能把减少 UART 输出归因于 P3 算法收益。
- 采用一致的 profile/计时插桩，报告其开销；插桩和无插桩构建的正确性需核对。
- 优化前后交错执行，计划各至少 5 次，固定冷/暖启动和 JIT/cache 策略，记录每次值、中位数、范围，不挑最快一次。

### 7.2 指标

- P3 调用数、单次与累计周期；模型完整生成周期。
- 首 token 延迟、后续 token 延迟、完整生成耗时。
- 生成阶段 token/s，含 EOS 与不含 EOS 两种口径，明确分母。
- 进程启动至回答完成的总墙钟时长；明确是否包括 boot、初始化、JIT、传输和输出。
- GPU 分离初始化/JIT、H2D、kernel+sync、D2H；仅在实际可测时报告。
- 每步 token、CPU/GPU 可用的真实生成时间计数；日志接收时间不冒充 token 生成时间。
- 输入、模型、词表、LUT、代码、二进制、工具、配置、日志与计时记录的 SHA256。

Vortex SimX 问答和墙钟吞吐满足用户的实际运行要求，但不是物理 GPU 性能。按项目规范，GPU 硬件周期收益另用 RTLSIM 验证。CPU/GPU 分别对照各自 baseline，不以不同后端墙钟绝对值判断硬件快慢。

### 7.3 收益、回退与晋升

- 优化前冻结性能板和权重；错误 case 不用于伪造正常计算吞吐收益。
- 按同 case/seed 周期比及冻结权重计算几何平均，维护直接父链和单项消融。
- 项目评分参考：算子收益 2%/5%/15%，P3 完整会话收益 2%/10%；它们是报告参考，不是收益承诺。
- 列出所有超过 5% 的逐 case 回退并解释，不用均值隐藏。
- 只有正确性、协议、性能、资源和有效物理证据门均满足，才讨论候选晋升。
- 收益不足、噪声无法排除或证据缺失则 HOLD；失败候选保留原因和关键证据。
- 原发布包 `data/candidates.json` 的 NOT_RUN 记录不直接改写，新优化使用独立候选与证据包。

## 8. 工作区治理与清理

所有新文件层级化放在本工作区内：

```text
optimization/p3/
├── PLAN.md
├── reviews/          审查、决策和技术依据
├── src/              候选源码及补丁
├── tests/            验证入口
├── tools/            环境与复现脚本
├── build/            可重建构建物
├── runs/             唯一 run ID 下的原始证据
├── physical/         综合、STA、PnR、功耗
├── reports/          最终报告及机器可读汇总
└── cleanup/          盘点、清理清单及恢复说明
```

只在需要时创建目录和文件，避免空目录、重复报告或“最终_final”式副本。核心文档维持本计划、统一审查/决策记录、最终报告及机器可读结果。

清理顺序：

1. 只读盘点大小、hash、引用、symlink 和活跃依赖。
2. 冻结原发布物 `data/`、`physical/`、`power/`、`MANIFEST.sha256`、`evidence-index.json`、`release.json` 等；它们不是垃圾。
3. 保留成功日志、失败原因、receipt、输入/二进制绑定和复现脚本。
4. 仅清理精确列明、已确认无引用的可重建对象、重复缓存和无用波形；不确定内容先保留或在工作区内隔离。
5. 删除前验证绝对路径和边界；不得递归删除工作区根目录或未分离的用户内容。
6. 清理后检查复现入口，记录移除项、释放空间及恢复方式。

既有 `rerun_sqrt3/`、`rerun_sqrt5/`、venv、工具链和 build 先不批量搬迁。需先迁移硬编码引用及符号链接，并验证新路径可重建。

所有新日志、文档、对象、波形、临时目录、下载缓存和 PoCL/JIT cache 均显式指向工作区。中文祖先路径导致构建问题时，优先使用指向工作区真实目录的 ASCII 别名，并核验实体文件仍在工作区内。不得静默沿用 `D:\sqrt3-rerun` 等外部输出路径。

若确实不可避免在工作区外产生实体产物，必须提前明确原因、精确路径、内容、生命周期及所需权限；系统工具不可避免的临时缓存亦应审计披露。本计划整理操作只生成工作区内的本文件。

## 9. 子智能体与持续审查

用户要求全程派发以下角色；第一轮只读审查已完成：

- `/root/independent_review`：独立技术、合规与证据审查。设计前、验证后和晋升前各审一次，独立重算关键结论。
- `/root/operator_engineering`：采用资深算子工程设计标准，完善算法、数据流、CPU/GPU 映射及前后端权衡；不虚称真实个人年资。

必要时增加专项审查，但不得让实现者自证代替独立审查，也不得让多个重型任务争用资源。

每个候选记录：

> 假设 → 不变量 → 候选修改 → 测量证据 → 审查问题 → 修复 → 复审。

目前依据为本地冻结规范、源码、上游文档与实测证据，尚未完成外网广泛调研。实施前补充相关官方资料和锁定版本依据，记录来源、版本、检索时间及其对候选的影响。若访问受限，如实说明，不编造调研完成状态。

资源遵循项目限制：重型验证约 2 vCPU / 8 GiB，物理任务并发 1。子智能体只读审查可以并行，重型仿真/综合/PnR 分阶段调度。

## 10. 执行阶段与放行门

| 阶段 | 工作 | 放行条件 |
|---|---|---|
| G0 | 盘点、清理边界、路径及规范冻结 | 工具可用，配置/模型/词表/输入绑定，工作区内构建路径成立 |
| G1 | 新 baseline 与分段计时 | 两端实际执行，计时公平，CPU/GPU 瓶颈分别可复核 |
| G2 | 精确算法候选 | primitive、布局适配、边界与差分验证通过 |
| G3 | CPU/GPU 接入和平台验证 | P3 全 330 条资格及故障/协议证据完整；P1/P2 无集成回归 |
| G4 | LLM 实际验证 | 冻结问题及根号5新执行，token/hidden/logits 与原模型一致 |
| G5 | 对应电路前后端 | 时序、物理、功耗及实现绑定有效；缺项明确 HOLD |
| G6 | 重复性能实验与交付 | 收益/回退、消融、原始证据、复现和清理完成 |

候选可迭代回退，数值与接口门失败时不能先宣称性能成功。新架构工作若超出默认配置，需明确决策后启动。任何无法安全推进的权限、依赖或范围问题，报告具体阻塞，不以伪造结果补齐。

## 11. 最终交付

1. 完整 P3 算法、实现差异、候选父链及选型依据。
2. CPU/GPU 各自 33 case × 10 seed 的逐条结果、协议/故障证据、失败及 HOLD 清单。
3. P1/P2 回归和 LLM 原冻结问题的集成验证。
4. 根号5优化前后全新真实运行：回答、token 流、计时定义、token/s、问答总时长及重复实验统计。
5. CPU/GPU 各自算子及完整会话收益、消融、回退和资源代价。
6. 对应实现的 WNS、hold、面积、功耗/能耗、签核条件及明确适用边界；不能用历史 PPA 替代新绑定。
7. 可复现入口、版本及 SHA256 索引、环境/资源记录、清理与恢复说明。

所有结论均可定位原始数据；预计收益、实际测量、仿真墙钟、硬件周期和物理签核分别报告。

## 12. 实施决策记录

### D001：前后端优化是必做项（2026-11-07）

用户明确要求不止算法优化，还要实际重新设计优化 RTL 前端及物理后端。默认路线仍为现有 CPU/GPU；先寻找保持 ISA 和外部功能契约的真实核心 RTL 候选，再以对应 P3/LLM 负载和全平台验证，不能以独立 route A 模块替代。若只有新增架构才能满足收益，显式记录决策并请求必要范围确认，不静默变更配置。

### D002：恢复物理工具，不冒用历史物理环境（2026-11-07）

G0 初查 WSL Ubuntu-24.04 具有 `/usr/bin/yosys`、`/usr/bin/verilator`，但 PATH 中没有 OpenROAD/OpenSTA，且旧 `/home/soclab` 工具树不存在。继续检查工作包可恢复的依赖、锁定源码和官方工具发行包，所有下载/安装树、临时文件、构建输出落入本工作区。无法恢复时必须明确缺项，不把历史 WNS/PPA 当新结果。

### D003：实际 CPU 编译配置与时钟口径（2026-11-07）

工作区内新 baseline 已成功构建并完成实际 RTL 问答，生成 11 token、13,586,292 周期，其中 P3 为 1,944,817 周期。生成的 `variables.mak` 为 `TRIPLE=riscv64-unknown-elf`、`CPUFLAGS=-march=rv32i2p0_m -mabi=ilp32`，浮点由 compiler_rt 软件实现；不得再误称本次 CPU 使用 RV32IMF。LiteX 仿真 sys_clk 为 1 MHz，100 MHz 是物理目标常量，不能把按目标频率换算值冒充本轮仿真时间。ASCII 链接 `/tmp/p3-workspace` 仅为入口，全部构建文件实体位于工作区 `optimization/p3/build/cpu-baseline`。

### D004：CSA 不预设为优胜 RTL（2026-11-07）

CPU 52-bit 三操作数 carry-save 恒等式已通过 Yosys SAT 任意输入证明，但首次通用拓扑综合为原表达式 638 个 generic cell、CSA 743 个；此结果不是 SKY130 或全核 PPA，且未应用真实部分积常量。候选暂不晋升，下一步按真实操作数位形/核心边界综合及 STA 决策。不能因为形式正确就宣称面积或速度改善。

### D005：首轮目标运行通过，但收益须做代码布局消融（2026-11-07）

native 四输出分块及固定尺度重量化候选已分别完成新的 CPU RTL / GPU SimX 根号5诊断运行，11 个 token、hidden、logits 均与对应新 baseline 完全一致。CPU P3 周期 1,944,817→1,177,344，生成周期 13,586,292→11,030,645；GPU aggregate cycles 17,678,406→17,188,623。证据分别为 `runs/native-cpu-comparison.json`、`runs/native-gpu-comparison.json`。

CPU 指令数仅从 7,502,470 降至 7,350,254，但 ibus bytes 从 4,979,168 降至 1,508,960，且 P1/P2 周期也变动，必须增加同代码布局回退、函数对齐及固定尺度/分块单项消融；当前整体1.23×不能全归因于P3计算减少。GPU一次墙钟受到JIT/cache和资源竞争影响，不把本轮墙钟差异作为稳定加速比。通用候选保留原尺度helper，1000条host差分通过仍不能代替目标330条及协议资格。两端尚未完成RTL候选接入和物理签核，所有候选仍HOLD。

### D006：通用候选全量执行及新GPU RTL候选（2026-11-07）

通用分块候选新执行CPU RTL 1000/1000匹配，P3 330/330；GPU SimX新执行1000条、970匹配，P3 320/330，唯一缺口仍为各算子MINI30真实fault注入。MINI31～33专项刺激仍NOT_RUN，故不将普通数值通过写为完整协议资格。

新增GPU同延迟分肢合并乘法器：保留四部分积，第二级35位CSA合并交叉项，第三级34位上肢加法，保持signed33→66及三次enabled edge。201,190笔本地RTL事务/49,912笔stall检查和抽象合并SAT通过；尚未整核/物理验证。寄存器声明减少19位不等于实际PPA收益。

同ELF布局消融采用新增loader尾部的单字节开关，位于原镜像全部分段之后，不改原模型/词表/问题/工作区；两个模式只差该开关，保持相同ROM和模拟器。准备入口 `tools/prepare_ablation.py`，尚未执行消融。WSL会话中断后已恢复仅指向工作区的 `/tmp/p3-workspace` 链接，未完成物理下载已改为 `.part` 并校验大小/包结构后才可完成。

### D007：CPU新RTL已完成一次整核负载；GPU generic拓扑初筛（2026-11-07）

CPU CSA实际私有核心构建及根号5RTL运行完成，与原核心上相同算法候选的11 token/hidden/logits一致，总周期均11,030,645。证据 `runs/cpu-rtl-comparison.json`。尚非全核形式等价或全协议资格，物理时序收益NOT_MEASURED。

GPU旧split/新limb同脚本generic综合分别8,279/8,108 cell、300/283个enable FF，证据 `runs/gpu-limb-synthesis-executed/comparison.json`。这是局部通用拓扑初筛，不是SKY130面积/STA/PPA。私有VX_multiplier overlay已生成并开始新的RTLSIM配置构建，完整执行及parity仍NOT_RUN。

### D008：同ELF五对消融纠正CPU归因；恢复物理工具（2026-11-07）

同一ROM/ELF/模拟器、仅输入尾部开关不同的5对交错RTL运行全部token/hidden/logits一致，周期重复值完全稳定：原P3模式总11,422,367/P3 1,843,453，候选总10,771,704/P3 1,194,876。整体1.0604×、P3 1.5428×。以此作为当前隔离跨二进制布局差异后的主要算法收益，先前1.2317×只保留为不同布局候选的观测，不宣传为纯P3收益。记录 `runs/cpu-ablation-retry/comparison.json`；仍为诊断UART模式，不是最终精简日志性能。

OpenROAD v2.0-17598已在工作区私有解包并补齐共享库，实际 `-version` 成功；不系统安装。SKY130HD TT标准单元库已恢复。GPU局部映射面积旧49,814.0256/新49,504.9792 µm²（约减少0.62%），仅局部cell mapping，尚无placement/route/全芯片WNS和功耗。物理后端设计继续推进，缺失宏视图不能伪造。

### D009：局部时序驱动后端与配置审计（2026-11-07）

真实标准单元LEF、技术LEF和RC已恢复。GPU旧/新乘法器同约束cell-only STA WNS为−4.62/+0.75 ns；加入真实布局、寄生估计及尺寸修复后，40%初始利用率为−5.35/+0.26 ns，30%为−5.29/+0.31 ns。采用30%作为后续CTS/route探索点，但仍保留40%对照，不能将单次密度探索当稳定最优。局部时序改善不证明CPU/GPU全核Fmax改善，也不能当route后WNS或全芯片PPA。下一步必须经过CTS、布线、寄生和约束检查再评估。

新GPU乘法器已完成processor RTLSIM根号5问答，与SimX的11 token/hidden/logits及1,713,555条指令一致；聚合周期17,077,421。审计发现首次stub使用默认4 warps编译、核心为2 warps，不能直接作完整匹配配置证据。强制以1core/2warps/4threads/STD重编stub并另存新run；配置修正后的结果不得追溯覆盖原日志。RTLSIM不是完整AFU/xrt故障和协议资格。

匹配配置重跑已完成，`runs/gpu-rtl-native-matched-config/comparison.json`逐token/state及指令比较通过。后端审查发现初轮映射含config.mk禁用的lpflow单元，因此新增过滤映射并将repair_design也约束为dont_use。真实重跑u40旧/新WNS为−5.84/−0.83ns，u30为−5.64/−0.42ns，候选仍未达10ns；初轮正slack不得用于晋升。后续CTS/route以filtered版本为起点，继续优化关键进位链和物理修复，不以放宽目标掩盖未收敛。

### D010：独立审查纠正物理父链（2026-11-07）

`map_multiplier.py`中名为baseline的模块是既有split-reference，不是此次RTLSIM所用原vendor `VX_multiplier`（完整signed乘法后接3级pipeline）。所有已列split→limb面积/WNS只能称局部候选间比较，不能写作原GPU→新GPU收益。保留目录和历史证据，新增实际vendor源码参数固定后的第三路同约束映射/STA/PnR，并在汇总时明确三路身份。原vendor与候选的整核RTLSIM同应用性能也须单独比较，不能仅凭新RTL与SimX一致推导RTL加速。

第三路已实际完成局部映射和两密度布局：vendor映射面积46,315.6704µm²、198FF；limb为49,535.008µm²、283FF，约增6.95%局部面积，是时序/面积权衡而非双优。vendor u30/u40 placement WNS−2.87/−3.00ns；limb−0.42/−0.83ns。CPU真实32/34/34位部分积合并边界映射也完成：原面积6,411.1488/CSA6,449.936µm²，ideal-wire WNS+0.27/+0.47ns；仅局部0.20ns改善，不足以断言全核频率提升。

局部详细布线流程新增真实OpenRCX提取：split-reference u40路由器0违例、提取STA WNS−3.94ns/hold+0.34ns。候选首轮因zero_地网不可路由失败，新增hilomap工艺常量映射后重做，不以更改网信号类型掩盖缺失tie来源。当前仅优先推进u30候选route，避免在未修根因时重复所有重型分支。

u30候选已完成真实CTS/详细布线及OpenRCX SPEF提取回读，router最终0违例、cell面积53,510µm²、局部TT WNS+0.37ns/hold+0.34ns。此前global-route估计仍为−0.29ns，保留两者，后者不能替代真实提取；均不得外推全芯片。下一门为真实核环境IO边界、对应vendor同密度routed对照、天线/PDN/LVS、整核时序及真实活动功耗。局部达到10ns不是G5全部通过。

### D011：真实协议资格按实现及接口分开（2026-11-07）

当前CPU scalar候选已新建私有RTL顶层，直接复用本轮ROM/内存/原核，只增加UART ready及sys_rst OR tb_reset注入；30条P3 MINI31～33实际执行成功，直接对冻结golden核查且事件门通过（唯一完成、稳定性0、真实stall/hold、reset_cycle−armed_cycle=2000且复位前完成0）。记录runs/cpu-scalar-protocol。该资格不转移给CSA核心、DFI内存接口或物理网表；后者仍须各自真实刺激。

新GPU问答runs/gpu-rtl-native-device-bound已保留实际JIT ELF/vxbin并逐token/state一致，17,077,421周期。它补足该新run设备镜像绑定，不追溯补齐先前run；kernel+sync120.137466s、进程121.346764s为RTL模拟墙钟，不能当芯片吞吐或vendor→候选RTL收益。

### D012：GPU实际父核对照不支持周期加速（2026-11-07）

重新configure并构建真实vendor 1core/2warps/4threads/STD运行库，强制同配置stub后新执行根号5。实际device vxbin SHA与limb完全一致，11token/hidden/logits一致，退休指令1,713,555及周期17,077,421均一致。因此RTL周期speedup=1.000×，不能把不同模拟墙钟115.531/120.137s当芯片收益。记录runs/gpu-rtl-parent-comparison.json。后续必须以同密度vendor/candidate详细布线、提取及整核时钟资格决定是否晋升；若整核关键路径未改善则不晋升硬件候选。

当前CPU实跑固件为11,735 words，已生成23×512-word ROM bank并逐有效地址核验；旧25-bank硬化视图不能直接复用。原12问输入镜像及逐问完整ABI已准备，问题长度影响编译宏，必须逐问重编CPU ROM/GPU应用，不能只更换image.bin沿用根号5二进制。

### D013：真实vendor同密度布线提取对照（2026-11-07）

vendor及limb均完成30%初始利用率、10ns、SKY130HD TT、禁用特殊单元的CTS/详细布线/OpenRCX。vendor WNS−1.31ns/hold+0.35ns/cell面积50,518µm²；limb+0.37ns/+0.34ns/53,510µm²，两路router最终0违例。局部WNS改善1.68ns，实际route cell面积增加5.92%，并非面积时序双优。证据physical/gpu-multiplier-routed-comparison.json。尚无真实整核IO负载/源slew、全角、天线/PDN/LVS/活动功耗，因此不折算整机Fmax/tokens/s。已知同应用整核RTL周期仍1.000×；硬件候选继续HOLD。

12问回归新增逐问CPU image-dir/build-id入口，严格核对输入SHA、冻结模型段和独立ABI，禁止用根号5旧ROM。run_cpu_regression.py对每问分别重编baseline/algorithm、真实执行、绑定ROM/内存/模拟器前后SHA并逐步比较token/hidden/logits；先首问验证流程后扩展。首试系统Python缺LiteX失败已保留，改用工作包原cpu-venv，不安装新环境掩盖错误。

首问“你好呀”已新执行两端baseline/candidate各一轮，CPU RTL与GPU SimX分别逐步token/hidden/logits一致，均输出[23,52,109,4]。证据runs/cpu-native-regression-smoke-envfixed和gpu-native-regression-paired-smoke；仅首问资格，不是12问PASS。后续继续其余11问并保留每问实际编译/device镜像绑定。独立审查推动增加ABI宏/分段边界检查与物理全部outputs哈希门；旧候选extract回执无outputs，因此新执行gpu-multiplier-extract-limb-u30-outputbound，仍WNS+0.37ns，新严格对照见physical/gpu-multiplier-routed-outputbound-comparison.json。

GPU其余11问已新执行完毕，合并首问为12/12逐token/hidden/logits完全一致（runs/gpu-twelve-prompt-comparison.json），保留每问新host/device镜像和时间。此项只放行GPU算法十二问语义回归；CPU其余问、GPU fault及协议/物理门不转移资格。

### D014：真实GPU故障seed1闭环（2026-11-07）

独立fault wrapper runtime实际configure/kernel/runtime完成；首试应用因缺common.h构建失败，保留日志后复制原包实际header重试。runs/gpu-fault-rtl-smoke-headerfixed真正完成普通P3 seed1及MINI30 seed1：真实0xe0000000请求/匹配tag响应/外存未映射读取/硬件sticky fault1/逐launch状态回读/device status6无输出及实际ELF反汇编全部门满足，才分类BUS_ERROR并与golden一致。禁止把status6或case flag直接伪装BUS_ERROR。十seed扩展已启动，必须逐seed新执行。此路径增加skid延迟，性能对照必须双方同wrapper；它不是完整AFU/xrt，也不覆盖MINI31～33或物理网表资格。

十seed扩展已全部新执行PASS（runs/gpu-fault-rtl-ten-seeds），但旧SimX 320/330结果保留，不拼接冒充同RTL/same-wrapper的330case资格。后续仍需该wrapper的数值/协议覆盖、AFU边界及全核物理资格。CPU其余十一问配对RTL已启动。

### D015：当前ROM同环境整核重放及现状文档整理

当前11,735-word固件23-bank ROM完成35,205次定义地址读检查后，重新构建原ROM/banked ROM两份相同CSA整核、驱动及输入并实际完成根号5。两路11个token/hidden/logits/elapsed_cycles与既有CSA父运行一致；生成均11,030,645周期，replay终点22,527,835周期。证据runs/cpu-current-rom-core-replay/{receipt,independent-audit}.json。不是未定义地址形式证明或物理资格，无周期加速；继续映射与真实时序验证。

CPU十二问已独立审计4/12，余项仍执行。PROGRESS.md整理为当前状态和有效证据索引，消除过时pending；历史细节保留在本决策记录及各run日志。清理须精确目标、引用/活动依赖检查和可恢复备份，不删证据。

独立审查reviews/rom-core-review.md指出私有replay驱动10000个1ps tick即10ns周期，不等于固件1MHz常量。该run只作状态/周期等价，不用其周期换算1MHz实际驱动时长；其他原运行需按各自driver核对。bank_data索引6bit对23bank产生宽度警告，已修生成器为5bit并准备另起验证，历史产物不覆盖。

### D016：速度主线回归算子周期与整核关键路径

CPU十二问已新配对RTL 12/12逐token/hidden/logits一致；锁定ORFS归档507,804,580 bytes、SHA256 db36562523d92ae66f88117a9b449edcaa5f054ec99769ebe20156ee9a241813完成结构校验和工作区解包。两项分别是语义门与后端依赖，不记作速度收益。

独立速度审查reviews/p3-speed-continuous-review.md确认CPU同ELF P3 1.5428x仍为最强证据。下一算法候选限定为固定Q6私有i32重定标及block-2/block-4四组同ELF消融，以RV32实际spill和P3 cycles决定；不扩大到通用scale接口。GPU limb同应用RTL周期1.000x，冻结额外局部PnR，先增加P3 isolated cycle counter和4线程协作微型kernel。电路后端改为baseline/CSA完整VexRiscv逻辑关键路径归属；未命中整核critical path就不宣称问答加速。

### D015：续行独立审计与协议实施顺序

CPU回归保持原WSL活跃进程，不因工具会话句柄丢失而重复启动。新增 `tests/summarize_cpu_prompt_regression.py` 独立读取已完成回执或进度，逐项核查构建/输入SHA、原始日志SHA、重新解析的逐step token/hidden/logits、唯一完成、EOS/维度及周期/吞吐公式；缺问明确HOLD。当前已审计index0/1/2共3问，动态快照为 `runs/cpu-prompt-regression-audit.json`。不同ELF逐问计时不替代同ELF归因。

GPU协议按新私有overlay/runtime逐层推进，先MINI31真实双向内存背压及稳定性检查，再MINI32命令响应hold、MINI33执行中reset/reissue；不得改写已绑定fault运行库。独立审查关注握手双方一致、tag关联、SCOPE层级及背压概率256截断风险。没有实际执行证据的阶段仍NOT_RUN。

全部新实体仍在本工作区内；唯一工作区外例外 `/tmp/p3-workspace` 是兼容工具ASCII路径的软链接，不写实体文档。清理只接受明确目标、无引用/无活跃依赖门、父代理复核与工作区内可恢复备份，不以删除原始失败证据来整理目录。

### D017：scale-context 以目标周期胜出；i32 与完整 Vex bit-blast STA 否决（2026-11-07）

同一 ELF/ROM/Vsim、仅输入尾部 selector 不同的四模式各五次交错 VexRiscv RTL 已完成。原 runner 把应随速度变化的 `elapsed_cycles` 误纳入语义字符串比较，导致20轮结束后的汇总断言失败；失败记录保留。新独立审计只排除时间测量字段，token/hidden/logits 20/20 精确一致，并绑定每份原始日志。scalar、block4-i64、block4-i32、scale-context 的 P3 周期分别为1,895,648、1,351,410、1,397,090、980,264；生成周期分别为12,664,245、12,119,748、12,164,349、11,754,128。scale-context 相对scalar为P3 1.9338x、生成1.0774x，相对现有block4-i64为P3 1.3786x、生成1.0311x。i32虽静态指令更少，目标P3周期反而慢3.38%，正式否决晋升；scale-context仅进入冻结33x10资格候选，未过该门前不替换当前实现。

完整 Vex baseline/CSA 逻辑映射两路均实际完成，但将cache/register memory展开为73,805个触发器，最差控制网扇出8,194，产生−1075.67/−1075.85ns伪WNS。原脚本还因OpenROAD只把面积打印到日志、未生成`area.rpt`而最终失败。新回执将其明确标为 `FAILED_DIAGNOSTIC_MEMORY_BITBLAST_NOT_PHYSICAL_STA`；不得用于Fmax、PPA、P3路径归属或tokens/s。脚本已修正后续面积解析，但不重复执行同一无效流程。CPU CSA前后端只继续真实乘法合并锥的同约束布局/CTS/布线/提取；仍不得外推整核。GPU主线保持isolated P3 device cycle counter与四线程微核优先，vendor/limb整核运行周期1.000x及宏视图缺失边界不变。

### D018：scale-context 冻结 RTL 通过；GC/布局成为当前 CPU 集成胜者，GPU counter 保留两次真实失败（2026-11-07）

benchmark-layout `scalar-ctx` 已完成新的 VexRiscv RTL 冻结 1000 条执行并逐条核对 golden：P1 33 case×10 seed=330/330、P2 34×10=340/340、P3 33×10=330/330，且每 case 的 seed 恰为1..10。该门只资格化 benchmark ABI/layout，不自动资格化 native root5、MINI31～33或物理网表。随后 fresh native scale-context root5 真实运行通过，token/hidden/logits exact，回答仍为“我无法获知实时天气。”，生成12,386,416周期、P3 880,633周期、I-bus 3,994,592 bytes。它证明 native 接入语义正确，但相对同ELF mode3生成回退632,288周期，暴露代码布局/I-cache问题。

仅移动 C 定义的 `native-ctx-layout` 最终载入的 `bios.bin`、ROM及关键符号地址均与 standalone 相同，真实 RTL 计数也完全相同，因此按 REJECT 收口，不做无意义的相同二进制五重复。后续 `native-ctx-gc` 对私有 BIOS 启用 `-ffunction-sections -fdata-sections` 并沿用 `--gc-sections`，静态门确认未用的 `mini_native_scalar_expert` 被丢弃，`bios.bin` 47,516→43,220 bytes，ctx/generate 热代码间距缩小。fresh root5及五次独立 Vsim均逐token/hidden/logits exact，硬件计数稳定为生成11,389,357周期、P3 880,673周期、I-bus 2,417,024 bytes、7,156,976 instructions。相对 standalone 生成1.08754x，且相对mode3仍为1.03203x；P3本体反而多40周期，故收益严格归类为 P3 接入/链接布局/I-cache 优化，不是P3算术、RTL、Fmax、WNS或PPA收益。该候选尚需同native ABI的P1/P2、冻结case/十二问及协议回归，完整晋升继续HOLD。

CPU局部CSA真实SKY130HD TT/10ns/u30 placement/CTS/detail-route/OpenRCX最终对照为 baseline WNS +0.13ns、CSA +0.11ns，面积7,163→7,117um2，两路router 0 violations。CSA虽面积约减0.642%，setup退化0.02ns，不支持速度目标，保持HOLD并停止该局部路线；不能外推整核。下一CPU RTL前端候选必须独立命名，优先根据RV32 trace选择exact packed INT8 dot-product或prepared-scale指令，并通过形式/330 case/root5周期及宏化整核后端门。

GPU isolated counter v1 的44-byte ABI、显式hi/lo、version/最后commit、单leader、routed/shared独立计数及host同步后读取已通过源码静态门，baseline/candidate保持同构插桩和1core/2warp/4thread/STD配置。首次真实SimX在PoCL JIT报 `Cannot find symbol p3_vx_cycle_begin/end in kernel library`，0 instruction/0 cycle；第二次 `OpReadClockKHR` 路线因工具链禁用 `SPV_KHR_shader_clock` 被拒绝。两次失败均保留，不包装为成功。只有计时入口被锁定工具链正确lower并取得20/20/0、sum40、非零周期、父token/state一致及实际device ELF/vxbin/runtime/config绑定后，才允许启动四线程P3微核；SimX墙钟继续不得替代硬件周期。

### D019：prepared-scale RTL算术成立，复制大组合单元与单周期finish拓扑否决（2026-11-07）

P3数据布局审计表明，相邻四个权重属于四个输出列，不能直接用传统dotp4归约而不引入转置/收集开销；CPU专属RTL优先选择精确prepared-scale操作。新增独立`int32 × uint24`、shift[-28,4]、ties-to-even、int16饱和规范及两周期流水原型。后乘法finish对任意56-bit product/sign在合法shift域的Yosys SAT通过；随机valid空洞、复位和连续输入流水仿真1006笔通过。完整单元整块SAT因双乘法位爆炸300秒超时，原失败保留，不能写作完整形式证明。

真实SKY130HD筛选否决两种直接拓扑：复制独立乘法器/可变移位单元在ABC前已有7,405 gates、143 inputs/80 outputs且300秒映射超时；只复用现有Vex MUL但把完整finish塞入单周期writeback时，局部映射为1,351 cells/7,141.8496um2，理想线网10ns最大路径13.3633ns、slack -3.3633ns。后者仍非placement/route或整核WNS，但已足以拒绝单周期写回接法。下一RTL前端必须复用Vex现有四部分积MUL路径，并把可变移位/舍入/饱和分段或作为受控多周期操作；需重新验证decode、源寄存器hazard/bypass、stall/flush、非法指令、330条P3、root5整轮周期及宏化整核PnR。上述局部结果不折算Fmax、token/s或PPA。

### D020：GPU isolated counter 五对稳定门通过，放行四线程微核（2026-11-07）

`tests/summarize_gpu_isolated_counter_repeat5.py` 对五对新Vortex SimX运行逐对重新核验全部回执SHA、20 routed/20 shared/0 failed/sum40、非零周期、empty=234、11步token/hidden/logits与各自父运行逐行一致、最终device ELF反汇编中恰好六组sync+mcycleh/mcycle/mcycleh lowering。五对baseline均为routed 3,062,574、shared 3,061,705、isolated 6,124,279、full SimX 17,735,751 cycles；candidate均为2,907,471、2,919,863、5,827,334、17,448,755 cycles。isolated speedup稳定为1.0509572645055183x，cycle reduction 4.8486523883%。机器证据为`runs/gpu-p3-counter-v1-qualified-repeat5/result.json`。

该结果仅表示私有诊断PoCL下、device mcycle CSR的bracketed-inclusive P3 SimX周期收益；不是Vortex RTLSIM收益、物理GPU token/s、四线程协作收益、Fmax或PPA。五对门满足后，GPU下一实现限定为standalone四线程column-owned微核：thread t只负责列4t..4t+3，每个dot保持k=0..15原顺序，全部线程经过一致barrier序列，以显式command/stop/error状态收口。先完成330条P3数值记录及isolated RTLSIM周期，再接入完整LLM；没有这两门不得把微核收益写入端到端结论。CPU并行主线不变：只允许复用Vex现有MUL并采用分段/多周期finish，已否决拓扑不得回流。

### D021：GPU四线程源码/host门与CPU三拍finish筛选成立，目标接入仍HOLD（2026-11-07）

GPU新增同一模板骨架的四线程column-owned微核，`<<<1,4>>>`下thread t负责连续四列，gate/up/down均保持k=0..15顺序，五个顶层uniform barrier，无线程early return，shared error/stop统一收口。native固定Q6 host差分对512组随机模型的expert0/1/shared共1,536次调用，scalar/candidate逐BF16 bit exact；另核实冻结P3清单严格为33 case×seed1..10=330。该门仅为源码/host reference，未证明device编译、barrier/atomic lowering、330 target执行、SimX或RTLSIM；下一步必须完成最终device ELF/vxbin反汇编门，再做A/B/C/D 2×2归因和330 target执行。

CPU新增无乘法器的三拍post-multiply finish：F0 shift/guard/sticky、F1 ties-even round、F2 sign/saturate。当前源码SHA绑定的reduced组合算术在shift[-28,4]对原finish SAT等价；fixed-latency随机流水1,016笔PASS。fixed pipe局部SKY130HD ideal-wire筛选为1,853 cells、11,719.9904um2，10ns最差setup +3.9407ns、hold +0.106ns；它含寄存器且为zero-I/O/ideal-clock/unplaced结果，不与旧7,141.8496um2组合finish直接作PPA对比，也不外推Vex/整核。首次STA因不支持`remove_from_collection`失败及一次setup/hold混合字段的retry均保留；fixed机器结果为`physical/cpu-p3-scale-finish-staged-mapped-retry3/result.json`，当前源码SAT为`runs/cpu-p3-scale-finish-staged-formal-retry/result.json`。

独立审查指出pulse-only fixed pipe不能处理Vex stall/flush/tag。随后新增global-stall elastic tail，携带rd tag，output backpressure时冻结全尾部，flush/reset取消所有in-flight并组合屏蔽output_valid；修复了最初flush与ready同周期可能被外部误判提交的问题。最新定向flush+ready、flush+stall、in-flight reset、合规producer hold、80周期满流水stall/resume，加随机背压/tag共accepted 1,813、retired 1,791、flushed 22且守恒PASS。elastic自身局部ideal-wire筛选为1,905 cells、12,042.8um2，setup +4.3962ns、hold +0.1043ns；仍非PnR/整核。此资格只属于standalone finish tail，未实际复用/接入MulPlugin，未覆盖decode exclusivity、普通MUL共存、RAW/bypass/异常、330、root5或整核后端。下一CPU门是先做阻塞式Vex正确性接入，再评估带age/kill/WB仲裁的II=1版本；禁止直接把当前局部结果称为问答提速。

### D022：CPU阻塞复用接口oracle通过；GPU device ABI修复后暴露local lowering阻塞（2026-11-07）

CPU新增独立`cpu_p3_vex_blocking_adapter`，精确匹配custom-0/funct3/funct7，运行时检查context保留位与shift范围，通过外部MulPlugin请求边界获取乘积，再进入当前三拍elastic finish。为验证解耦边界上的错误归属，standalone oracle携带owner与8-bit transaction tag，覆盖匹配tag但owner=false、连续两次flush后最老响应晚到、随机乘法延迟、WB背压和无幽灵提交。首次WSL启动两次`E_ACCESSDENIED`、首次动态运行300秒死锁、随后两次watchdog失败均保留；定位到TB在posedge驱动`wb_ready`造成finish与adapter采样竞态，改为所有flush/WB控制negedge驱动后fresh运行通过。最终固定seed `0x50335eed`并绑定runner、命令、Icarus 12.0及Yosys 0.33后再运行：304 accepted = 284 retired + 20 flushed，3344 cycles。Yosys结构门确认DUT无`$mul`，回执为`runs/cpu-p3-vex-blocking-adapter-screen/result.json`。

该PASS只资格化standalone阻塞控制oracle，不是单体Vex接入。资深审查决定真实MulPlugin为固定stageable流水，不照搬8-bit解耦tag：下一版使用`IS_P3 + stage valid/isRemoved + owner-scoped launched`，custom-only增加一拍abs/context预处理后复用现有四部分积，普通MUL不增加预处理停顿；仅从原单RF writeback提交注册F2结果。必须继续证明runtime illegal精确trap、RAW/WAW/WAR/rd0、ordinary MUL混流、reset/exception/redirect无ghost、生成RTL单乘法器、330、fresh root5完整周期与宏化整核后端。standalone tag比较器不作为生产微架构，也不形成速度/PPA结论。

GPU已将`_Z3absl`改为手写LLVM IR，并在standalone及最终派生`kernel-riscv32.bc`验证唯一精确`i64(i64)`定义；派生SHA256为`0c1aa79cce997530539f433404d5a82e43358d09e06af54aa6a4c4734915198a`，PoCL debug日志确认实际加载该私有路径，旧i32/i64 verifier错误消失。随后pair-11/12在PoCL `processKernels` 暴露LLVM20 opaque-pointer对automatic-local/shared数组GEP丢失addrspace(3)的新阻塞，仍为0 instruction/0 cycle。当前修复限定为shared对象标量化，保持4线程、五个uniform barrier及算法顺序不变，并实测`<<<1,1>>>`/`<<<1,5>>>`非法launch。当前烟测臂只称`4T-S`/`4T-C`；速度归因必须另补同基础Vortex上的`1T-S/1T-C/4T-S/4T-C`，硬件baseline/candidate是独立正交轴。

### D023：GPU四线程最终device smoke通过，尚非速度/330资格（2026-11-07）

修复automatic-local地址空间问题时，将16个shared intermediate与4个lane error标量化；每线程仍仅计算列4t..4t+3、gate/up/down的k顺序不变。锁定chipStar/Vortex lowering对`tid==0` leader分支存在异常，入口probe证明全线程全局写有效且tid实为0..3，但leader分支无lane命中；最终改为所有4个SIMT lane执行值相同的幂等shared初始化、错误OR发布及status/completed发布，消除leader分支和分发散，不改变列计算。所有诊断probe已从最终源码移除。host differential重新通过1,536调用。

最终新执行`runs/gpu-p3-4thread-device-pair-22-final-evidence`中4T-S/4T-C均exit0：正常路径status0/completed1，16个BF16输出逐位相同；descriptor=2、numeric=4；`<<<1,1>>>`与`<<<1,5>>>`均由host实际读回launch error=1/completed0。两臂分别捕获唯一device ELF/vxbin及反汇编。P3 kernel反汇编含5个静态barrier helper调用点（4个jal和函数尾部1个tail j），都指向同一`_Z7barrierj`；helper只生成一份，故不能要求ELF有5份custom0。编码扫描仅证明ELF内存在custom0/funct3=4，计数4T-S为2、4T-C为4，不把所有匹配字都冒称barrier。

pair22的device输出仅直接证明4T-S/4T-C互相bit-exact；数值oracle来自独立host门逐BF16绑定`mini_native_scalar_expert`，不是同一device进程内oracle。pair22总计包含正常、descriptor、numeric、under-launch、over-launch五次P3发射，SimX总计4T-S 8,569 instructions/98,591 cycles、4T-C 8,624/99,305；这些是诊断smoke聚合值，不是单次P3性能A/B，且当前候选更慢，禁止作为加速结论。pair21与pair22设备源码相同；pair21仅因审计脚本漏计尾部tail `j barrier`而报4个调用点，pair22修正为jal/j后得到5。下一步必须完成真正`1T-S/1T-C/4T-S/4T-C`同负载矩阵、330条target执行及isolated周期，再决定算法晋升；随后才可进入对应Vortex RTL前后端和整LLM问答速度归因。
### D024：恢复执行与GPU分歧编译根因修复（2026-11-08）

实际工作区已迁移至 `D:/college/codex/student-mini-v1-cpu-gpu`，旧 `D:/大学/...` 不存在。历史回执保持原样；新实验显式使用迁移后的路径、独立目录、工作区内HOME/TMPDIR/cache。环境审计 `runs/resume-20261108-environment/result.json` 确认依赖及输入存在。

独立复核发现D023所有lane同时发布shared/global状态存在数据竞争，即便值相同也不能作为正式实现。pair22保留为历史smoke观测，撤回候选晋升依据。四个新的单写者语法/CSR probe均失败，不能继续用同值并发写绕过。检查LLVM发现 `-vortex-divergence-max-bbs` 会在函数基本块过多时跳过SIMT分歧流水。新eq-zero单写者源码配显式阈值10000在 `runs/gpu-single-writer-bb10000-20261108-05` fresh SimX PASS；同runner默认阈值对照06 FAIL；候选臂07 PASS。P3最终ELF恢复vx_split/vx_join，正常16 BF16逐位符合独立expected，descriptor/numeric及非法1x1/1x5通过。三次结果均保存实际ELF/vxbin、IR、runner snapshot、私有PoCL与输入SHA。

正式header已恢复三个 `tid==0` 单写者发布块；后续编译必须显式绑定有效divergence阈值并检查最终ELF，不能只查源代码。尚需精确核对默认阈值/基本块数、runtime全局初始化、通用330 wrapper、四臂同负载归因和RTLSIM。新烟测聚合PERF不计作速度收益。CPU并行推进私有Scala MulPlugin源码overlay，保留现有四部分积和owner-scoped提交；整核后端仍须恢复匹配23 ROM bank的真实宏视图，禁止重复无效memory bitblast STA。

### D025：真实MulPlugin生成与ISA通过，通用GPU数值门推进

私有CPU原配置Scala编译通过，JNA/affinity宿主兼容恢复后，baseline02/candidate03均实际生成Spinal1.7.0a整核Verilog。新P3沿用原四个部分积，增加custom准备和三拍elastic finish。独立审查修复异常valid依赖removeIt造成组合环；首次编译暴露UInt不支持一元负号，改为定宽0减。candidate连同finish Verilator lint rc0，4项位宽warning原样保留。真实Wishbone整核ISA运行九组P3/普通MUL/RAW/rd0、40项mailbox、三次非法context精确mcause/mepc/mtval与mret恢复全部通过，741 cycles。回执 `runs/cpu-generated-p3-isa-20261108-01/result.json`，绑定审计 `runs/cpu-generated-core-audit-20261108/result.json`。原工作包RTL由Spinal1.9.4生成，因此不能继承其330或LLM资格；下一步新生成核配对root5集成、in-flight reset与全case。

通用GPU wrapper直接读取1936字节冻结ABI，两臂host320exact/10unsupported后，目标11/12分别真实暴露缺abs(int)/abs(short)，均0instruction/0cycle。新私有bitcode补精确i32/i16/i64 ABI后13/14实际各执行330输入，320状态/BF16/primitive exact，10MINI30 unsupported，MINI31～33仍只有数值门。继而发现PoCL setup全lane同址写全局workitem状态，改为14处从不可变KMU参数读取并删除setup发布。新私有库15/16两臂再次fresh执行相同输入；独立机器审计17确认各320exact、P3 split50、setup零store、IR无旧work全局引用。仍禁止声称330合规、RTL协议或问答提速。后续必须为同数值内核增加真实fault/协议、isolated device周期和RTLSIM，再接完整LLM。

后端参数化ROM生成器从实际BIOS/init/RTL动态产生23bank，11735定义地址重构一致，映射后一个时钟SAT等价通过。当前bank0映射1716cells/10516.336um2；同207.23um动态die详细布线在1200秒剩3DRC超时，失败证据保留，没有routed ODB/SPEF或最终WNS。下一修复针对address高扇出与拥塞，保持面积/约束可比，不以延长timeout替代优化，不将更大300um die误称同面积收益。

### D026：P3窄位宽电路优化与新问答计时修复

本阶段新完整问答实测已完成：CPU新counter核三臂11步state exact，baseline/candidate/narrow生成12088215/10260016/10260016 cycles，P3 888628/769197/769197，整轮1.178187x（混合算术/布局/cache，不纯算术归因）。GPU完整4T诊断06 11步state exact，S/C生成14563928/14436680 cycles（1.008814x），P3 2351672/2231192（1.053998x）。实际答案均保持“我无法获知实时天气。”，未改词表或纠正模型答案。具体token流和分域计时见最新CONTINUATION及机器回执。

改进计划：GPU微核约1.113x收益进入完整诊断后P3约1.054x、整轮仅1.009x，不据微核比值外推。当前诊断的非P3四lane私有重复需改为leader计算/共享控制、所有lane uniform P3协作；保持同runtime和插桩重跑。CPU窄化保持同频周期，后续仅通过真实整核后端验证是否能提高时钟或降低面积/功耗。两端新330合规、RTLSIM及整核PPA尚未完成。

新增独立 `cpu_p3_scale_finish_narrow.sv`，保留乘法器复用、shift/guard/sticky与三拍elastic协议，将shift后的60位无符号幅值截为饱和值65536，再使用17位寄存器和舍入加法。任意合法56位乘积及shift[-28,4]的幅值不超过2^60-16，截断值高于正负饱和阈值且保留未溢出数的奇偶位。`runs/cpu-finish-narrow-20261108-01/result.json` 的任意幅值/guard/sticky/sign SAT及原1813笔elastic协议PASS。保留生产版本不变，避免污染正在执行的问答。

新配对映射同库/10ns/原约束：wide 1905 cells/12042.8um2、setup +4.3962ns；narrow 1220/7921.3472、+4.6241ns。只属ideal-wire局部screen；下一步同流程详细route/OpenRCX、真实generated核ISA/reset，之后新配对root5，禁止将局部面积/时序改善折算问答收益。局部route采用10ns、1ns输入/输出、0.03pF、30%利用率、met1–4；因映射面积变化产生不同动态floorplan，须明确区分同流程与同die。

新生成baseline/candidate完整root5首轮各实际输出11步且token/hidden/logits与冻结reference一致，但GenCoreDefault small CSR未映射MCYCLE/MINSTRET，两臂周期均0，明确 `TOKEN_STATE_EXACT_PASS_TIMING_HOLD`；保留失败计时证据，不用21秒左右仿真墙钟作硬件吞吐。下一步成对启用真实计数器并重建，补BEGIN→COMPLETE宿主单调时间及实际custom执行证据。

原23bank ROM的同面积修复启动新轮 `cpu-current-rom-bank0-fanout-20261108-01`：输入buffer、max_fanout32、slew/cap修复，保留原30%初始化和IO约束；未完成前不宣称成功。GPU四臂仍需实际实现/运行，既有清单不计完成。

D026后续实测：narrow配对详细route/OpenRCX均0DRC，局部WNS+3.72→+5.49ns、单元面积14400→9397um2，逐hash审计PASS；动态die不同，不是同die实验。窄化配新counter核的真实ISA/reset已PASS，七拍有界逐拍等价PASS。ROM输入buffer/fanout方案1200秒剩9DRC超时，否决晋升，下一方案须解决具体拓扑拥塞而非照搬fanout阈值。

GPU四臂已真正完成20次交错SimX并审计：1T-S136779、1T-C122691、4T-S45002、4T-C40420 cycles，五次各臂完全一致且输出BF16 exact。1T入口为serial phase emulator，4T含协作barrier，线程归因包含入口结构差别；empty独立记录不扣除。只放行完整LLM集成诊断，不替代330/RTLSIM/问答验收。后续4T-S/C同runtime完整root5并记录逐token状态/周期/总时长；GPU硬件乘法器前后端仍为独立对照轴。

CPU计时修复后新三臂完整问答已完成：baseline12088215周期、custom10260016周期，narrow同10260016；11步token/hidden/logits exact，回答“我无法获知实时天气。”，原模型/词表未变。1MHz配置下0.909977→1.072123tokens/s（含EOS），生成时长12.088215→10.260016秒。BEGIN→COMPLETE宿主18.830884/18.553527/17.459449秒，包含仿真/UART输出。审计 `cpu-generated-counter-root5-audit-20261108-01`绑定全部实际状态与输入，组合集成收益1.178187x、P3 bracket1.155267x；I-cache/布局/core变化有影响，不能把全部差异归于算术。narrow只换外接RTL、相同固件，已证明保持周期并改善局部后端，仍待整核物理与新330。

### D027：同步合同修复、真实RTLSIM与调用开销优化

新Q6 INT32候选已有合法INT16乘积超集组合SAT及fresh RTL root5：P3 757580→744771，但完整生成10235712→10254325退化，Ibus791328→817312bytes，11state exact。故暂不晋升；继续围绕布局/cache与同布局消融改进，局部更快不能替代完整问答验收。

CPU当前新核/narrow已完成benchmark1000及UART MINI31–33专项30，native ABI资格不继承。GPU leader-only消除非P3四lane重复，05–09真实五对输出/周期重复，但独立ELF审查发现barrier(1)不提供global fence；共享控制和LUT指针位于global memory，故该链只保留观测，不能晋升。fenced02改显式device barrier(3)，最终ELF检查实参3及fence；五barrier后仅在!stop且out有效时复制结果。01尝试不支持的threadfence builtin失败保留。修复版SimX生成14202355→14066408、P3 2372318→2254057 cycles，真实11state exact，仍需修复版五对和RTLSIM，不继承旧重复性。

05已有真实RTLSIM S/C生成14053094/13905537、P3 2321949/2192203，11state exact；审计明确同步HOLD。新fenced02 RTLSIM已独立启动，严禁复用05结果。所有GPU周期速率用tokens/million cycles，未取得整核物理频率；宿主仿真墙钟单独记录。

CPU下一算法/软件速度候选为消除p3_scale_apply4每expert八次函数调用和四lane循环：独立build_cpu_custom_inline.py使用显式4条custom指令与always_inline，同counter核/narrow、模型/LUT/舍入不变。必须fresh RTL比较完整root5状态、P3周期、I-cache流量与代码大小，若寄存器压力/代码膨胀导致退化则否决；收益包含布局/cache影响，不能归于RTL频率。新candidate ROM bank0同时按实际固件映射进行met5 route/OpenRCX；旧ROM电气违规不豁免，新固件大小变化须重新内容/物理绑定。

D027实测补充：fenced GPU五对SimX完整问答周期完全重复，真实fenced RTLSIM两臂生成14148604→14003538、P32392124→2260888，11state exact；新generic全局fence wrapper两臂仍320exact/10fault unsupported。CPU inline两次fresh RTL均10235712生成/757580P3，parent10260016/769197，固件+64bytes、Ibus下降14688bytes；只放行继续资格验证。当前parent固件ROM bank0 met5预算1200s剩9DRC失败，无新WNS。下一物理方案针对拓扑/拥塞，必须留失败证据，禁止通过沿用旧固件bank或延长预算宣称收敛。


### 2026-11-13 本轮计划细化：直接速度候选与清理

- 将 GPU 固定 native Q6 的 INT16×INT16 乘积及 RNE helper 收窄到 INT32，保持 generic scale、4T算法、barrier(3)、模型/词表/LUT不变。先绑定实际header做数值独立门，fresh C64/C32 full SimX两对，再实际processor RTLSIM。仅按完整generation周期晋升；小幅SimX收益不能替代RTL或物理频率证明。实现入口 tools/run_gpu_fenced_q6_i32.py；证据 runs/gpu-fenced-q6i32-20261113-01/02。
- 当前两对SimX周期重复：generation14066408→14055069、P32254057→2243858；算术门/RTLSIM完成前不晋升生产。CPU同名Q6i32曾因端到端退化被拒，GPU必须独立评估。
- 已清理46个历史CPU.gch，经引用/进程/逐SHA可恢复归档检查，净释放3193240334bytes；最终Vsim、ELF/bin、RTL、golden、模型及原始日志保留。清理作为支持工作，不替代P3速度实验。

### D028：CPU双列显式累加与64字节布局联合优化（2026-11-13）

新block2将gate/up四组标量累加、down双列标量累加，保留每列k顺序、custom scale、Q6 INT64与BF16语义。未对齐fresh RTL P3757580→592452，但完整generation10235712→10325668退化，不晋升。align256超过复用RTL ROM深度10671words而启动失败，保留失败。align64固件42612bytes/10653words，真实ROM内容及容量校验通过，两次fresh RTL generation10127934/P3614629，11token/hidden/logits一致；完整约1.010641657x，P3约1.232580955x。收益混合累加循环和布局/cache，不能全归算术或新RTL。

已启动父/候选交错五对fresh RTL重复，入口tools/run_cpu_block2_repeat5.py；新候选源码src/p3_native_block2_align64_custom.c，独立审计runs/cpu-block2-align64-audit-20261113-01/result.json。完整native330、十二问、真实协议与最终固件整核物理仍待补。轻量构建只私有固件和初始化镜像，复用父只读库/Vsim，每候选约11MiB，避免重复0.66GiB构建。脚本已按实际RTL容量检查并自动创建modules链接，历史失败不覆盖。

## 2026-11-13 D029：完整适配回归、GPU active reset及针对性电路修复

- CPU已启动12冻结问题父/候选fresh RTL配对，tools/run_cpu_block2_sessions.py；先用既有loader验证SDRAM128bit/512列bank交织，再逐输入验证模型/词表/LUT段与原image完全一致且不含expected token。当前前三对token/hidden/logits一致，完整生成加速约1.31%–1.37%，尚在执行，不授全12PASS。每构建约11MiB。
- 独立审查新增独立gate/up/shared scale及非法scale/expert差分12000调用/192000输出/status一致，runs/cpu-block2-native-scales-20261113-01，仅host native shape，非RTL330。
- GPU已实际实现私有safe reset：submitted未完成请求保留orphan直到callback完成并隔离旧epoch，完整重放20DCR，目标用户launch10 busy64后reset/reissue。冻结MINI33seed1–10十个真实processor进程数值32BF16/status均golden一致，runs/gpu-mini33-reset-20261113-audit.json。所有精确busy64时old_requests=0，故不声称非空orphan动态覆盖；AFU/full330/newQ6资格仍单独HOLD。独立审查继续核对源码/事件。
- 最新CPU block2固件10653words bank0已制作地址buffer tree并mapped SAT通过，physical/cpu-block2-rom-buffer-tree-20261113-02；同die配对step route在修正OpenROAD调用后推进，不把早期geometry/空DRC当最终PnR。
- 所有新文件optimization/p3内。原计划仍HOLD_NOT_FINAL_ACCEPTANCE。

## D030：十二问与GPU五对重复已实际完成

状态仍为 **HOLD_NOT_FINAL_ACCEPTANCE**。本节取代上文十二问“尚在执行”的状态。

CPU block2-align64完成12问题×父/候选=24次新VexRiscv RTL。独立审计重新解析原始token/hidden/logits、status/count、generation/P3周期、宿主BEGIN→COMPLETE事件，并重算日志/固件/内存镜像SHA。12/12 exact且完整生成零退化；合计speedup 1.012002018448x（周期减少1.185968%），逐问题speedup 1.010604167–1.013726739x。证据runs/cpu-block2-sessions12-20261113-01/audit.json。这是固定模型native集成回归，不能当generic330或物理频率资格。

GPU固定Q6补跑03/04/05三对，加已有01/02共五对fresh SimX；所有11token/hidden/logits exact、周期完全重复：generation14066408→14055069，P32254057→2243858。审计逐SHA绑定原始证据及实际helper穷举；host墙钟改善不一致，不能声称仿真器吞吐稳定提升。证据runs/gpu-q6-repeat5-20261113-01/result.json。固定Q6并不支持generic任意scale资格。

继续中的任务：非空pending请求复位/孤儿callback压力门；基于实际placement坐标的ROM buffer分组新拓扑；独立审查完整native/generic映射。旧实例序buffer-tree同die路由退化已拒绝。完整native330/最终整核物理仍未放行。

所有新增实体文件在实际工作区optimization/p3内；未生成工作区外文档。CPU私有构建使用父Vsim和库链接避免复制大缓存。保留已验证净清理3,193,240,334bytes的历史回执，活动构建不清理。

D030补充：GPU非空submitted未完成请求复位压力门已十seed新processor RTL通过，runs/gpu-mini33-outstanding-20261113-audit.json。每条launch10在busy14捕获submitted_unready1/old_requests1，重放20DCR；最终orphan remaining0/retired1，32BF16/status golden exact。主线程已独立重算全部input/log/source/runtime/golden与result SHA。该补充门不替代冻结busy64，仍不能授予AFU或最终固定Q6 native330资格；旧epoch隔离的独立源码/事件审查继续。GPU十二问fresh配对SimX已首4题exact并加速，完整12尚在运行，入口tools/run_gpu_q6_sessions12.py，runs/gpu-q6-sessions12-20261113-02；首次脚本转义启动失败保留01，未计PASS。

D030最终回归更新：GPU十二问也已完成12×父/候选=24次fresh SimX并通过独立模型/vocab/LUT逐段、目标源码/header、实际helper SHA、原始token/hidden/logits跨CPU、generation/P3/token时间及host QA审计。完整生成逐题均无退化，合计speedup 1.000867111075x，周期减少0.086636%。证据runs/gpu-q6-sessions12-20261113-02/audit.json。CPU十二问和GPU十二问合计48次本轮真实运行，不是复用历史回答；固定native集成回归不替代generic330/AFU/最终物理资格。空间坐标56组buffer新拓扑SAT已PASS，路由仍在执行，未宣布WNS/PPA。全部文件仍在工作区。

D030后端/合规适配新进展：空间01(56buffer)SAT通过，早期DRC4370/area14834；空间02(42buffer)SAT通过，DRC4416/area14614；父4381/14225，同die同约束且父原证据复用有明确SHA。两轮均不晋升，无完整route/WNS/PPA。热点以met1 Short及内部decode为主，继续分级decode/分块同步ROM新结构实验，不再只调扇出。

已新实现host record/native adapter，显式转置gate/up/down布局、保留route及状态边界；330条中250条实际调用CPU block2 native候选（custom ISA在host仿真）、70条fallback结果/status/primitive与golden exact；10条BUS_ERROR为host unsupported，绝不计target PASS。runs/p3-native-dispatch-20261113-01/result.json。独立代码审查进行中，目标RTL/SimX集成仍未授资格。此为真实adapter差分，既不等于完整native330，也不替代两平台最终目标执行。

D030清理已实际完成：仅已结束CPU12问private构建408个普通.o，经与保留父对象逐SHA一致并确认未在该run bindings绑定后，替换相对链接，原重复内容53,360,832bytes；逐文件来源/hash/恢复方式见cleanup/cpu-sessions12-duplicate-objects-20261113/result.json。父对象、ELF/bin、Vsim、镜像和原始日志不变。首次路径层级断言在任何变更前停止，修正后完成，所有去重链接SHA复验。任何未来在这些private目录重编译前必须先复制解链接，避免修改父对象。连既有.gch净释放累计约3.2466GB（未扣本轮小回执/链接元数据）。

新高4位/低5位显式ROM decode已映射SAT通过，绑定10653word固件bank0的512个定义word，一拍同步读保持，其他bank及未定义尾部不变；同die路由诊断正在运行。physical/cpu-block2-rom-decode-20261113-01/result.json。不能据SAT宣布物理提速。

D030最新执行：CPU native/fallback资格固件真实构建通过36252bytes/容量37864bytes，使用同benchmark父RTL、真实custom scale ISA；fresh330正在运行，不能预授PASS，build/cpu-native-dispatch-20261113-01和runs/cpu-native-dispatch-20261113-01。目标是250native+80fallback(含10真实DMA fault)，与host10BUSunsupported分开记录。独立审查已补全GPU十二问0–11目标source无expected注入。
高4/低5显式decode mappedSAT通过但同die早期DRC5201/area14446，劣于父4381/14225，拒绝晋升；继续结构修正。无新WNS/PPA或整核频率结论。

D030 CPU目标资格已完成：新native/fallback固件fresh VexRiscv RTL330/330输出/status/primitive匹配对应原golden，运行打印fast250/fallback80/COMPLETE330，含MINI30十条DMA fault，原日志已保留；主线程再次独立重算全部绑定SHA并重新parse/join golden通过。runs/cpu-native-dispatch-20261113-01/result.json。此为原candidate helper在资格adapter中的真实custom ISA，不等于生产LLM新增transpose开销或新问答性能；协议专项、GPU最终适配器330及整核物理仍缺。全部文件在工作区。

## D031（2026-11-14）：最终适配器、协议和电路继续

原计划仍HOLD_NOT_FINAL_ACCEPTANCE。已重新派发实际GPU cooperative native/fallback全量实现、资深硬件后端优化及独立连续审查。GPU首个同固定Q6 INT32 helper的设备dispatcher已fresh SimX 250native+70fallback=320数值/status/primitive exact；10BUS明确unsupported，正在补真实processor/fault，不转授旧generic资格。runs/gpu-native-dispatch-20261114-01/result.json。

CPU原native固件新跑MINI31–33十seed=30条UART ready/valid背压/17cycle hold/reset2000事件与golden全部PASS，严格比较新sim.v转换后等于旧边界dut.v才复用immutable仿真器。runs/cpu-native-protocol-20261114-01/result.json。边界是UART，不是DFI或busy64。

独立审查额外发现冻结330外的fallback错误传播bug：各scale合法但乘积不合法时，忽略course转换错误而发布status0。原冻结330结论不变，修正新固件立即传播status4/count0，requant错误也传播；build_cpu_native_dispatch_fixed.py在新build编译35708bytes/37864bytes容量，fresh330/330再次exact，fast250/fallback80，含十DMA fault。runs/cpu-native-dispatch-fixed-20261114-01/result.json。修正固件协议30重新执行中，不沿用旧协议PASS。原bug probe及失败证据独立保留reviews/d031-cpu-audit-20261114。

物理正在尝试独立字节slice、不同decode划分及地址寄存器retime；一拍formal与真实路由分别核验，未获得新整核WNS/PPA。所有新文件和缓存均在optimization/p3；不新增重复大构建。

D031修复收口：fixed CPU固件fresh330/330再次exact，并以精确fixed固件新跑30条UART协议全部事件/golden/SHA PASS。另新四条scale乘积上/下界非法输入已实际RTL status4/空输出，独立generic host reference一致，剩余326冻结记录无变化exact；runs/cpu-dispatch-product-edges-20261114-03/result.json。首两次缺只读modules/config未启动CPU，03原始运行完成后host全seed比较器不适用替换输入，已修正为四条参考+326逐条golden；不将启动/审计错误算通过，不改原golden。所有旧失败证据保留。
GPU同cooperative helper新SimX320门已独立SHA/ELF fence/barrier/输入转置审查；processor selected路径正在补真实fault状态映射，不能将硬件error witness而status6当golden5。
物理四8bit切片earlyDRC3174、area15602，对父4381/14225，拥塞改善但面积增加；只允许继续600秒有界完整route，不晋升PPA。高5低4/地址retime均失败，报告reviews/backend-rom-structures-20261114.md。直接速度新候选在当前CPU block2align64上组合fixedQ6 INT32，fresh root5运行中，以完整generation周期而非P3局部决定。

D031直接速度新实测：当前block2上直接Q6i32首轮P3588785但完整generation10382596，相对原10127934退化，拒绝。ELF显示后续generate前移128字节，Ibus857504→1253792。单次有据helper128byte对齐后generate地址恢复0x38f0，freshRTL generation10100173/P3587070，11token/hidden/logits exact，1MHz配置10.100173s、1.089090256tokens/s（含EOS），hostQA17.594732287s。五对交错fresh重复执行中，runs/cpu-block2-q6i32-layout-repeat5-20261114-01，未授最终晋升。
新候选实际header helper提取穷举2147483649整数[-2^30,2^30]全部一致，覆盖INT16乘积；独立scale/native形状12000调用/192000输出/status一致。runs/cpu-q6-layout-exhaustive-20261114-01和cpu-q6-layout-native-scales-20261114-01。只fixed native Q6、不转授generic/新330/12问。源码位于build/cpu-block2-q6i32-layout-20261114-01/bios/p3_native_ctx.c，后续晋升须固化同SHA且新固件物理重新绑定。
后端4byte切片600秒完整route超时，末迭代1319违规，失败保留，不授route/PPA。fresh父同预算仍在执行。当前全GPU processorRTL330回归仍在推进，未完成前不计全量PASS。


## D033：P3分列与布局联合实验、分组ROM结构、宏工具恢复

新g2d4显式累加与compact布局原本退化；实际双jump40byte布局在三对fresh RTL完整generation10100173→10067122（约0.327%周期减少），P3587070→591871反增，联合布局收益不可归纯算术。新native330/UART30 PASS，十二问和独立审查收口前不晋升；单pad消融10075905。固定ROM容量不扩，超容量四臂失败保留。候选src/p3_native_g2d4_q6_layout40_custom.c。后端继续分组寄存选择器与真实PDK/OpenRAM宏恢复，局部SAT/早期STA不替代整核签核。


## D035：最终固件网表接入与输入一致性补门

主线仍为 P3 同词表、同模型、同语义的完整问答提速。当前 signed-bias/helper32 候选 CPU generation 为 10,060,264 周期，P3 为 585,212 周期；不能把局部后端时序裕量当作整核 Fmax 或问答提速。

1. 保留实际新固件 bank5/20 的详细布线、天线修复、真实信号连通、routed SAT 和显式加载新 SPEF 的 STA；其余 19 个 bank 新综合且各做定义地址的一拍等价，完成 21 bank 联合读检查后接入真实 CPU 新编译回放。若解释型全网表遍历在冻结预算超时，保留失败，使用编译型仿真完成相同检查，不删除或改写失败回执。
2. 独立审查发现历史 root5 镜像的 user.utf8 仍为旧天气文本，而实际被 CPU/GPU 消费的 prompt token 确为 root5。保留历史镜像及 SHA，另建 canonical root5 镜像，文本、prompt token、manifest 统一，逐段证明模型/vocab/LUT 不变、generated 区不含期望输出。两端用新镜像 fresh 执行并记录 token/state、周期及宿主时间。
3. ROM 全网表功能回放无 SDF，不能授整核布线/频率/PPA。继续完整 VexRiscv narrow 核与当前固件 ROM/真实宏接口综合及后端绑定；宏的实际连接和完整几何 DRC/LVS/TT 表征仍为门，不能用抽象视图 DRC、库属性适配或局部 block 结果替代。
4. 新构建与临时目录限定 optimization/p3。完成后清理已结束构建的可重建缓存，须核对进程、证据引用、可恢复归档及 SHA；保留二进制/RTL/固件/原始结果。

G5/G6 维持 HOLD_NOT_FINAL_ACCEPTANCE，待完整电路物理、功耗及最终统一交付门通过。




