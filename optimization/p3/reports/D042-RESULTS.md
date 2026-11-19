# D042 执行结果与下一步

整体 **HOLD_NOT_FINAL_ACCEPTANCE**。主线为 P3 算法、RTL 与物理实现的问答提速闭环。模型、词表、LUT、golden、生产固件保持不变。本轮补齐物理正确性及集成，没有新增目标周期或物理频率收益。

## 实际完成

- bank20 仅四个 a21oi_2 和一个 a21boi_2 改为已真实验证的 drive4 单元。419 有效地址域的 source/routed SAT 通过，不忽略 golden X。原始 PDK/GDS/CDL 未改。新 route DRC0、antenna0；完整真实 GDS DRC0/unknown0，独立导出 GDS 回读通过。晶体管 LVS 在两种原始 setup 模式均唯一匹配，双方1423器件/1424网络；独立实际 LVS 复现。
- 最终 filledODB 的显式加载 SPEF 时序 setup +4.10ns、hold +2.75ns、TNS0、电气/非恒定未约束0。功能加二极管面积10237um²，比原10167增加70；填充后11227um²，比原11162增加65。旧+4.11ns不能作为新收益，最大tap距离/endcap及整核门未通过。
- SRAM 已把供电 stack +0.085um、数据 channel +0.020um、row-address jog +0.155um 落实到原生 generator 局部验证。六份新局部 GDS 全部DRC0/unknown0，三对提取 SPICE 仅归一顶层名称后逐字一致。新增rowaddr两模块由独立Magic重新验证。目标抽象第一簇定位为 logical port1、bit5、bank addr1_5；jog及相邻一条channel修复后实际abstract6→0。仍是27个历史maglef替换的诊断，原完整目标712801DRC/18unknown及宏LVS/TT未解决。
- bank3 实际新增PG9088端子BAD0、VDD/VSS连续。后插PG reroute与先PG再freshplace均在300s预算超时，无finalODB。旧末完整快照2865项/1602条PG短路；fresh末完整快照377项/13条PG短路，其余主要signal-pin热点。快照不是最终DRC，不沿用旧signalSTA授PG资格。下一需依据pre-detail实际单元和pin坐标定向布局，不重复同预算同方案。

- bank20最终filledODB/SPEF已真实导出并import/link TT LIB与含VDD/VSS端口的LEF。LIB缺pg_pin groups，仍不能授完整层级PG/功耗资格。实际791tap/67行；最大同行tap-center间距103.04um，二维功能单元中心到最近tap中心最大10.882431um。二者均为布局代理指标，不替代扩散区/同well连通与foundry规则，不能直接判通过或失败。最终视图physical/cpu-signedbias-bank20-pgabstract-d042-20261114-04，详细reviews/d042-bank20-pgabstract。

## 新物理网表真实 CPU 问答

新bank20最终filled网表接入五个routed bank整CPU。首次编译因PG-only tap/fill不在逻辑cells库中失败，原失败保留。retry严格确认5195个空实例只有PG LEF引脚，作可逐字恢复的signal仿真投影；不改变任何功能/二极管/clock单元及物理ODB/GDS。独立419词SAT再次通过。

问题：**根号5等于几？**。实际回答：**我无法获知实时天气。**

- 新编译61.740776700秒；新执行11token（含EOS），IDs `[67,69,84,97,90,56,71,51,82,8,4]`。
- 全部hidden/logits、逐token周期及P1/P2/P3计数与已资格候选精确一致。
- generation10060264，P3585212；配置1MHz生成10.060264秒，1.09341066994token/s。配置时钟不是物理Fmax。
- 本次宿主问答224.177018458秒，含启动进程233.381571990秒；宿主吞吐约0.049069token/s，不用于跨平台硬件性能对比。
- GPU本轮未作新电路变更，未重复已充分资格的SimX；最近真实结果仍在 runs/gpu-clean-root5-20261114-01。最终CPU/GPU物理绑定后统一公平重测仍待完成。

## 文件治理及审查

- 新CPU结束后两PCH归档逐解压SHA验证，净释放128544779bytes，最终binary不变。
- 490份历史相同MAG透明NTFSLZX压缩，全部路径/逻辑bytes/SHA不变，实际allocation释放14115812bytes；没有hardlink或删除证据。PCH净逻辑节省与NTFS物理allocation节省分项记录，不相加作工作区净减少，本轮也生成了新产物。
- 发现旧gap03回执同一channel-patch两个slash风格绑定中一项SHA过期。原回执保留，显式纠正见 reviews/d042-primary-evidence-correction/result.json；入口SHA通过不能代替递归历史资格。
- 独立审查：reviews/d042-independent；最新CPU、PG-only投影、PCH、NTFS及新增rowaddr验证见 reviews/d042-final-actual-independent。检查数是细粒度证据检查，不等于新增case数。
- 所有新增脚本、日志、HOME/TMP、缓存和归档均在实际工作区 optimization/p3 下。实际根目录为 D:/college/codex/student-mini-v1-cpu-gpu；环境所列中文目录不存在。

## 继续顺序

1. 将已验证SRAM runtime overlay绑定实际完整目标层级和坐标，证明移动channel所有端点，再做有实质差异的目标宏生成，修完整geometry/unknownlayer，完成LVS/TT。
2. bank3 PG-aware按实际signal-pin热点精确布局；bank10/14与其余16个ROM bank物理资格继续。
3. bank20实际PG抽象/导入及tap距离/endcap资格，整核CPU/GPU PG/PDN/GDS/LVS/STA/PPA/IR/EM/活动功耗。
4. 物理绑定后统一真实CPU RTL/GPU SimX问答与性能验收；保持原33×10 case合规资格，接口/数值变化时重验受影响项。

机器索引由 tools/update_current_d036.py 更新；CURRENT-INDEX-AUDIT.json记录当前入口逐SHA检查。算法既有收益为P3周期减少1.12507%、完整生成减少0.06812%，不得将本轮局部物理收口重复计为提速。
