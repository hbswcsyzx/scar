# 有限同步模型实现与源码压力验收

日期：2026-10-16。判定：**声明的有限组件通过；完整 N2、整体程序模型和 LeWM
全过程建图未通过。** 本报告不授予新的优化权限。

## 1. 冻结实现与自动执行证据

- revision：`dcd498699e0cd1331cf496158b29575c3fc2c536`。
- source fingerprint：`bf7ccd18b51b843c53b6b49f290c5f7368c397f394209991eb1f13a1f313bf05`，335 文件。
- 环境：conda `lewm`，CPython 3.14.7。source/raw/目标仓库保持不变。
- 组件：**290 passed，35.787s**，包含新行为与已有接口/兼容检查，不是 290 项全新能力。
- 全仓：**2,657 passed，0 failed/error/skipped，414.870s**，峰值 RSS 1,030,244 KiB。
  部分任务并行；该时间是验收成本，不是性能 benchmark。

命令、JUnit、逐案例与 source before/after 在归档中：

- [组件报告](../artifacts/experiments/b1_call_operands/structured_model_component/report.json)
- [全仓报告](../artifacts/experiments/b1_call_operands/structured_model_full_regression/report.json)
- [独立 builder 审查](../artifacts/experiments/b1_call_operands/model_connection_audit/structured_builder_review.md)

本轮只归档已有结果，没有为文档改动重跑整仓测试。

## 2. 实际覆盖的模型部分

| 已实现范围 | 相应证据 | 仍不证明 |
| --- | --- | --- |
| typed LocalBindingValue、BOUND/UNBOUND/合流规则 | binding 正反例、codec/validator。 | 完整 heap/cell/global 版本模型。 |
| if、while/for、零次/回边、break/continue/else | 独立 CFG 执行 oracle 对照实际 Python；嵌套控制目标篡改拒绝。 | 全部 Python 控制与异常清理。 |
| 普通同步表达式/调用与有序 Uses | source replay、提前 unbound 不执行后续参数、重复参数。 | 动态 callee、环境、完整 effects。 |
| iterator 临时生命周期接口 | hold/release 显式 uses、结构校验。 | 精确 RC/GC/finalizer/traceback 时序。 |
| public structured profile | CLI 构建/重放、plain/gzip、旧版本与源漂移拒绝。 | 全程序 inventory 已接入该 profile。 |

确定 UNBOUND 的 INVOKE 可以保留结构 normal 端口，但该边不可行；查询/oracle
必须按 binding facts 排除。静态边存在不等于一次正常读取发生。

## 3. 原始 LeWM 源码压力：固定 256 候选

这是**不执行目标程序**的源码压力测试。旧 v6 inventory 仅作为固定候选索引，
按原有文件/定义顺序取全部 256 个已尝试函数体；没有业务名选择或手工函数名单。
整个项目有更多定义，不能以 256 作为全过程覆盖分母。

| 项 | 实测结果 |
| --- | --- |
| 源码/定义身份 | 256/256 校验成功。 |
| 单次准备 | 70 个文件，每文件 prepare 一次。 |
| 函数体结果 | 旧 50 LOWERED_WITH_GAPS / 206 UNSUPPORTED；新 51 GRAPH_WITH_GAPS / 205 UNSUPPORTED。 |
| 源 Call | 1,591 个；严格 core-covered 旧 76、新 77。 |
| 有序输入端点 | 旧 251、新 254；保留每个 Call 的 Use/subtree 来源条件。 |
| 构造预算 | 总计收费 5,592/50,000 ops；单体 10,000；没有预算阻断。 |
| 分析成本 | 209.77s；进程 lifetime 高水位 RSS 2,371,520 KiB，before/after 相同，不当作单独 lower 阶段峰值。 |
| 源码不变性 | LeWM Git clean、574 个 tracked Python hash 与 SCAR fingerprint 前后相同。 |

唯一从 unsupported 得到图的案例包含一个循环；这里只作结果定位，不将其名称
变成规则。runtime target、effects 和 transformation authority 均为 false。
真实缺口主要仍是 unsupported 构造及跨层协议，不能声称已完成“全面建模”。

有效正式批次是 [attempt-005/report.json](../artifacts/experiments/b1_call_operands/structured_model_source_stress/attempt-005/report.json)，
SHA256 `7b6baa241633f8368fd6ced1d6a4e3aafcfd3a7fe5c4f01d1e6a7dac7bae6131`。
driver、preflight、命令、终态及逐项结果均在同目录。

前置失败原样保留：tuple unpack、旧 codec 误用、Use 字段假设和 iterator 反转
等均是验证脚本错误，**不计为 SCAR unsupported 或合法性拒绝**。
attempt-001 虽 exit 0，验收无效；attempt-002 是终止的无效批次。attempt-000/001
没有精确冻结当时完整 driver 源文，不能事后补造；后续批次有独立快照。失败
不覆盖成功结果，也不从历史删除。

## 4. 门的判定与下一步

旧 N2 计划中 binding/同步 loop 的有限组成部分有证据；G2 普遍结构保留、G3
全程序 profile/inventory 接通、G4—G6 全过程依赖和化简均未完成。不能把组件
PASS 改写为父门 PASS。

当前优先级由 [整体模型计划](WHOLE_PROGRAM_MODEL_PLAN.md)接管：先冻结一致
规格，再落实规范类型/逐构造协议，之后才补全自动图。当前没有 LeWM 自动
变换和 clean A/B 加速比，不将源码分析时间作为运行性能。
