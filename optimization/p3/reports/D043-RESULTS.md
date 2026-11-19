# D043 暂停检查点（2026-11-19）

用户明确要求暂停，已中断三个子智能体，停止继续优化。核查 WSL 进程列表无本任务 OpenROAD/Magic/Netgen/Yosys/仿真进程；主线程全部会话已结束。整体仍为 HOLD_NOT_FINAL_ACCEPTANCE。

## 本轮已完成

- bank16/17/19：原203.765um die、pad2、平台14um tap 优先于 placement/PDN 的真实详细布线、天线、电气、driver、显式 loaded-SPEF STA 和完整512地址 SAT 通过。bank18 generic FAIL 保留；专项证实 data15/data31 全512词为0且实际 tieLO 驱动，专项 STA/SAT 通过。
- bank16 原完整GDS实际 DRC1、LVS FAIL 保留。实际 foundry leaf DRC 定位 a2111oi_0 内部 licon.8a；_1/_2 DRC0。六个 a21oi_2 在实际 routed.v 中确认，旧“没有实例”判断为错误检索，不沿用。
- bank16 真实替换六个 a21oi_2→_4、一个 a2111oi_0→_1；不改 PDK/CDL。新 route74.331939346s，DRC0/天线0；功能面积6257→6309um²（+52）。新512SAT、2234输入/32输出driver、电气0、setup+4.19ns/hold+2.74ns/TNS0。
- 新最终 filler 版本已重新提取 SPEF/读回 STA、driver及完整512SAT PASS；不能借用填充前结果。新完整原厂GDS（437structures、无maglef）DRC0/未知层0，提取56.5440685s，器件LVS776devices/785nets两边唯一匹配。

## 限制与剩余门

没有新增端到端提速证据，也没有本轮新CPU/GPU问答。保留生产CPU generation10060264、P3585212；相对g2d4减少0.06812%/1.12507%。模型、词表、LUT、golden不变。

bank16新候选尚缺独立终态审查、全部PG端子绑定及tap/endcap工艺资格、抽象和CPU集成回放；其他小bank尚缺fullGDS/LVS。bank3新热点布局、SRAM真实target generator绑定子任务被暂停，目录未找到d043终态产物，不能记为完成；需下次核实agent交接及真实文件。整核CPU/GPU PG/PDN/GDS/LVS/STA/PPA/活动功耗与最终公平真实RTL/SimX问答仍未完成。

## 续跑顺序

1. 恢复独立 reviewer 和资深工程师子任务；先独立复核bank16新finalfilled/fullGDS/LVS及bank17/18/19的PG/SAT，校正证据字段（填充前qualification的outputs计数字段被文件SHA字典覆盖，32输出实际在driver.log；最终filled用outputs_checked保留）。
2. bank16 finalfilled PG端子/工艺与TTLIB/LEF抽象后接回CPU实际RTL；批量推进其余小bank完整GDS/LVS，保留所有旧FAIL。
3. bank3依据PG-aware真实pin热点修布局；SRAM将已有runtime overlay绑定真实80x64层级，先证明命中和端点再做有差异fullgeometry/LVS/TT；禁止重复无差异昂贵生成。
4. 完成剩余bank/整核物理后统一新RTL/SimX root5问答，记录token流、tokens/s和问答总时长。局部slack不可转授整核Fmax。
5. 清理：本轮未进行新增删除/压缩，不声称净释放空间。新GDS产生的重复MAG待确认无活动依赖后透明压缩并逐SHA记录，保留参考、源码、最终binary、失败证据。所有新文档/home/tmp/cache均在实际工作区D:/college/codex/student-mini-v1-cpu-gpu/optimization/p3。

## 关键入口

- physical/cpu-signedbias-small-pgaware-d043-20261119-01/bank-{16,17,18,19}/result.json
- physical/cpu-signedbias-small-pgaware-d043-20261119-01/bank-18/constant-output-validation-retry1/result.json
- physical/cpu-signedbias-bank16-viewcompatible-d043-20261119-01/{result.json,qualification/result.json}
- physical/cpu-signedbias-bank16-viewcompatible-filled-d043-20261119-01/qualification/result.json
- physical/cpu-signedbias-bank16-viewcompatible-fullgds-d043-20261119-01/result.json
- reviews/d043-bank16-redesign-fullgds/native-lvs/result.json
- reviews/d043-bank16-replacement-geometry/result.json

已结束会话：50204重设计、95829局部资格、9037完整GDS/LVS、58432最终填充资格；不可下次当活动任务继续轮询。独立agent中断时仅交接意见，未完成新的终态审查，不计PASS。
