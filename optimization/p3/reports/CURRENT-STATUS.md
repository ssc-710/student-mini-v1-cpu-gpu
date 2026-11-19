# D043 用户要求暂停（优先于历史记录）

已暂停并保存断点，详见 [D043-RESULTS.md](D043-RESULTS.md)。bank16七实例真实替换后完整原厂GDS DRC0/未知层0、LVS776devices/785nets唯一匹配，最终填充SPEF setup+4.19/hold+2.74ns/TNS0及512SAT通过；功能面积+52um²。bank17/19局部route/STA/SAT通过，bank18两恒0端点专项通过。独立审查及PG/其余bank/SRAM/整核仍缺；无新增端到端速度或本轮新问答。三个agent已中断，核查无活动任务工具进程。整体HOLD_NOT_FINAL_ACCEPTANCE。生产周期和既有问答记录不变。

---

# D042 当前续行（优先于下方历史记录）

详见 [D042-RESULTS.md](D042-RESULTS.md)。整体 **HOLD_NOT_FINAL_ACCEPTANCE**。bank20五单元真实重设计已通过完整GDS DRC0、器件LVS唯一匹配和最终SPEF STA+4.10/+2.75ns，增加功能面积70um²，无新增速度。新网表整CPU fresh问根号5已PASS：11token/state/cycles exact，generation10060264/P3585212，配置1MHz10.060264s/1.093410670token/s；本次hostQA224.177018458s/process233.381571990s。SRAM六个原生局部模块DRC0/连接exact，目标抽象6→0，仅诊断，完整宏仍FAIL。bank3两PG后端方案300s超时保留，无finalODB，下一按实际pin热点修布局。本轮PCH净释放128544779bytes，490MAG透明压缩allocation释放14115812bytes，原路径SHA保留。历史gap03过期绑定已显式披露。持续独立审查，整核物理和最终公平CPU/GPU问答仍未完成。

---

# D040 当前续行（优先于下方历史检查点）

整体 **HOLD_NOT_FINAL_ACCEPTANCE**。继续 P3 算法、RTL 与物理后端提速闭环，生产模型、词表、LUT、golden 和 signedbias 固件未变。本轮物理进展尚不能换算为新增问答速度。

- 算法及合规资格保持：CPU 全1000（P1/P2/P3=330/340/330）、native330、UART30、边界与12问已通过；固定Q6全域2147483649整数exact。生产CPU generation10060264/P3585212；对g2d4减少0.06812%/1.12507%。
- bank10 独立实际复核73项全部通过：512词固件bits0/1恒1且实际tieHI驱动；fresh完整SAT、loaded-SPEF和6847输入/32输出driver通过。setup+3.90ns/hold+2.73ns/TNS0/电气0；2常量未约束、0非恒定未约束。四个未使用驱动明确披露，原genericFAIL保留。仅局部信号资格，尚无PG/GDS/LVS。
- 四bank（5/10/14/20）实际postroute网表+17mapped新编译并真实VexRiscv问“根号5等于几？”完成。11token及全部hidden/logits/逐token与算子周期exact，仍回答“我无法获知实时天气。”。token IDs [67,69,84,97,90,56,71,51,82,8,4]。编译62.857657481s，generation10060264；配置1MHz生成10.060264s、1.093410670token/s含EOS；宿主QA211.379619771s，进程220.533164380s。此为逻辑后端集成回放，无SDF/整核物理频率资格。
- GPU最近实际干净输入SimX：generation14055069/P32243858；宿主QA10.467320119s、1.050889805token/s；无签核频率。本轮CPU局部变化不沿用为GPU新增收益。
- bank14新PG实际9280端子BAD0、VDD/VSS连续；原300s PG后reroute超时，无finalODB；仅清旧signal/clock dbWire后freshroute仍300s超时。独立确认2289普通线删除、2PG/2specialwire保留，组件/端口/特殊布线/逻辑均byte identical。不得以旧信号PASS授予新PG后资格。当前改为先floorplan+PDN再pad2 freshplacement，同300um die；首次路径错误保留，02已真实300s超时，无finalODB，保留FAIL；下一步按met1引脚热点精确布局修复，不能重复相同预算。
- bank3同300umdie/pad2首轮300s timeout；依据7条末快照热点对两driver定向pad4后实际routeDRC0，天线24→2仍FAIL；initial loaded-SPEF489slew且2常量端点，未晋升，实测489slew分别属于address3的387项和address4的102项；新增两buf16 root后512词sourceSAT通过，新route282.409s及天线修复130.700s终态PASS：DRC0/antenna0/electrical0，area17559um2、setup+3.59ns/hold+2.79ns/TNS0，6831输入/32输出driver与完整512词routedSAT通过。独立fresh73检查通过。5routed（3/5/10/14/20）+16mapped新整CPU问答已PASS并独立80项复核：编译60.461692321s、gen10060264/P3585212、11token/state/cycles全exact；宿主QA208.217406747s、进程217.107804622s；配置1MHz10.060264s/1.093410670token/s，非物理频率。不授PG/GDS/LVS。中间正slack不代替电气/天线资格。
- bank20稀疏tap+filler完整真实GDS已独立文件读回DRC0/unknown0，抽取完成；原厂CDL/nativeMOS与series对照仍LVS FAIL，保留10device/5net差异。D041读Netgen实现纠正：DEVICE行2849是fanout计数而非nodeID，原“参考PG全同node”判断不成立。已定位a21oi_2四实例及a21boi_2一实例的独立串联stack与CDLm=2共享内部节点差异，数量恰解释10device/5net；仍须真实pin/property等价验证，不能据计数授LVS。tap间距、最终RCX/PG重绑定、LVS及整核仍缺。
- SRAM clockcenter目标真实688.942211557s生成，fullgeometry712801DRC+18unknown，extract241.037s超时，abstract10，未晋升。已纠正第二M3簇为row-address阵列供电via landing而非clock rail；后续先局部供电/通道几何证据再决定重跑目标宏，不能重复无差异昂贵生成。
- 新四bank整CPU运行结束的2PCH经归档解压逐SHA验证，binary不变，净释放128546388bytes；新5routed结束后2PCH另净释放128513877bytes，binarySHA不变；此前清理分别保留回执，不把归档节省称工作区净减少。所有新增实体/cache/home/tmp仍在实际工作区optimization/p3内。

