# SCAR 当前代码审计

状态：**2026-09-22 架构基线**

范围：`scar/ir/`、`scar/trace/`、`scar/analysis/`、`scar/planner/`、
`scar/backends/`、`scar/validate/`、CLI 与测试。

约束：本审计不增加 detector，不增加 backend，不修改 LeWM。

## 1. 结论

当前 SCAR 是一个已经能够采集真实 Python/PyTorch/CUDA 证据、重建 v1 执行图、
生成保守候选并运行少量受限 backend 的原型。它还不是能够从程序语义机械地
导出唯一修改方案的自动化简系统。

主要问题不是候选数量少，而是五段桥梁尚未连通：

```text
源码语义
  -> 运行实例
  -> 逻辑值来源与副作用闭包
  -> 可替换区域及其残留副作用
  -> 全局最优、可验证的修改计划
```

v2 已经正确地开始拆分 logical value、physical storage、operation definition
和 operation instance，但目前只是独立 schema。CLI、trace、analysis 和 planner
仍使用 v1 mixed graph。继续在 v1 上添加 detector 只会产生更多无法证明、无法
组成具体方案的候选。

因此下一阶段的主线必须是：**完成 SG/EEG/ValueGraph/OIR，并把已有证据接入
这条主线，然后实现只输出方案的通用图化简器。** 在此之前不新增 backend。

## 2. 审计方法与可复现状态

本次审计逐项阅读了：

- `docs/MODEL.md`、`PROGRAM_DECOMPOSITION.md`、
  `RESPONSIBILITY_AND_LOGIC.md`、`IR_DESIGN_V2.md`、`IR_MIGRATION.md`；
- `scar/ir/` 和 `scar/ir/v2/`；
- `scar/trace/`、`scar/analysis/`、`scar/planner/`；
- backend、validation、CLI、unit/integration tests；
- 已归档的通用测试与 LeWM evidence report。

审计时完整测试结果为：

```text
155 passed, 1 warning in 26.95s
```

warning 来自 Python 对多线程进程中 `os.fork()` 的弃用提示。它不改变测试
结果，但 fork 后 CUDA/profiler 的支持仍然只具备有限合同。

## 3. 当前能力矩阵

| 能力 | 状态 | 代码证据 | 准确含义 |
| --- | --- | --- | --- |
| v1 source coverage | Verified | `scar/ir/source.py`、`scar/ir/graph.py` | AST、物理行、保守 CFG/Name 读写；覆盖语法不等于理解语义 |
| Python/Torch trace | Verified | `scar/trace/` | call/return、module、部分 C-call、Torch profiler 和资源记录 |
| CUDA evidence | Partial | `scar/trace/cuda.py`、Kineto 记录 | kernel/memcpy/barrier/stream 可观测；并非总能绑定到逻辑值 |
| v1 mixed graph | Implemented | `ProgramGraph` | K/Σ/A/R/Q/M 投影和部分依赖；混合了静态、动态和推理命名空间 |
| proof ledger | Implemented | `scar/analysis/proofs.py`、planner | 能区分 PROVEN/DISPROVEN/UNKNOWN；尚未形成区域证明树 |
| candidate discovery | Implemented | `scar/analysis/` | 重复、物化、同步、loop 等信号；候选不是修改方案 |
| v2 value identity | Schema-only | `scar/ir/v2/values.py` | 概念和校验存在，真实 trace 尚未填充 |
| v2 semantic graph | Schema-only | `scar/ir/v2/semantic.py` | definitions/slots/control 容器存在，缺少完整 typed relations/frontend |
| v2 evidence graph | Schema-only | `scar/ir/v2/evidence.py` | instances/observations 容器存在，缺少 effect/order/memory relations |
| SG↔EEG correspondence | Absent | 无 v2 实现 | 静态定义与动态实例尚未在 v2 关联 |
| Optimization IR | Absent | 只有 `OptimizationRegionID` | 没有 region、alternative、delta、residual effect 或 plan schema |
| graph simplification | Fragmentary | constants/topdown/liveness 分离 | 没有统一规则引擎和跨层值/副作用闭包 |
| global planner | Absent | v1 selector 只做局部筛选 | 不处理 region overlap、依赖冲突、组合收益和全局计划 |
| AI-ready edit plan | Absent | 无 | 不能输出“改哪里、替换成什么、保留什么、为什么” |
| code transformation | Prototype | exact reuse/residency/dead expr | 仅少量显式合同路径，不代表通用优化器完成 |
| workload validation | Partial | `scar/validate/` | 有分层 API；真实 LeWM 变换后的 Level 2–4 尚未完成 |

