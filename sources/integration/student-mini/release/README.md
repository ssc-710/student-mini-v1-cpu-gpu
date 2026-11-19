# student-mini-v1 三平台最小 baseline 工作包

本包是 `student-mini-v1` 的白名单交付：CPU（VexRiscv RV32IM）、GPU（Vortex 1 core / 2 warps / 4 threads）、
专用加速器 × P1/P2/P3 共九个 baseline 的全部输入、golden、实际执行结果、逐元素差值、事件、
五份物理实现证据、逐 seed 功耗、三平台 NanoChat 会话、受限资源运行记录和 SPEC。

**发布状态以 `release.json` 为准**（`COMPLETE` 或 `PARTIAL_NOT_RELEASED`，并列出每个发布门）。
一小时目标的计时起点、实际耗时与是否达成同样写在 `release.json` 中；超时如实报告为未达成。

## 查看

- 打开 `report.html`（离线单文件，无需网络）：九个 baseline 汇总 → 每个 case → 每个 seed 的输入、
  golden 位模式/数值、actual 位模式/数值、signed delta、事件证据与计数器。
- 原始数据：`data/records/<platform>.jsonl`（逐记录 JSON）、`data/arrays/<platform>.npz`（位模式与 delta 数组）、
  `data/summary/*.csv`（case、baseline、逐 seed 功耗）、`data/golden/vectors.jsonl`（冻结输入与 golden）。

## 校验（无需 EDA 工具，仅需 Python 3 标准库）

```bash
python3 verify_release.py
```

它逐文件核对 `MANIFEST.sha256`，并从原始 BF16 位模式独立重新比较每条记录与 golden。

## 内容边界

- 功耗：SKY130HD tt 25 °C 1.8 V，100 MHz；活动来自布线后网表本身的逐周期重放（与 RTL 端口逐周期比对），
  寄生参数来自最终 SPEF。不含板级、主机、外部 DRAM 功耗。
- CPU/GPU 的 P1/P2/P3 共享同一物理网表，但每个算子、每个 seed 的功耗各自由其负载活动计算。
- 协议用例（MINI-31/32/33）在各平台真实的握手接口上施加：加速器为 DMA/命令接口；GPU 为存储器请求/响应与主机响应；
  CPU 为 UART 结果流与 `asic_reset_i`（DFI 为固定时延接口，无握手）。具体映射见 `SPEC.json` 的 `protocol_interfaces`。
- 不包含：软件安装包、Python 环境、容器镜像、编译缓存、中间 ODB、训练优化器状态。依赖通过
  `sources/third_party/sources.lock.json` 锁定安装。

## 重跑

安装依赖后（`sources/scripts/install_and_run_p1_p4.sh`），各阶段入口脚本位于 `sources/scripts/`，
其输入/输出 SHA 绑定记录在各阶段证据中；所有重跑均在 2 vCPU / 8 GiB 限制下执行
（`sources/scripts/student_mini_resource_guard.py`）。