证据：reviews/d040-independent-bank10；reviews/d040-bank14-pg-independent；reviews/d040-backend-engineer；runs/cpu-signedbias-4routed-core-replay-20261114-01；cleanup/d040-four-routed-cpu-pch-20261114-01；reviews/d038-bank20-gds/sparsetap-gds-roundtrip；reviews/d037-sram-clock。CURRENT-RESULTS.json仅绑定已终态证据，运行状态以各result和真实进程为准。

下一步：bank3局部及CPU功能已收口，推进bank3/10/14 PG-aware物理；解决bank20两leaf的真实器件拓扑与CDL m=2表示；SRAM供电落点/内存hold-oldvalue适配；其余16bank及整核CPU/GPU PG/PDN/GDS/LVS/STA/PPA/活动功耗，最终公平问答验收。持续独立审查与资深工程子任务。

D041续：独立73项bank3+80项5routedCPU+39项既有PCH归档=192项通过。bank20官方GDS mode实际重跑仍LVS FAIL，最小emptytap测试两mode均通过，未支持emptytap造成参考PG异常假说；单leaf a21oi_2实际也FAIL。SRAM供电landing可逆局部移1.5um第一次abstractDRC仍10；实测轨间可用0.92um而供电落点含间距需0.93um。新落点+0.085um、单M3轨+0.020um实际局部abstractDRC10→6，第二簇消失、第一簇仍在，baseline/patch rowDFF抽取SPICE byte exact。仅局部诊断，尚须generator实现、整channel连通与fullgeometry；不重跑无差异昂贵目标宏。bank3工具导出真实TTLIB/LEF及实际import/link PASS，限信号抽象。

---
# D036 续行检查点

整体 **HOLD_NOT_FINAL_ACCEPTANCE**。P3算法和CPU/GPU真实问答资格保持；本轮重点推进同一候选的物理实现，没有新的端到端速度收益可宣布。所有新文件、临时目录及归档均在实际工作区 `D:/college/codex/student-mini-v1-cpu-gpu/optimization/p3`。