状态词的含义：

- **Verified**：有实现、测试和可复查 artifact；
- **Implemented**：实现存在且有局部测试，覆盖范围受限；
- **Partial**：只覆盖模型的一部分；
- **Schema-only**：类型存在，但没有进入真实数据通路；
- **Absent**：当前代码没有该能力。

## 4. 核心图审计

### 4.1 v1 `ProgramGraph` 不是未来核心 IR

v1 graph 同时存放 source line、AST operation、dynamic action、state、resource、
contract 和 measurement。它适合把现有 evidence 汇总成可查看报告，但不能同时
承担三种不同职责：

1. 程序可能表达什么；
2. 某次运行实际发生什么；
3. 哪个边界可以被另一段程序替换。

三者的真值范围不同。静态未解析不等于运行时不存在，单次未观测也不等于所有
执行均不存在，可替换区域还需要输入、输出、状态、副作用、控制和资源边界。

### 4.2 v2 的拆分方向正确，但实现没有接通

`scar/ir/v2/` 当前只有：

- typed identities；
- `ValueGraph`；
- definitions/slots/controls 组成的 `SemanticGraph`；
- instances/observations 组成的 `EvidenceGraph`。

全仓引用审计表明，v2 目前只被自身测试和文档使用。`scar trace`、`scar analyze`、
candidate、planner、backend、validator 都没有消费 v2。

v2 还缺少：

- `SourceAtom`、package/module initialization、import/re-export/lazy attribute；
- operation 的 typed consume/produce/read/write/call/effect edges；
- dynamic read/write/materialize/alias/happens-before/effect edges；
- `ContractDefinition`、resource requirement 和 measurement binding；
- SG↔EEG correspondence；
- `OptimizationRegion`、`PlanAlternative`、`TransformDelta`、
  `ResidualEffect`、`ValidationRequest` 和 `CostRequest`。

### 4.3 正确的核心不是一张万能图

未来核心由四个相互引用、独立校验的图组成：

```text
Semantic Graph (SG)       程序结构、控制、值槽和合同
Execution Evidence (EEG)  某次运行的实例、事件和测量
Value/Provenance Graph    逻辑值、版本、来源和物理表示
Optimization IR (OIR)     可替换区域、替代方案和证明
```

每个 operation definition 和 instance 都可以沿 containment 递归展开。展开只
表示层级关系，不把 Python function、Torch op、kernel 和 memcpy 错当成同一
粒度节点。

## 5. 身份与 provenance 审计

### 5.1 当前已正确区分的概念

v2 明确区分：

```text
ObjectID
StorageAllocationID
StorageRegionID
LogicalValueID
ValueVersionID
ProvenanceID
MaterializationID
```

这能表达 allocator 地址复用、同一 allocation 的多个 view、同一逻辑版本的
CPU/GPU 副本，以及 copy/transform/mutation 的不同 provenance relation。

### 5.2 真实 trace 仍使用 storage-derived logical token

v1 trace 中的 logical version 主要从 storage token、storage epoch 和 logical
epoch 构造。这只能证明物理分配上的局部连续性，不能自然表示：

- deepcopy 后仍来自同一个逻辑来源；
- dataset raw value 经过 normalize、H2D、encode 的 provenance 链；
- 同一 Python object 被外部原地覆盖后产生的新逻辑版本；
- 不同 object/storage 在明确合同下表示同一个值；
- import literal 通过属性访问、索引和调用参数层层传递到最终 consumer。

shape 和少量前缀值适合作为低成本 guard 的第一阶段，不能生成逻辑相等证明。
只有第一阶段相等时才值得进行保留 bytes、hash 或逐元素核对；即使内容相同，
provenance 和可见副作用仍需单独证明。

### 5.3 缺少统一 registry

`constants`、`topdown`、v1 state graph 和 v2 ValueGraph 目前是四条独立路径。
没有一个 registry 把 source slot、runtime object、storage region、value version、
materialization 和 consumer 连接起来。因此 SCAR 看到“第八层输入没有变化”时，
无法机械地回溯到第三层的 origin，也无法把第三至第八层收缩成一个 composite
region。

## 6. 程序语义与副作用审计

### 6.1 source coverage 不是 semantic closure

当前 source model 能为每个物理行保留节点，并对显式语法做保守标注。它还不能
完整解释：

