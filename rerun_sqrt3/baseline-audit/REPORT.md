# CPU / GPU 六个 baseline 全量复核报告

## 结论与验证范围

2026-11-06 本轮复核确认：冻结的 100 个 case，各 seed 1–10，共 1000 组 golden；CPU 和 GPU 各 1000 条已保存的实际执行结果，全部与对应 golden 一致。共核验 2000 条记录，未抽样。

本轮实际执行了输入/golden 重新计算、原始结果逐位重比较、覆盖率与输入绑定检查、NPZ 交叉检查、协议计数器检查，以及全包校验器。**本轮没有重新运行 CPU RTL 或 GPU RTL/SimX 的 2000 个目标测试。** 结论针对工作包内的既有执行记录；不是新建环境下的全量硬件重放结论。上一轮根号 3 的 NanoChat 会话不是这 100 个算子 case 的替代证据。

## 1. 确认测试集

检查 README、SPEC、`data/golden/manifest.json`、`sources/scripts/generate_student_mini_vectors.py` 的 case_catalog，以及冻结向量和两平台记录。

| baseline | case 数 | seed | case×seed 条数 | 本轮匹配 | BF16 元素数 | 位差异 |
|---|---:|---|---:|---:|---:|---:|
| CPU P1 | 33 | 1–10 | 330 | 330 | 2320 | 0 |
| CPU P2 | 34 | 1–10 | 340 | 340 | 2160 | 0 |
| CPU P3 | 33 | 1–10 | 330 | 330 | 7840 | 0 |
| GPU P1 | 33 | 1–10 | 330 | 330 | 2320 | 0 |
| GPU P2 | 34 | 1–10 | 340 | 340 | 2160 | 0 |
| GPU P3 | 33 | 1–10 | 330 | 330 | 7840 | 0 |

P1/P3 为 MINI-01..33；P2 在相同编号范围上追加 MINI-34（two-query-maximum），没有重编号。100 个 case 是三个算子合计，不是每个算子 100 个。1000 组 golden 由 CPU/GPU 共用，不是六个 baseline 各 1000 组。

## 2. 输入与 golden 完整性及重生成

检查 golden 文件 SHA-256 与 manifest 一致，并核对生成器、spec、rtl_oracle、numeric 四个源文件的锁定摘要。检查 case_catalog 与 manifest 完全一致；case/seed 无重复、无缺失；每个 case 恰好包含 seed 1..10。

对全部 1000 条调用原始 `numeric_inputs(case, seed)` 重建输入，并调用原始 `golden(case, inputs)` 重新计算预期结果。输入对象和整个 golden 对象均与冻结版本一致：1000/1000。

这是按锁定数值合同重算，不是另写一个全新数学参考模型；也不证明该数值合同等同于无限精度浮点语义。生成 golden 不视为硬件执行。

环境：WSL Ubuntu-24.04，Python 3.12.3，NumPy 2.3.5，ml_dtypes 0.5.4。详见 `golden-regeneration.json`。

## 3. 独立重新比较实际结果

新建 `../audit_baselines.py`，没有直接相信原报告的 PASS。分别读取 `data/records/cpu.jsonl` 和 `gpu.jsonl` 的 observation，按 case_id/seed 关联冻结向量，检查：

- 1000 条记录、1000 个唯一 case/seed、ordinal 0..999 恰好各一次。
- case、seed、ordinal、PRNG、平台标识（若提供）和输入 JSON 的 SHA-256。
- 记录携带的 golden 与冻结 golden 一致。
- actual_status 与 expected_status 完全一致。
- actual_bits 与 output_bits 的数组长度和每个 uint16 BF16 位模式完全一致，零容差。
- 从原始位模式解码浮点值；核对 golden_values、已提供的 actual_values；计算逐元素差值。
- P1 的 selected token IDs；primitive witness 的整数结果。
- expected_events 全覆盖、missing_events 为空，并检查原记录 PASS 和比较字段与重算相容。

结果：2000/2000 匹配，两个平台各 12,320 个 BF16 输出元素，合计 24,640 个元素，位差异 0，最大绝对误差 0。每个平台 P1 的 260 条有效选择结果匹配；每个算子各 60 条 primitive witness 匹配。CPU/GPU 对同一组 case/seed 的状态与输出位模式也全部相同：1000/1000。

完整结果见 `audit.json`；逐条明细见 `records.csv`（2000 行）；逐 case 的全部 seed 覆盖见 `cases.json`（200 组 platform/case）；全部检查见 `checks.json`。

## 4. 非法输入与错误用例不能当成普通数值输出

每个平台均为以下分布：