- CPU生产候选继续为signedbias/noinline/helper32，完整生成10,060,264cycles、P3 585,212cycles；相对g2d4分别减少0.06812%/1.12507%。CPU全1000、native330、UART30、全域算术及12问资格已有，不重复充分完成的测试。
- 最新干净root5实际结果：CPU全21映射ROM回放与GPU新JIT SimX，11token/state exact，回答均为“我无法获知实时天气。”，原词表不变。CPU配置1MHz 1.093410670token/s、10.060264s；宿主QA213.902733682s。GPU宿主1.050889805token/s、QA10.467320119s，设备0.782635788token/百万周期，无签核频率。
- 新bank20 PG与signal reroute实际完成：5668PG端子正确、VDD/VSS连续、routeDRC0/antenna0；显式readSPEF setup+4.11ns/hold+2.74ns/TNS0、电气/未约束0，cellarea10167um2。独立61check PASS及address<419无ignore_gold_x SAT PASS。旧address485越界harness失败保留，不改写。尚缺GDS/MagicDRC/LVS/IRdrop/功耗/整核。
- bank14原byte4改300umdie实际routeDRC0/antenna0，cellarea17189um2、setup+3.78ns/hold+2.76ns/TNS0，但316slew均属于address[3]，因此FAIL。die面积约原2.16769倍，不能称等面积收益。自动修复重route触发-11崩溃；140全地址分支GRT0116；仅A3的18buf4分支SAT通过但300s timeout，日志最后3个违规不是最终DRC。新单A3root buf16方案现已实际local PASS：routeDRC0/antenna0/electrical0、6916inputs/32outputs driver PASS，提取后setup+3.13ns/hold+2.75ns/TNS0、cellarea17457um2，routedSAT及独立64项检查通过；另独立freshSAT证明559处load替换可逆且所有512词精确。未完成PG/GDS/LVS或整核。
- bank5/20工具真实导出的TT时序LIB+LEF抽象通过独立审查，限信号层级准备。138check内存边界审查实际证明OpenRAM模型直接连接不保持禁读输出，需要真实适配；不能改模型的X赋值来称等价。整核逻辑映射240s超时，未取得网表/时序。
- 新80x64修复宏实际生成677.180755s，完整geometry75.456678s仍712801DRCtiles和18unknownlayer，abstract10；extract241.092411s超时，无LVS/表征。已定位M3数据轨与clock/row-address-DFF via landing冲突，下一步具体改clock层与landing。
- 新清理42历史PCH，逐归档SHA验证，21最终simulator不变，净释放2,912,916,887bytes（约2.91GB）；目标宏结束的temp/crash recovery另11,301,195bytes。此前D035净250,490,107bytes另计，不称工作区净减。原始源码、最终二进制、golden与证据保留。

下一步：bank14已取得局部PASS，推进bank10及其余18bank；bank5落实PG重route；SRAM clock几何修复与内存语义适配；其余19bank及整核CPU/GPU物理签核。新独立审查与资深工程子智能体持续执行，活动会话请检查process/result，不将历史“运行中”当当前状态。

证据入口：`CURRENT-RESULTS.json`、`CURRENT-INDEX-AUDIT.json`；局部物理 `reviews/d036-bank20-pdn`；独立 `reviews/d036-pg-independent`、`reviews/d036-memory-audit`；目标宏 `reviews/d035-target-macro`；清理 `cleanup/d036-historical-cpu-pch-20261114-01`。


## D037–D038 实际新增结果

- 新bank5 PG完成：8292PG端子正确、VDD/VSS连续，含PG详细布线DRC0/天线0，提取+4.15/+2.75ns/TNS0/电气0，完整512词SAT不忽略golden X。原联合阶段在最终ODB写出后超时，保留FAIL；对该实际ODB另做恢复验证并独立fresh检查，112项PASS（另含bank14抽象）。
- 新bank14 postroute网表已接实际VexRiscv整CPU，三bank postroute、十八bank mapped，新编译62.052713230s并实际重新问“根号5等于几？”。11token/state/所有逐token和算子周期exact，generation10060264/P3585212；配置1MHz10.060264s/1.093410670token/s，宿主QA218.160509320s、进程226.678371091s。回答仍“我无法获知实时天气。”。独立终态81项PASS。日志、完整token流和binarySHA保留在runs/cpu-signedbias-3routed-core-replay-20261114-01。
- bank14工具导出TTLIB/LEF已身份一致化并实际import/link PASS；只信号模型，缺PG/GDS/LVS，不为物理频率。
- bank10 pad1 die300实际route300s timeout；定位met1 pinaccess短路，改pad2后routeDRC0/天线0、area17053um2、setup+3.72/hold+2.73/TNS0，但263slew全部来自address4，所以保留电气FAIL。按实测地址4增加buf16，已SAT PASS并新route；以独立新目录终态为准。
- bank20真实stdcell GDS+DEF导入、完整geometry：原默认网格92335DRC，0.005um精度修复量化后1086仅nwell类；实际标准filler补row后完整DRC0/unknownlayer0，抽取完成（87.115s）。LVS仍未通过；后续标准tap/endcap及原厂器件模型命名映射继续。禁止把routerDRC0或abstract0代替完整GDS检查。
- SRAM clock45和clock24两个候选被实际完整geometry/LVS拒绝（407vs409nets，clock短VSS）。保留原拓扑只将rowDFFtap居中的小宏395devices/409nets唯一、显式Calibre参考适配LVS PASS；原Magic参考属性FAIL保留。目标80x64已真实生成，完整geometry仍712801和18unknownlayer，抽取/abstract继续，以最终回执为准。
- 本轮新CPU结束后2PCH经归档逐SHA验证净清理126210813bytes；小宏3个结束临时GDS另2744853bytes。与42历史PCH2912916887bytes分项，不混淆工作区净变化。