- import 的 module initialization、import hook、lazy attribute、re-export；
- 跨函数/方法/模块的精确 def-use、phi、exception value flow；
- descriptor、property、magic method、dynamic dispatch；
- callback 注册、全局对象图、closure escape；
- 动态生成代码和 C extension 的内部语义；
- 第三方库 operation contract。

不能解析的代码应成为有边界的 `OpaqueOperation`。这仍是“覆盖”，但其正确
化简结果通常是保留这个 boundary，或者提出明确的补充 instrumentation/contract
需求。

### 6.2 effect 不能组合

当前 effect 字段覆盖 reads/writes/allocates/frees/aliases/escapes/RNG/raise/
external/order，但普通 Python call 的完整集合通常 UNKNOWN，也没有把 child
effect 精确汇总到 composite region。

缺少以下算法：

- bottom-up effect summary；
- backward value slice 和 forward consumer closure；
- effect liveness；
- residualization：删除 value computation 时保留仍受 Q 要求的副作用；
- 读取、写入、逃逸和异常在 region boundary 上的精确投影；
- 不同 Q contract 下可见副作用的配置。

这也是 stable-pretraining 示例目前无法输出“替换值并删除 import”的直接原因：
literal value 已可静态解析，import 初始化与 lazy access 的 effect 却没有进入同一
证明和化简图，系统也没有 residual effect 计划。

## 7. tracing 与运行证据审计

当前 tracer 的主要价值应保留。已验证的 evidence source 包括 Python call/
return、部分 C-call、module hook、TorchDispatch/profiler aggregate、Kineto
kernel/memcpy/barrier、stream 和资源采样。

主要缺口是：

- C-call 普遍拿不到参数、返回值和内部 effect；
- non-Tensor object attributes、globals、module registry、callback 和环境状态
  没有通用生命周期模型；
- Python/NumPy RNG、文件、env、logging 等尚未形成统一 external state；
- autograd、grad mode 和 backward graph 不是一等实体；
- branch predicate、exception path、async task、预存在线程/进程覆盖不完整；
- 只有 same-stream 的部分顺序；cross-stream event 和 host/device happens-before
  尚未建立；
- CUDA copy 到 logical value 的关联经常依赖 shape/size signature 推理；
- 完整 line trace 成本过高，已记录 LeWM 一次运行产生 10.79 GB trace、耗时
  1415 s，不能作为默认方案。

下一阶段应该规范化现有 trace，按缺失证明按需插桩，而不是默认记录所有 Tensor
数值或所有 Python line。

## 8. detector、candidate 与 planner 审计

### 8.1 candidate 不是替换区域

当前 `Opportunity` 主要由 CodeID、supporting events、reason、backend 和若干
proof obligation 组成。它没有严格定义：

- 要替换的 region members；
- region 输入、输出、状态、控制、资源和异常边界；
- 替换前后的 value/effect 图；
- 需要删除、移动、合并或保留的 operation；
- residual effects；
- source locations 与 AI 修改指令；
- plan-specific cost/validation request。

event detector 与 graph detector 还可能对同一现象产生两个投影。常量候选则把
“值可替换”和“import 可删除”两个不同结论耦合在一个报告中。

### 8.2 planner 只做局部候选筛选

当前 cost model 基本比较：

```text
expected_savings_ns > guard_ns + lookup_ns
```

并可检查 memory budget。它没有建模 startup/steady-state、warmup/compile、variance、
memory pressure、transfer overlap、同步改变、候选组合收益和全局冲突。冲突处理
主要依据 CodeID/backend/supporting event，不能处理 region overlap、producer-
consumer 依赖或 effect ordering。

### 8.3 终态不应是裸 `UNKNOWN`

事实层必须允许 UNKNOWN，因为任意 Python 程序和开放世界环境不可能总能静态
证明。但用户可执行的计划层不能以“UNKNOWN”结束。每个分析目标必须归一化为：

```text
REWRITE     已有充分证明、成本与验证方案
KEEP        已知不合法、不盈利，或 opaque boundary 必须保留
INSTRUMENT  明确指出缺哪个事实、在哪里采集、采集后重跑哪个证明
CONTRACT    明确指出需要调用者/库提供哪个合同
```

其中 `INSTRUMENT` 和 `CONTRACT` 是具体下一步，而不是不解释原因的拒绝。所谓
“唯一最优答案”也必须相对于显式 Q/M：结果、状态、异常、RNG、日志和环境效果
哪些必须保持，以及成本目标是什么。Q/M 相同且证据相同时，planner 应使用固定
tie-break 生成确定性计划。

## 9. graph simplification 审计

