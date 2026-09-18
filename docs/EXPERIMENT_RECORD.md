# 实验记录与结论边界

本文档把 SCAR 的实验结果分为 `Observed`、`Inferred`、`Implemented`、`Verified`、`Rejected` 和 `Proposed`，避免把猜测写成加速结果。

## 1. LeWM baseline

### Observed / Verified

- 外部 testcase：`../scar-testcases/lewm`；SCAR 核心没有 LeWM 分支。
- 运行环境使用 `conda activate lewm`，LeWM checkout 在实验前保持原状。
- 成功采集一次真实 baseline：45,894 个事件，包含 20,820 次 module call、22,457 个 CUDA kernel、543 个物理 CUDA copy、360 个 CUDA barrier；资源采样与命令返回码均写入 trace 目录。
- 该次 baseline wall-clock 约 104.85 秒；GPU 平均利用率约 1.10%，峰值约 13%，GPU memory 峰值约 1191 MiB。资源采样是低频观察，不能替代 Nsight/Kineto 的精确 kernel 时间。
- 动态图和静态链接均通过结构完整性校验。line tracing 版本约 1415 秒，只作为插桩证据，不可用于性能比较。

### Inferred

- trace 中重复的 module/operator signature 说明存在候选重复模式，但 signature 相等不等于逻辑版本、effect、consumer 和成本都相等。
- 低 GPU 利用率提示 CPU/Python/同步/数据准备可能值得继续分析，但这不是某个具体 backend 合法或有利可图的证明。

### Rejected

- 早期统一 planner 结果：1,571 `UNKNOWN`、959 `REJECT`、0 `TRANSFORM`。`UNKNOWN` 是证据不足，不是“证明没有优化机会”。
- 直接把所有重复 module call memoize 被拒绝：LeWM 含大量自定义 module、复杂状态和输出/输入别名，不能用名字或重复次数替代 contract。

## 2. 通用 micro workload

### Verified

- `@pure` exact reuse：同一输入返回等值结果，并对 cached Tensor 做独立 copy；调用方原地修改不会污染后续结果。
- 输入原地写入会改变 SCAR storage/logical guard；NumPy alias 写入即使没有 Torch `_version` 变化，也会被快速指纹/精确快照拒绝旧缓存。
- 隐藏计数器、随机操作、梯度输入、module hooks、未知对象和输出 alias 不会被当成纯函数。
- 新的两级输入守卫只在每次调用记录少量 metadata/前缀样本；完整字节 snapshot 仅在新 cache entry 建立时保存，且只有快速指纹相同时才比较。

### Implemented

- opt-in `scar optimize -- command` 使用精确的内置 `torch.nn` 类合同；首个重复 key 做原始 probe；测量到 hit 不划算时关闭该模块；未知类回退原实现。
- Torch dispatch observer 只标记 in-place/`out=` 写入；普通算子不会推进 storage epoch，避免把所有计算误报成写。

### Rejected / Not profitable

- 小型 CPU/GPU Linear micro run 证明了 cache lookup、输入守卫、输出 copy 和首次 probe 可能超过原始快速计算；成本闸门会禁用这种 backend。不能为了显示 hit 人为报告加速。
- 因此“检测到了重复”与“优化值得采用”严格分离。

## 3. LeWM opt-in backend 尝试

- **Rejected：** 第一次命令误把父进程和子进程都注入 optimizer，报告无效，已停止并标注为实验错误。
- **Rejected：** 第二次正确注入返回非零，出现大规模 fallback/缓存保留，未形成完整 episode 输出，不能作为 A/B。
- **Rejected：** 第三次在更小的每模块预算下仍显示过高 CPU/运行时间，未完成且已停止；没有把它宣称为性能结果。

截至本文档更新，LeWM 还没有可信的 SCAR optimized clean A/B speedup。下一步必须先缩小到可验证的外部 workload slice，得到 Level 1/2/3 correctness，再测无插桩 baseline/optimized median、warmup、重复次数、方差和资源证据。

## 4. 下一阶段实验门槛

一个 backend 只有同时满足以下条件，才可以进入 LeWM A/B：

1. 在通用 micro test 的正例、原地写、隐藏状态、随机性、输出 alias 中全部通过；
2. trace 中观察到对应真实动作，且输入 logical version、effect 和 consumer 证据完整；
3. Guard、lookup、额外内存和同步成本有测量值；
4. Level 1 区域结果和 Level 2 固定 solve 一致；
5. clean run 的 median 改善超过测量噪声；
6. 失败时自动回退原执行，并在 report 中保留原因。

满足前才写 `Verified speedup`。否则只写 `Proposed`、`UNKNOWN` 或 `Rejected`。