当前活动工作的真实session：bank10 address4 root+pad2 PnR为91709；目标80x64clockcenter验证由d037_sram_clock_actual执行；bank20GDS/LVS与tap/fill由d038_bank5_gds_actual执行；d038_independent_actual持续审查。问答session52570已结束PASS。下一步先完成这些终态，推进剩余ROM、SRAM适配和整核物理，不重复充分通过的算法全域/1000cases。

---

# P3 当前实施状态（D035）

整体 **HOLD_NOT_FINAL_ACCEPTANCE**。主线仍为 P3 算法、RTL 与物理实现提速闭环。实际工作区 D:/college/codex/student-mini-v1-cpu-gpu；新增产物均在 optimization/p3。模型、词表、LUT、golden不变。下方D034为历史检查点。

|门|当前完成|剩余工作|
|---|---|---|
|G0|SHA绑定；D035已验证可恢复PCH清理250314879bytes|持续维护活动依赖与缓存|
|G1/G4|干净root5输入两端实际执行，CPU全21真实映射ROM整CPU问答11token/state/逐token周期exact，GPU新私有JIT SimX exact|最终物理绑定及公平性能收口|
|G2|signedbias/noinline/helper32全域2147483649 exact，三对fresh RTL复现|保留数值与scale范围契约|
|G3|CPU全1000（330/340/330）、native330、UART30、边界、12问PASS；GPU hostAPI330/rawdevice320|不混淆host故障适配和原生device资格|
|G5|全21bank mappedSAT、31977定义读及真实整CPU回放PASS；新bank5/20局部route/antenna/driver/routedSAT/loaded-SPEF STA PASS|其余19bank物理、目标SRAM宏、PG/PDN/GDS/LVS、整核STA/PPA/活动功耗|
|G6|相对g2d4 P3周期减少1.12507%，generation减少0.06812%；12问每题均快，对retained父合计speedup1.00073521|计划未完成，无整核PPA或物理tokens/s签核|

## 本轮真实问答

问题：**根号5等于几？**。两端实际回答仍为 **“我无法获知实时天气。”**。token IDs `[67,69,84,97,90,56,71,51,82,8,4]`，11个含EOS。原词表根/号/5为UNK，保持不变。

|执行|generation周期|P3周期|token/s（含EOS）|时间与口径|
|---|---:|---:|---|---|
|CPU VexRiscv RTL + 全21映射ROM|10060264|585212|配置1MHz：1.093410670|配置生成10.060264s；本次宿主QA213.902733682s、进程222.556582593s|
|GPU Vortex SimX干净输入、新JIT|14055069|2243858|宿主1.050889805；0.782635788 tokens/百万周期|宿主QA10.467320119s；kernel+sync10.449601870s；进程11.455209908s|

CPU 1MHz为仿真配置而非物理Fmax。真实映射ROM增加宿主模拟计算量，宿主时间不能当硬件性能回退，目标周期未变。GPU无签核频率，物理生成秒数保持null；宿主口径不用于跨平台硬件吞吐比较。

## 电路前后端

|局部ROM|cell面积 µm²|setup slack ns|hold slack ns|route DRC|天线违规|
|---|---:|---:|---:|---:|---:|
|新bank5|15572|+4.16|+2.75|0|0|
|新bank20|10167|+4.12|+2.74|0|0|

两bank均从新固件实际重做：RCX、write/read_spef、TNS0、信号driver检查和routedSAT通过。driver计数不等于全线段连续性或PG签核，局部结果不能推出整核WNS/Fmax。其余19bank按实例数排序实际批处理，bank14等在原203.765µm/.40密度下GPL0302容量失败，需明确标注新布局方案或映射面积改进；保留旧失败，不暗改对比预算。

