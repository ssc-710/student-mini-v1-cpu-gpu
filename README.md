# student-mini-v1-cpu-gpu：CPU + GPU 课程最小 baseline 工作包

本包是 `student-mini-v1` 中 **CPU + GPU** 课程（`SPEC.json` 的 route B）的白名单交付：
CPU（VexRiscv RV32IM）与 GPU（Vortex）× P1/P2/P3 共 **六个 baseline** 的全部输入、golden、实际执行结果、
逐元素差值、事件、**两份物理实现**证据（CPU 顶层 + 25 个硬化 ROM bank；GPU 层次化实现 = 顶层 + 4 个硬化象限
block q0_LL/q1_LR/q2_UL/q3_UR，时序以拼装后网表的全芯片 STA 签核，附分区）、逐 seed 功耗、CPU 与 GPU 的
NanoChat 会话、受限资源运行记录和 SPEC。

**专用加速器不属于本课程。** 加速器 P1/P2/P3 的 baseline、物理实现、功耗和 NanoChat 会话属于另一门
**CPU + 专用加速器** 课程（route A），在该课程的工作包中交付；本包中加速器既不是“缺失”，也不是“PASS”。

**发布状态以 `release.json` 为准**（`COMPLETE` 或 `PARTIAL_NOT_RELEASED`，列出每个发布门、
`course`（包含的平台与实现）以及 `disclosures`（全部 HOLD 与披露事项及其真实原因））。
一小时目标的计时起点、实际耗时与是否达成写在 `release.json` 的 `one_hour` 中；该目标**未达成**，如实报告。

## 查看

- 打开 `report.html`（离线单文件，无需网络）：六个 baseline 汇总 → 每个 case → 每个 seed 的输入、
  golden 位模式/数值、actual 位模式/数值、signed delta、事件证据与计数器。
- 原始数据：`data/records/{cpu,gpu}.jsonl`、`data/arrays/{cpu,gpu}.npz`、
  `data/summary/*.csv`（case、baseline、逐 seed 功耗）、`data/golden/vectors.jsonl`（冻结输入与 golden）。
- 物理实现：`physical/cpu/top`、`physical/cpu/rom-bank-00..24`；`physical/gpu/top`、
  `physical/gpu/vortex_physical_top_q0..q3`（4 个象限 block；以 `--eco-from` 续跑的 block 附 `eco-from/` 前序运行与
  `eco-context/` 芯片时序上下文 SDC）、`physical/gpu/fullchip-sta`、`physical/gpu/partition`。
- 四层候选结构：`data/candidates.json`（runtime/algorithm/microarchitecture/physical，全部 `NOT_RUN`，无 PROMOTE）。
- NanoChat：`data/nano/sessions.json`（12 个冻结测试问题 × CPU/GPU，逐 token 对比），`data/nano/model-card.json`（模型卡）。
- 资源：`data/resources/`（每个受限任务的 guard 记录：2 vCPU / 8 GiB、峰值内存、耗时；`resource-measurements.json`
  为软件依赖与重建临时空间的单独实测）。

## 校验（无需 EDA 工具，仅需 Python 3 标准库）

```bash
python3 verify_release.py
```

它逐文件核对 `MANIFEST.sha256` 与 `evidence-index.json`（含 gzip 前 SHA-256 及功耗记录与网表/SPEF 的绑定，
GPU 功耗记录同时绑定顶层与每个 block 的网表/SPEF），并从原始 BF16 位模式独立重新比较每条记录与 golden；
课程包只检查本课程平台，并确认不含被排除平台的记录。

## 内容边界

- 功耗：SKY130HD tt 25 °C 1.8 V，100 MHz；活动来自布线后网表本身的逐周期重放（与 RTL 端口逐周期比对），
  寄生参数来自最终 SPEF。GPU 为核心 die（顶层 + 4 个象限 block），不含主机、外部 DRAM 与板级功耗；
  OpenRAM 宏的访问能量因其模型无有效表征而不计入（保留宏漏电与引脚电容，并报告逐宏访问次数）。
- CPU 与 GPU 的 P1/P2/P3 各自共享同一物理网表，但每个算子、每个 seed 的功耗各自由其负载活动计算。
- 协议用例（MINI-31/32/33）在各平台真实的握手接口上施加：GPU 为 `vortex_physical_top` 的存储请求/响应端口与
  主机命令响应；CPU 为 UART 结果流与 `asic_reset_i`（DFI 为固定时延接口，无握手）。具体映射见 `SPEC.json` 的
  `protocol_interfaces`。
- 不包含：软件安装包、Python 环境、容器镜像、编译缓存、中间 ODB、训练优化器状态。依赖通过
  `sources/third_party/sources.lock.json`、`sources/requirements-lock.txt`、`sources/requirements-bootstrap-lock.txt`
  与 `sources/sbom.spdx.json` 锁定；OpenROAD 补丁见 `sources/third_party/patches/`。

## 重跑

安装依赖后（`sources/scripts/install_and_run_p1_p4.sh`），各阶段入口脚本位于 `sources/scripts/`，
其输入/输出 SHA 绑定记录在各阶段证据中；所有重跑均在 2 vCPU / 8 GiB 限制下执行
（`sources/scripts/student_mini_resource_guard.py`）。
