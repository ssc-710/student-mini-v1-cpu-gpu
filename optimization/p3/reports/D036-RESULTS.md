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