小宏data channel下移四个m3 pitch后395/395器件、409/409网络唯一匹配。四项参考W/L按原始独立Calibre LVS视图显式适配后实际LVS PASS；原Magic参考属性仍FAIL。另两precharge连接M1补片使各leaf DRC3→0，完整宏DRC仍17864，未资格。80×64目标旧完整geometry712801/abstract10亦未通过；六宏18views/TT表征及整核PPA仍缺。

## 输入修复与证据

独立审查发现旧image的user.utf8遗留天气文本；实际prompt IDs一直为root5。新 `inputs/root5-clean-20261114-01` 只修分配24bytes中的正文为19bytes root5 UTF8+5个0，23处byte变化全在user段，其余model/tokenizer/scales/prompt/生成毒化区/header/offset不变。新image SHA `9d30e181ec709efb7c80b17716368bedf724d2d532f1e9e972c1d740c03dc2d7`。CPU/GPU本轮均用此新输入实际执行，冻结原件保留。

- 新整CPU真实映射ROM问答：runs/cpu-signedbias-all21-mapped-core-replay-20261114-01/result.json
- 21bank SAT：physical/cpu-signedbias-all21-mapped-20261114-01/result.json（原vvp300s timeout保留）；同网表同TB编译式31977读：verilator-read-proof/result.json PASS
- 新GPU：runs/gpu-clean-root5-20261114-01/{result,timing}.json
- 两bank物理：reviews/d034-signedbias-physical/{report.md,result.json}
- 独立审查和输入闭环：reviews/d035-independent、reviews/d035-clean-input
- 小宏修复：reviews/d034-short-repair-channelshift、reviews/d034-short-repair-precharge-area
- 可恢复清理：cleanup/d035-completed-simulator-pch-20261114-01/result.json，6个PCH归档解压逐SHA后移除，最终binary/源码/log不变，净释放250314879bytes，非workspace净减。小宏中间GDS另3241540bytes分项记录。
- 机器入口：CURRENT-RESULTS.json；SHA入口校验：CURRENT-INDEX-AUDIT.json。

## 下一步

1. 其余19bank按真实面积改进映射或布局，保留固定预算失败；晋升须route/天线/连通/RCX+loaded-SPEF STA/SAT实际证据。
2. 目标80×64及其余宏落实连接/precharge修复，解决foundry leaf工艺规则及生成互连DRC，实际DRC/LVS后TT表征。
3. 整核CPU/GPU集成、PG/PDN、GDS验证、整核STA/PPA和活动功耗，再做最终公平问答收口。继续独立审查和资深工程子任务。

---

# D034 历史检查点

整体 **HOLD_NOT_FINAL_ACCEPTANCE**。本入口替代历史文档顶部的旧状态，历史检查点保留。实际工作区为 D:/college/codex/student-mini-v1-cpu-gpu；所有新增产物在 optimization/p3。模型、词表、LUT、golden未改。

|门|当前证据|尚缺|
|---|---|---|
|G0 冻结与治理|逐run SHA、输入无expected；本轮22重复库释放1,947,725,296bytes|持续维护活动依赖与缓存|
|G1 计时|CPU/GPU新root5，CPU五对交错、GPU五对SimX重复已有|物理时钟不可由仿真周期推得|
|G2 算法|已资格Q6基础+新gate2/down4、compact/双pad候选；GPU4lane/fence/Q6 INT32；新候选helper2147483649整数精确、native12000calls exact|新候选P3局部反慢，整程序布局联合收益；fixedQ6不转授任意scale|
|G3 平台|CPU新g2d4全1000 RTL exact（P1 330/P2 340/P3 330）独立PASS；native330和UART30、4额外边界均新RTL PASS|GPU live hostAPI330/330和冻结协议已新RTL通过；保留device raw320/330与hostAPI330/330差别；processor接口不授AFU；P1/P2性能回退须解释和隔离|
|G4 问答|CPU新候选12/12 token/hidden/logits exact零退化；GPU12对先前PASS；本轮两端新root5已完成|最终生产接口/物理绑定后再收口|
|G5 前后端|新g2d4全21bank/84byte-slice31977读及新整CPU实际问答独立PASS；旧Q6bank5local333 mappedSAT/earlyDRC2179改善|无finalroute/extractedSTA/整核PPA；旧Q6local333仍300s timeout，新固件bank5重绑定推进；真实宏工具已SKY130 smoke，六宏18views未完成|
|G6 性能与交付|新g2d4 root5三对重复10,100,173→10,067,122；12问对retainedQ6父合计周期减少0.334915%；P3局部均慢|PPA、功耗、接口及逐case回退未闭环，不宣称整体完成|

