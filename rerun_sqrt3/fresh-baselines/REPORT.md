# 本轮实际 CPU RTL / GPU SimX 全量重跑

日期：2026-11-06。不是历史 observation 的重比较，也不是主机运行算子代替目标执行。

## 结果

| 目标 | 算子 | case × seed | 状态、输出位模式、选择及 primitive 全匹配 |
|---|---|---:|---:|
| VexRiscv RTL | P1 | 33 × 10 | 330/330 |
| VexRiscv RTL | P2 | 34 × 10 | 340/340 |
| VexRiscv RTL | P3 | 33 × 10 | 330/330 |
| Vortex SimX | P1 | 33 × 10 | 320/330 |
| Vortex SimX | P2 | 34 × 10 | 330/340 |
| Vortex SimX | P3 | 33 × 10 | 320/330 |

CPU 1000/1000 一致。GPU 970/1000 一致；P1/P2/P3-MINI-30 各 seed 1–10 共 30 条，golden 要求 BUS_ERROR，普通 SimX scalar 路径实际返回 UNSUPPORTED_BUS_INJECTION。未伪造 BUS_ERROR，未用历史 RTL observation 补齐。

两目标全部正常数值输出均与冻结 golden 逐 BF16 位模式一致；非法描述符、非法长度、非法数值尺度等其他预期错误状态也一致。GPU 差异是缺少真实总线错误注入能力，不是正常算子数值误差。

## 实际过程

1. 从冻结 `data/golden/vectors.jsonl` 读取 1000 组记录，用原始 `export_student_mini_input.encode` 仅序列化 inputs，形成 1,936,000 字节 inputs.bin；目标镜像不含 expected 输出。manifest 保存输入及原始算子源码 SHA。
2. GPU 使用原始 `prepare_student_mini_gpu.prepare` 投影原 scalar 算子到设备代码，使用上一轮已成功构建的 Vortex RV32、1 core、2 warps、4 threads、STD FPU 运行库；本轮新编译 student_mini 程序，在 SimX 上一个设备 launch 执行全部 1000 blocks。输入来自本轮 inputs.bin，主机仅拷贝数据与打印结果。
3. GPU 中途出现 CP 暂时无进展警告，但随后正常完成，退出码 0。`gpu-execute.log` 包含 1000 条唯一结果及 `STUDENT_GPU_COMPLETE start=0 count=1000`。曾启动10组一批的诊断，原整批完成后停止重复批次；诊断结果不用于拼接或补齐最终1000条。
4. CPU 首次构建失败：原 BIOS Makefile 引用了工作包不存在的历史 nano_control_smoke.c 等源文件。日志保留为 cpu-build.log。创建独立 baseline_bios/Makefile，复用锁定 LiteX upstream BIOS，只链接原始 student_mini_session.c、student_mini_scalar.c、operator_scalar.c，不修改算子实现。
5. 在 ASCII 路径 `/mnt/d/sqrt3-rerun/baselines-cpu` 完成真实 VexRiscv Full_4k RTL 的固件、Verilator 构建。第二次构建日志 cpu-build-attempt2.log。使用系统 RISC-V 工具链的 RV32 构建标志，未宣称预编译 RV32 工具链替代了实际使用的工具。
6. 实际运行新 Vsim，UART 输出保存到 cpu-console.log。正常 DMA 校准为 `STUDENT_CPU_DMA_PROBE status=0 bytes=0:64`。MINI-30 由固件对 RTL DMA 桥发起非法地址访问，实际返回 status=5，故障 DMA 计数16字节。不是在主机将 unsupported 状态改为预期错误。
7. CPU 输出 `STUDENT_CPU_COMPLETE count=1000` 后主动停止长期运行的 BIOS 模拟器。cpu-run-receipt.json 保存停止原因、耗时、模拟器/input/console 摘要；负的进程退出码对应完成后的主动终止，不是测试失败。
8. 通过原始 CPU/GPU transcript parser 检查唯一 ordinal 0..999 和严格完成标记，再调用原始 release_records.compare，逐条检查状态、BF16 位模式、P1 selected IDs 和 primitive witness。比较发生于设备完成后，golden 不送入目标执行。完整 observation 和 comparison 分别存于 cpu-results.json、gpu-results.json，汇总 comparison.json。

## 验证边界

- 已实际重跑100个case各10个seed，两平台各1000条，并未抽样。
- CPU 是原始 Full_4k 核及 LiteX SoC 的 RTL 仿真；不是之前发布包25-bank物理映射后网表的重放，不据此宣称物理映射签核。
- GPU 是 SimX，不是本轮 GPU RTL 仿真，也不是物理 GPU。
- MINI-31/32/33 的算子状态/数值在本轮普通执行中匹配；专项背压、响应保持、复位重发尚未施加重跑。因此不宣称六个baseline完整协议资格通过。
- GPU 的30条真实bus-fault用例尚未通过，需具备错误响应/状态寄存器适配器的GPU RTL路径单独运行。不能只修改scalar代码返回BUS_ERROR来“修复”。
- 没有改动冻结golden、已有data/records或发布清单。历史RTL结果1000/1000与本轮SimX970/1000并不矛盾：两者目标适配器覆盖不同。

关键复现入口：上级 rerun_baselines.py（首次构建/整批GPU）、build_baseline_cpu.py（CPU重试）、run_baseline_cpu_sim.py（RTL执行与完成检测）、check_fresh_baselines.py（严格比较）。如要再次独立重跑，应使用新的输出目录，不能覆盖本次日志；初始入口的exist_ok=False用于防止覆盖。
