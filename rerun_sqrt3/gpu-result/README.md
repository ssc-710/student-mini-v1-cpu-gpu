# 根号 3：实际 CPU RTL / GPU SimX 结果

问题：根号3等于几？

GPU Vortex SimX 实际生成：**我无法获知实时天气。**

```text
STUDENT_NATIVE_GPU status=0 count=11
tokens = [67,69,84,97,90,56,71,51,82,8,4]
STUDENT_NATIVE_GPU_COMPLETE count=11 p1=1 p2=10 p3=40
```

原始词表不含“根”“号”“3”，模型实际接收 `[UNK][UNK][UNK]等于几？`，带会话标记的输入 ID 为 `[1,2,5,5,5,92,16,27,111,3]`。未修改权重、词表或生成答案。这是模型在该输入下的真实错误回答，不是数学正确答案；数学上 √3 ≈ 1.7320508075688772。

与已完成的 VexRiscv CPU RTL 输出比较，11 步 token、16 维 hidden state 和每步 256 项 logits 均逐项一致。比较只涵盖日志中导出的状态，不宣称所有内部状态或完整质量门禁通过。

修复了运行器经符号链接调用 configure 导致 find 未遍历源码的问题；补齐上游锁定的 SoftFloat、Ramulator 及其指定版本依赖；本地 ICD 配置修正 PoCL 预编译包中打包机器的绝对路径。SimX 配置为 RV32、1 core、2 warps、4 threads、STD FPU，单线程设备内核完成整个自回归会话。

这是 Vortex SimX 模拟执行，不是物理 GPU，也不是 GPU RTL 验证。日志 PERF 为整个进程的模拟计数，未作为独立推理性能结论。

证据：`execute.log` 为 GPU 原始构建/运行日志，`cpu-run.log` 为 CPU RTL 原始日志，`completion.json` 保存各阶段退出码与输入/源码/二进制绑定，`result.json` 保存解码及逐项比较结果。依赖版本与下载摘要见上级 `gpu-dependencies.json`，构建日志见上级 `gpu-ramulator-build.log`。