## D034 当前推进（本节优先于下方D033历史条目）

整体仍 **HOLD_NOT_FINAL_ACCEPTANCE**。本轮继续算法与电路后端，未改模型/词表/LUT/golden，新增均在本工作区 optimization/p3。

- 新固定Q6候选：signed bias RNE、noinline、helper内jump32 padding；完整[-2^30,2^30]共2147483649整数与原helper exact。真实CPU RTL首次gen10060264/P3585212、固件42636bytes；三对fresh交错全部复现，相比g2d4 gen10067122/P3591871，完整生成减少0.0681227%、P3减少1.125074%。属于算法与代码布局联合收益，不能归因纯算术。
- native330全exact（250native/80fallback/10真实DMA错误）、UART30专项PASS、全1000目标RTL P1 330/P2 340/P3 330 exact，四scale乘积边界status4/empty+326冻结项PASS。主线程SHA审计在reviews/d034-primary/qualification-binding-audit.json；独立新候选终审已PASS，见reviews/d034-signedbias-independent/result.json。十二问候选fresh12/12 exact、每题P3及完整QA均快，合计generation speedup1.000735210643；父为retained g2d4，不能称freshpair12。
- 三项消融未晋升：自动inline gen10284696/P3653252；noinline gen10068180/P3583277（P3快但QA慢1058cycle）；native末端pad32 gen10069346/P3594560。保留真实证据，helper内pad方案目前最快。
- 新firmware SHA 7c1dae5426309d54b70715f02db1a4938b38346aa88a66f10f620adb8f59e1e9，相对g2d4仅bank5/20变化，其余19bank字节相同；全21bank/84slice31977读已新执行PASS，新整CPUbyte4前端已重新编译并实际回放PASS、10060264周期。改变的bank必须重做物理，整核资格仍缺。
- g2d4 ROM后端已从实测met1 shorts定位，改global trunk met2–5/detail仍met1；发现并修复OpenDB alias造成data0/1无driver（routedSAT不能代替物理连通）。flatconnect+10真实diode后actualroute DRC0/antenna0，全部32输出及6197信号输入driverPASS、routedSAT PASS；RCX+显式readSPEF setup+3.87ns/hold+2.76ns/TNS0，area15486um2。仅旧g2d4局部bank5，无整核GDS/DRC/LVS/PDN/活动功耗资格；新signedbias需新内容重绑。
- 80x64 1w1r/write_size20/wpr1宏已真实598.7266秒生成四layout/model文件；静态port/mask匹配，主模型1152读检查及独立2176读检查实际PASS。完整GDS无leaf替换的Magic DRC02实际66.641s完成，712801error tiles、18未知layer提示，未资格；旧small DRC0是默认maglef替换范围，不能当完整原GDS几何签核。另标准macro DRC脚本因前置抽取240秒timeout，未有该门结果。
- workspace新构建Netgen1.5.328修复旧1.5.133崩溃；实际small LVS完整报告FAIL，top395/395器件但408/409nets，bank_din0_1与p_en_bar0存在明确merge，replica特殊器件属性差异仍待修复。没有通过LVS/TTchar，不造LIB。selected322当前逐gitblob复查仍exact；额外工具与源文件按SHA另绑定。
- 立即续做：完成12问/新整CPU回放/独立终审；新signedbias bank5/20物理重绑；小宏真实连接修复及特殊SRAM层/器件工艺映射、目标宏真实DRC/LVS/TT表征；其余宏及整核STA/PPA/功耗。所有“running”以本节和各run终态为准。

## 已资格Q6基础问答与D033新CPU候选（真实执行）

问题：根号5等于几？两端实际回答均为“我无法获知实时天气。”，原词表将根/号/5编码UNK，未修改词表或答案。token IDs：67,69,84,97,90,56,71,51,82,8,4（末4为EOS）。

|平台|generation周期|P3周期|明确的token/s|时间|
|---|---:|---:|---|---|
|CPU VexRiscv RTL|10,100,173|587,070|配置1MHz：1.089090256（含EOS）；宿主：0.626249377|配置生成10.100173s；宿主问答17.564887727s；进程18.795543880s|
|GPU Vortex SimX|14,055,069|2,243,858|宿主：1.102268392（含EOS）；0.782635788 tokens/百万周期|宿主计算回读9.979420691s；kernel+sync9.961433852s；进程10.503836776s|

