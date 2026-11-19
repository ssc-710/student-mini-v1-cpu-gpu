# 原 P3 计划阶段核查（2026-11-13）

依据 `PLAN.md` 第10节 G0–G6 放行门核查。总体状态 **HOLD_NOT_FINAL_ACCEPTANCE**，不能声明原计划完成。此表是现有证据审查；CPU block2-align64 为主线程刚完成的新执行，已完成交错五对重复，尚待全资格。

|原阶段|当前状态|已实际完成|尚缺/不能转移的资格|
|---|---|---|---|
|G0 盘点、清理边界及冻结|基本成立，持续维护|实际ASCII工作区可构建；模型/词表/LUT/golden与输入按run SHA绑定；已净清理3,193,240,334bytes历史.gch并保留可恢复归档|不是所有build均有必要保留；新候选仍须逐项绑定，不应用旧大学路径cleanup plan|
|G1 新baseline与分段计时|当前参考已成立|CPU inline fresh RTL generation10,235,712/P3757,580；GPU fenced fresh SimX S14,202,355/C14,066,408，P3分段及token计时；processor RTLSIM已有对应两臂|宿主墙钟不是物理GPU吞吐；当前新候选需匹配父链与重复策略|
|G2 精确算法候选|部分PASS，按候选区分|scale-context、CPU custom/narrow算术及协议局部门；GPU Q6 INT32实际两header helper的2,147,483,649整数超集穷举一致；固定Q6两对SimX和RTLSIM输出exact|GPU generic任意scale不可继承固定Q6资格；CPU block2-align64已五对RTL root5 exact并补9000次native形状host差分；仍需完整适配范围/RTL协议|
|G3 CPU/GPU接入和平台验证|**未完成**|CPU custom/narrow benchmark1000中P3=330/330、P1=330/330、P2=340/340；CPU UART专项30；GPU generic fenced320数值exact/10fault另有真实RTL MINI30seed1–10链；真实processor ready/valid selected MINI01seed1 stall/hold17门|benchmark ABI不等于native ABI；当前完整LLM候选尚无同实现完整native330/全P1P2回归。GPU MINI31/32精确冻结seed1–10已在native processor完成20条；MINI33精确busy64 reset/reissue十seed已通过native processor门；非空orphan压力与完整AFU边界仍缺|
|G4 LLM真实验证|root5当前门PASS；全回归未完成|CPU/GPU多轮fresh“根号5等于几？”均11token/hidden/logits一致，实际回答“我无法获知实时天气。”；词表未改|当前最终候选须重做冻结其它问题、原始模型集成回归；不能将历史不同ABI或程序结果拼成新候选资格|
|G5 对应电路前后端|**未完成**|CPU narrow finish局部route/OpenRCX WNS+3.72→+5.49ns，area14400→9397um2（动态die不同）；GPU limb等局部证据；新ROM失败已记录|最终固件/整核macro绑定STA/PnR、完整route DRC、hold、多角、PDN/天线/LVS和活动功耗仍缺。ROM当前路由失败，无新有效整核WNS/PPA；旧固件bank结果不可沿用|
|G6 重复性能实验与交付|部分完成，**未放行**|CPU inline/父候选及GPU fenced有重复fresh证据；GPU新Q6两对SimX周期重复且RTL方向一致；原始token/日志、SHA及清理回执已保存|CPU新候选交错五对已完成；完整逐case性能回退、全部资格与物理资源门及统一最终交付未完成|

## 当前速度候选结果

- CPU当前合格性能参考仍为inline64，generation10,235,712/P3757,580cycles。Q6i32因整体退化不晋升。
- 新CPU block2未对齐：generation10,325,668/P3592,452。算子快但整体慢，不晋升。新align64：generation10,127,934/P3614,629，1MHz下10.127934s、1.086105024tokens/s（11含EOS），hostQA17.499845388s。已完成交错五对fresh RTL周期重复，继续资格验证，尚不宣布最终获胜。
- GPU新固定Q6 INT32两对fresh SimX：generation14,066,408→14,055,069（1.000806755×），P32,254,057→2,243,858；processor RTLSIM14,003,538→13,991,326（1.000872826×），P32,260,888→2,250,307。是同limb RTL上的软件算法宽度优化，非新RTL拓扑/物理频率收益。

## 关键原始证据入口

- `runs/cpu-generated-custom-narrow-frozen1000-audit-20261108-01/result.json`
- `runs/cpu-generated-custom-narrow-protocol-audit-20261108-01/result.json`
- `runs/cpu-inline-root5-resume-20261113-01/result.json`
- `runs/cpu-inline-block2-root5-20261113-02/result.json`
- `runs/cpu-inline-block2-align64-root5-20261113-01/result.json`
- `runs/gpu-full-4t-fenced-resume-20261113-01/audit.json`
- `runs/gpu-fenced-q6i32-20261113-01/audit.json`、`02/audit.json`
- `runs/gpu-q6-exhaustive-20261113-01/result.json`
- `runs/gpu-fenced-q6i32-rtlsim-20261113-01/audit.json`
- `runs/gpu-protocol-processor-stall-20261113-02/audit.json`
- `reviews/backend-resume-20261113.md`
- `cleanup/historical-cpu-gch-20261113/result.json`

## CPU轻量构建独立审查

`build_cpu_block2*.py`复用父RTL/Vsim并私有替换运行时readmemh ROM，输出hash确认同sim.v和Vsim；这是一条固件/布局实验，不是新RTL重编译。库以只读使用方式链接父目录，不能随后在父库目录make或清理。实际测试确实读取新ROM：align256因超过10671words在readmemh越界失败，未计PASS；align64容量检查后才运行。

需修复脚本的通用防错门：当前构建脚本只检查bios<=131072bytes，但复用Vsim真正ROM为10671×4=42684bytes，应从父RTL数组深度核验而非沿用SoC映射窗口；应自动创建modules只读链接，避免恢复时再次缺动态模块。未对齐build首轮缺LiteX PYTHONPATH与run首轮缺modules失败均保留，不作为已完成执行。

双列循环每列累加顺序仍k=0..15，INT8乘积INT32累加在16项范围内不溢出，Q6/SiLU/down BF16表达式未变，apply2保留每元素custom scale且正确分离gate/up ctx；但这些源码检查不代替同native ABI的330/错误协议运行。

下一优先次序：稳定并审计align64完整问答收益 → 同nativeABI数值/集成回归 → GPU精确冻结协议与安全active reset → 最终实现整核后端与活动功耗 → 至少5次公平重复及最终证据包。持续以完整generation周期晋升，不能以局部P3或初始DRC替代。


## 本轮收口补充

CPU align64父/候选五对交错fresh RTL全部周期重复，generation1.010641657×、P31.232580955×。native形状host差分9000调用/144000BF16全部一致，custom scale仿真不代替RTL330。GPU MINI31/32共20冻结记录native processor seam通过；AFU与MINI33尚缺。当前后端新取得的是旧inline10671word bank0映射一拍SAT以及真实早期DRC几何，不是最新block2固件或最终route；不得转移资格。


D029最新：GPU精确首busy拍起计64拍复位重发已fresh十seed通过，runs/gpu-mini33-exact64-20261113-audit.json；原START ACK后计数的较弱门保留，不沿用为精确门。old_requests均0，非空orphan尚待动态验证。CPU十二问已前五对fresh token/state exact且完整周期加速1.012–1.014x，完整12尚未完成。

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