| 算子 | OK（有数值输出） | 预期错误状态 | 合计 |
|---|---:|---|---:|
| P1 | 260 | BAD_LENGTH 10；NUMERIC_ERROR 50；BUS_ERROR 10 | 330 |
| P2 | 260 | BAD_LENGTH 10；BAD_DESCRIPTOR 10；NUMERIC_ERROR 50；BUS_ERROR 10 | 340 |
| P3 | 250 | BAD_DESCRIPTOR 20；NUMERIC_ERROR 50；BUS_ERROR 10 | 330 |

所以“1000 条通过”不是说 1000 条都应返回 OK：每个平台有 770 条正常输出、230 条预期错误。错误状态必须正确，输出数组必须与 golden 同为空；不能跳过这些用例，也不能将正确报错视为测试失败。

## 5. 格式差异与协议/数组交叉检查

初版额外审计曾把 protocol observation 中可选的重复 platform/actual 字段当作必需字段，误报 180 条元数据格式问题；其中 CPU 的 90 条协议记录没有浮点 actual。检查实际记录和原生产脚本后修正：外层 platform 仍必须匹配；内层 platform 若存在就必须匹配；actual 若存在就必须与 bits 解码一致；原始 actual_bits 始终必需且逐位检查。没有改动任何 golden 或 observation，也没有增加数值容差。保留初版摘要 `initial-schema-check.json`，其中的 180 项是检查器格式误报，不是算子输出不一致；最终 `audit.json` 的 issue_count 为 0。

另运行 `../audit_baseline_arrays.py`，对两个 NPZ 的 1000 行检查 ordinal、seed、length、golden_bits、actual_bits 与 JSONL 一致，signed_delta 为 0。

对每个平台的 90 条 MINI-31/32/33 协议记录，检查保存的原始计数器：CPU completion=1、无稳定性违例、背压/保持确实产生 stalled_cycles，reset 前无 completion、reset 时序有效、重发 payload_match=1；GPU 无稳定性违例、commands/responses 一致、背压请求/响应均停顿、hold 周期数正确、reset/reissue 计数有效。检查标准参照包内 CPU/GPU 协议生成/汇编脚本。

NPZ 与协议交叉检查合计 2182 项，全部通过，见 `arrays-and-protocol.json`。它只复核包装后的计数器，不声称本轮重新观察了 RTL 波形或重做所有性能计数器类别的原始运行。

既有记录标注的后端：CPU 普通记录 vexriscv-rtl（910 条）及 cpu-protocol-run（90 条）；GPU 普通记录 vortex-rtlsim-mapped-core-fault-adapters（910 条）及 gpu-protocol-run（90 条）。这些不是上一轮 NanoChat 的 SimX 记录。

## 6. 全包校验和已知完整性差异

分别在 Windows Python 和 WSL Python 执行原始 `verify_release.py`。两次结果一致：CPU 1000 PASS，GPU 1000 PASS；2572 个 evidence 文件、1145 个 alias、480 个 power/netlist/SPEF 绑定完成检查，missing/omitted 为 0。

但退出码为 1，唯一问题：`manifest mismatch: sources/scripts/run_student_mini_native_gpu.py`。这是上一轮为修复 GPU 构建路径、依赖绑定和本地 ICD 环境而修改的脚本。没有回写原始 MANIFEST、没有将全包完整性宣称为通过。记录和 golden 本身的摘要匹配原清单。

发布状态仍是 `PARTIAL_NOT_RELEASED`；本次算子结果复核不会改变资源限制、一小时目标等发布门。完整 stdout 见 `verify-release.stdout.json`，stderr 为空。

关键文件 SHA-256：

```text
golden vectors b96fc48dc57b6792203c39682dc08c51c65187f03c2e8f54444f32892858b974
CPU records    36496672bc181855d15a173238ec16e396ec007013a340e1aa9fcc6f953aa6f6
GPU records    bfb03b3df6b760b400818af8f890701462e971d2e7ecbe38c715cb97925a8fee
```

## 7. 复现命令

从 WSL 运行（路径中的 ROOT 替换为当前工作包的实际路径）：

```text
ROOT/rerun_sqrt3/cpu-venv/bin/python ROOT/rerun_sqrt3/audit_baselines.py
ROOT/rerun_sqrt3/cpu-venv/bin/python ROOT/rerun_sqrt3/audit_baseline_arrays.py
python3 ROOT/verify_release.py
```

前两项最终通过；第三项因上述已披露的 runner 修改返回 1。审计输出仅写入 `rerun_sqrt3/baseline-audit`，未改动冻结测试数据、既有执行结果、原报告或发布清单。