CPU配置1MHz不是物理Fmax；GPU无签核频率，不能填物理生成秒数。宿主口径各自定义不同，不能跨平台比较硬件吞吐。完整token/逐token周期/hidden/logits/二进制和输入绑定在对应run，不复用旧回答。D033新CPU双pad候选另实际执行：generation10067122、P3591871、配置1MHz10.067122s/1.092665809tokens/s（含EOS），hostQA16.611909122s/process17.874714046s；三对fresh重复及12问证明详下文，GPU此轮无需因CPU软件修改重复资格。

新CPU完整1000项最初39.07KiB超过benchmark ROM37864bytes，容量assert正确失败。严格剔除注释和ROM深度后，现有inline RTL与benchmark逻辑字节相同；用已有10671word ROM Vsim容量42684bytes真实重跑，1000/1000通过。失败回执保留，修复证明在tools/fix_cpu_full1000_capacity.py和runs/cpu-q6-full1000-capacity-correction-20261114-01。

资格适配器额外transpose/dispatch及代码布局开销：相对保留旧baseline，正常P1几何speedup0.9383、P2 0.8934、P3 1.3513，共490正常项回退>5%。这不是fresh配对，也不是生产LLM路径。已保存逐项清单runs/cpu-q6-full1000-20261114-02/performance-scope.json，不隐瞒回退、不将该adapter作为生产提速实现。

## D033 正在推进

CPU新增显式累加宽度实验。保留128/64布局的g2d4/g4d2/g4d4固件42716/42788/42892bytes，均超过固定42684byte容量，构建门阻止运行。紧凑16/16布局g2d4与g4d2真实RTL token/state一致，但完整generation分别10143173/10238623，退化而拒绝；g4d4仍超容量。

进一步有据布局探针的**实际实现**在scale_prepare和candidate return各含一个jump40bytes，未精确恢复父地址（generate从0x38f0至0x3908）。新g2d4双pad候选generation10067122，相对10100173减少0.327232%；P3 587070→591871反增，属于累加结构与全程序布局联合收益，不称纯P3算术加速。固件42636bytes，模型/词表/LUT/ROM容量不变。三对交错fresh RTL完全重复、native330和UART30均新执行PASS。十二问新候选12/12 exact、完整generation零退化，相对保留Q6父合计speedup1.0033604079568075×（仅候选本轮fresh）；完整1000新RTL1000/1000也通过。未作最终物理晋升，不沿用旧候选物理资格。单处pad消融新RTL10075905/P3590978，较双处慢，证据单独保留。入口runs/cpu-q6-explicit-block-probe-20261114-01至04和cpu-q6-g2d4-layout40-repeat3-20261114-01。

GPU live全330及MINI31–33已完成主审计和独立审计，rawdevice320/hostAPI330边界保留。清理1320个未绑定可重建cache目录释放13170300bytes，输入、设备ELF/VXBIN、runtime、原始日志保留；清理后两套审计已实际重跑PASS。

OpenRAM恢复改用官方tree及逐blob取文件，已得到原锁commit的322个运行时/技术/config源文件2386107bytes且git blob哈希全匹配；Magic实际smoke通过，SRAMcells真实源恢复。PDK release assets分块下载完成且官方MD5匹配、SKY130 init已实际PASS；旧Magic与PDK不兼容的tech load失败保留；新Magic8.3.700已实际加载SKY130A并保存几何smoke通过，实际宏生成继续，不能提前声称六宏18views恢复。详见runs/openram-locked-files-20261114-01等。

## 立即续做

1. 收口g2d4完整1000、scale乘积边界和全bank新整CPU回放的独立终审。新固件全部21bank变化，84byte-slice31977定义读与整CPU新编译root5 10067122周期已PASS；物理须全部重新绑定。新增布局收益不能全归于算术或新RTL。
2. G5新bank5分组寄存选择器结构的mapped SAT及公平route；优先降低地址扇出，不盲增面积/时间。恢复真实PDK/六种宏、整核提取STA与活动功耗。
3. P1/P2正确性PASS与资格adapter性能回退继续分别披露，生产native不加入该transpose适配层。
4. 所有新增实体文件/cache仍在optimization/p3；持续独立审查与资深工程子任务，清理仅在依赖/进程/绑定核实后进行。

证据入口：CURRENT-RESULTS.json；已资格CPU及GPU新问答见上表；独立all330为reviews/live-status-review-20261114/all330-result.json。当前仍HOLD_NOT_FINAL_ACCEPTANCE，无新finalroute/整核WNS/PPA。