当前存在 repetition、liveness、topdown placement、constant provenance 等局部
分析，但不存在统一的图化简规则引擎。以下通用能力仍缺失：

- constant propagation 和跨 import/call/index 的 path contraction；
- import/module initialization 的 effect liveness 与安全删除；
- dead subgraph elimination；
- common subexpression elimination；
- loop-invariant region motion；
- partial evaluation；
- materialization/residency/lifetime 化简；
- host materialization defer；
- allocation lifetime/buffer reuse；
- fusion、prefetch、capture/replay 的 region plan；
- 多个 rewrite 的冲突、组合和 normal form。

这些规则必须操作 OIR，并输出 proof tree 与 transform delta。不能通过检查 LeWM
函数名、包名或变量名来触发。

## 10. validation 与测试审计

### 已有基础

- nested Python/Tensor output comparison；
- caller 提供 visible state snapshot 的 Level 1–4 runner；
- exact reuse/residency/dead-expression 的正反例；
- trace smoke、thread/fork、alias/view、loop 和 proof tests。

### 缺口

- 没有自动从 OIR contract 生成 validator；
- 环境、RNG、module state、file、stream/order snapshot 依赖调用者手工提供；
- 没有 source→SG→EEG→OIR→plan 的端到端测试；
- v2 只有少量 schema fixtures，没有真实 trace normalizer 测试；
- 没有 import elimination、effect residualization、跨模块常量链、composite hoist
  的通用 golden tests；
- 没有 alias/provenance/import/dynamic Python 的 property/fuzz tests；
- 没有真实 LeWM transform 后的 Level 2–4 A/B，因此没有 LeWM 加速比。

## 11. 可保留、需重构和暂时冻结

### 保留

- raw trace 格式和已有采集器；
- CodeID/InvocationID 的基本思想；
- storage allocation/region 几何与 allocator epoch；
- K/Σ/A/R/Q/M 作为正交观察维度；
- Action multi-label；
- effect 字段及三值 evidence；
- proof ledger；
- validation levels；
- 已有 artifact 和 v1 reader。

### 重构

- mixed `ProgramGraph` → SG/EEG/ValueGraph adapters；
- storage-derived logical version → provenance registry；
- candidate → OIR region/alternative；
- local selector → global plan graph；
- isolated constants/topdown/liveness → unified simplification pipeline；
- handwritten visible-state validation → contract-derived validation request。

### 冻结

- 新 detector；
- 新 backend；
- LeWM-specific rule；
- 根据名称直接 cache/hoist/delete；
- 在 v1 candidate 上继续增加临时 proof flag。

冻结解除条件见 `NEXT_PHASE_PLAN.md` 的 Gate 7。

## 12. 对 LeWM 的当前准确结论

### Observed

- 已真实运行并采集 LeWM；最新记录的一次 instrumented run 返回码 0、
  `success_rate=100.0`、wall-clock 104.854 s；
- trace 中有 45,894 Actions 和 1,465 个 detector opportunities；
- 该次运行选择 0 个 transform；
- 另一份全项目 graph 构建记录有 834,790 nodes / 1,628,494 edges，耗时
  404.10 s、峰值 RSS 约 4.54 GiB；
- resource-sampled run 的 GPU 利用率平均 0.74%、峰值 23%，这是插桩运行证据。

### Inferred

- 低 GPU utilization 和大量 Python/control activity 表明存在值得继续追踪的
  orchestration、同步或 composite-region 机会；它们没有单独证明任何化简合法。

### Implemented

- SCAR 能收集上述证据并给出保守候选/拒绝原因；
- isolated constant pass 能解析部分 local imported literal。

### Rejected / unresolved

- 当前没有可信的 LeWM transform；
- 1,465 个候选不是“1,465 个已证明可优化点”，而是 detector 信号；
- 没有 clean baseline vs optimized LeWM，因此当前加速比为 **未测得**，不能用
  generic micro benchmark 的 4.158× 代替。

## 13. 审计后的工程原则

从本基线开始，每个新功能必须回答：

1. 它在 SG、EEG、ValueGraph、OIR 的哪个位置？
2. 输入 identity、版本、provenance 和 materialization 如何表示？
3. control、effect、resource、contract boundary 是什么？
4. 它增加的是事实、推理、候选、计划还是执行？
5. 它的 negative/counterexample 如何证明不会错误化简？
6. 终态为何是 REWRITE/KEEP/INSTRUMENT/CONTRACT？

无法回答这些问题的 detector 或 backend 不进入主线。