D033清理：8个已结束探针build的136个普通.o与父逐SHA相同、无证据绑定后替换相对链接，释放17786944bytes。固件/RTL/镜像/设备和原始日志保留，重建前须copy解链接。新root5双pad token流已保留，1MHz配置10.067122s与1.092665809tokens/s（含EOS），该次hostQA16.611909122s、process17.874714046s；同问答原答案不变。宿主时间不归因硬件提速。

D033最终资格续：新完整1000独立审计P1 330/P2 340/P3 330及status/primitive/output/selection/input encode/SHA全部PASS；四scale product边界实际RTL status4/count0与独立reference一致、剩326exact。后端旧Q6bank5局部预译码earlyDRC2179但300秒完整route仍timeout，不授PPA。完整新固件物理绑定仍待后续。

D033缓存继续：新整CPU两.gch经进程检查、可恢复tar归档并解压逐SHA核验后移除，净113183561bytes；加GPU cache13170300和probe相同.o17786944，本检查点已验证释放144140805bytes。最终binary未改。qualification adapter相对保留priorQ6 full1000正常P1/P2/P3 geomean1.0281285/1.0455422/1.0172797、>5%退化0；不是freshpair也不撤回最初oldbaseline的P1/P2回退，生产问答速度仍以专门run为准。

D033最新新固件bank5重绑定：新byte4父及local333均新512词mappedSAT PASS；fresh同TCL earlypair父2992DRC/area15510/setup4.16/hold2.79，local333为2452/14858/4.17/3.06，earlyDRC减少18.0481%、面积减少4.2037%。仅局部earlygeometry/estimatedRC；新双方各300s fullroute已终态timeout，无finalODB/extractedSTA，不授签核。下一423局部预译码独立结构继续。

D033依赖终态：已恢复原locked源码322file、SRAMcell1658file及官方锁定SKY130A PDK，Magic8.3.700真实PDK几何smoke、ngspice42真实NFET OP和netgen网表比较通过。真实2x32小宏sp/v/gds/lef已生成，独立抽取04有界timeout；GDS解析112结构/4457refs无重复/缺失/环，阻塞继续诊断。六宏之一80x64、1w1r、write_size20、新words_per_row1真实layout正在session55975，所有临时仍workspace；不声称旧宏组织等价或18views完成。恢复工具净占约326MB，已清理下载/编译缓存75930322bytes。加本检查点其他清理，已验证释放234012147bytes（包含后端fanout可恢复压缩13941020），不是工作区净减值。

局部423新固件候选mappedSAT通过，但13719.408um2综合面积导致冻结density0.40 placement GPL0302要求0.42，已拒绝、不改约束晋升。新333完整fresh父/候选各300s均终态timeout，无finalroute/PPA。

D034清理续：失败几何rawstdout无损gzip解压逐SHA后移除原，释放36292487bytes；新整CPU两.gch可恢复tar解压SHA验证后移除，净114967391bytes。加LVS已结束下载缓存1525482，本轮已验证释放152785360bytes，非workspace净减；固件/RTL/最终binary/原始证据可恢复，恢复说明随receipt。

D034 GPU再次fresh：runs/gpu-d034-root5-fresh-20261114-01新编译真实SimX token/state exact，gen14055069/P32243858，hostQA10.905185225s/process11.96033855s/host1.008694467tokens/s含EOS，无签核频率。80x64标准abstract-view DRC独立实际运行6.345s得10，与完整geometry712801分别披露；overlay首short修复候选引入其他merge而拒绝。

D034清理补充：geometry02完整DRC坐标46,275,678bytes压成10,041,475bytes，解压逐SHA一致后移除raw，另释放36,234,203bytes；规则分类保存在reviews/d034-primary/geometry-drc-rule-counts.txt（规则列表可重叠不可累加成tile总数）。本轮已验证净释放189,019,563bytes，不是workspace净减值。

D035后端续：新bank5/20从实际ODB+显式readSPEF导出OpenSTA真实TT timing model与LEF，名称一致化后实际read_lef/read_liberty/link两宏PASS，见physical/cpu-signedbias-banks5-20-actual-abstracts-20261114-01/integration-roundtrip/result.json。仅信号抽象，PG/GDS/LVS未授资格。独立最终审查535项PASS，见reviews/d035-final-audit/result.json；其余19bank仍在真实优化，bank14共享32位映射2269→1842instances且SAT PASS，但同die拥塞路线尚未完成。






