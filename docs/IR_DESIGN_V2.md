# SCAR IR v2：面向语义的程序执行世界模型

状态：**架构审查提案**。

本文不增加 detector，不增加 optimization backend，也不承诺当前代码已经
实现 v2。它回答一个更基础的问题：SCAR 要在未来覆盖重复计算、重复解析、
materialization、buffer、prefetch、fusion、capture/replay、KV/cache、循环
不变量和收敛提前终止，应该把程序和执行表示成什么。

## 1. 审查结论

当前 SCAR 的 K / Σ / A / R / Q / M 六维划分是有用的观察坐标，但不是足够
强的核心 IR。当前 `ProgramGraph` 同时承载了：

- 静态 AST 和源码行覆盖；
- 动态调用和 profiler event；
- Tensor object、storage、region 和 logical version；
- control、contract、resource、measurement 的辅助节点；
- detector 为某种优化构造的候选证据。

这使 v0.1 能够记录证据和拒绝不安全的 reuse，但有四个结构性缺口：

1. **Action 不是稳定的优化单位。** 一个 `module_call`、一个 kernel launch
   和一个 composite CEM solve 都可能代表不同层级的工作。Action 更接近一次
   发生的动作或标签，不能同时承担操作定义、调用实例和可替换区域三种语义。
2. **Storage-based LogicalVersion 不够。** Storage 是物理分配，不能代表
   “goal image”“observation”“embedding”这样的逻辑值。deepcopy、view、
   cast、normalize、H2D 和 in-place update 会把逻辑身份、内容来源、版本和
   物理副本混在一起。
3. **静态图和动态图的证据等级不同。** 静态 AST 可以证明语法结构，不能证明
   runtime effect；动态 trace 可以证明一次发生，不能证明未观测分支不存在。
   两者应该通过 correspondence 关联，不能简单 merge 成一个事实集合。
4. **Evidence graph 不能直接当 Optimization IR。** 原始事件需要保留，不应
   被 planner 改写；优化需要边界、输入输出接口、合同、守卫、失效条件、成本
   和验证层级，这些应形成单独的 Optimization IR。

因此 v2 的核心不是“把更多标签加到 `GraphNode`”，而是建立三个互相连接
但职责不同的图。

```text
Program source / library contract
             │
             ▼
      Semantic Graph (SG)
             │ correspondence
             ▼
  Execution Evidence Graph (EEG)
             │ normalization + proof references
             ▼
      Optimization IR (OIR)
             │
             ▼
       Plan alternatives
```

原始 evidence 是唯一的事实来源。Semantic Graph 和 Optimization IR 都必须
保留 provenance、evidence status 和 UNKNOWN，不能因为 projection 或 pattern
match 而升级证据。

## 2. 基本原则

### 2.1 身份、相等、来源、表示、版本分开

“同一个东西”至少有五种含义：

1. 是同一个 Python object；
2. 使用同一块 storage；
3. 是同一个逻辑值的同一个版本；
4. 由同一个来源通过某种变换得到；
5. 在某个合同下数值或语义等价。

它们不能用一个 Tensor ID 或一个 hash 代替。任何合并都必须有明确的
relation 和 evidence。

### 2.2 Operation 是定义，Instance 是发生，Region 是替换单位

`OperationDefinition` 描述“这类操作是什么”；`OperationInstance` 描述一次
真实执行；`OptimizationRegion` 描述一组可以作为整体替换、移动、保留或提前
终止的操作。一个定义可以有很多 instance，一个 region 可以包含多个定义和
多个 instance。

### 2.3 Data 是一等实体

数据不是挂在 Action 上的一组字典。数据有自己的逻辑身份、版本、来源、物理
表示和生命周期；操作通过端口读取、产生、更新或暴露数据。

### 2.4 Control 独立于 Operation label

调用、分支、循环、异常、线程、进程、stream、wait 和 callback 的关系不能
只用 `CTRL` 标签表示。Control 是独立的 context/region 和 ordering relation，
可以约束 OperationRegion 的合法替换边界。

### 2.5 证据是追加的，推理是有来源的

Execution Evidence Graph 只追加观察到的事实。推理结果必须带：

```text
provenance
confidence
scope
assumptions
evidence references
```

空集合加 UNKNOWN completeness 不等于没有 effect。没有观察到 consumer 也不
等于没有 consumer。

### 2.6 每个节点都可以递归展开，但展开不是事实合并

OperationDefinition 有静态 children；OperationInstance 有动态 children；
OptimizationRegion 有 region members。递归展开只沿明确的 containment 或
control relation 进行，并保留子节点的独立 identity。展开一个函数不会把
内部所有操作伪装成一次 function call。

## 3. 三种图的严格定义

## 3.1 Semantic Graph（SG）

Semantic Graph 描述程序在源代码、库合同和显式用户合同下**表达的结构**。
它不声称某条分支已经执行，也不把静态 syntax hint 当成物理 runtime fact。

### SG 节点

| 节点 | 含义 |
| --- | --- |
| `Program` / `Package` / `Module` | 程序和模块边界、版本、import scope |
| `OperationDefinition` | 稳定的广义 function/op 定义，包含 Python function、method、module forward、operator、copy、allocation、branch、loop、kernel contract 或 opaque call |
| `ValueSlot` | 函数参数、返回值、局部变量、module field、dict key 等语义端口 |
| `LogicalValue` | 一个逻辑值 lineage 的身份，不绑定 object 或 storage |
| `ControlRegion` | function body、branch、loop、exception、callback、thread/process/stream scope |
| `ContractDefinition` | 输入输出、effect、异常、RNG、精度、顺序和可见副作用要求 |
| `ResourceRequirement` | 对 CPU/GPU/DRAM/HBM/stream/thread/file 等资源的静态约束 |
| `SourceAtom` | 物理源码行/表达式覆盖索引；用于保证任意代码都有分类，不是唯一优化单位 |

### SG 边

```text
contains_definition
contains_operation
contains_value_slot
reads_slot
writes_slot
produces_logical_value
consumes_logical_value
controls
guarded_by
may_raise_to
calls_definition
requires_resource
has_contract
source_contains
```

SG 的 `reads_slot` 是静态或合同证据，不等于已经知道运行时读到了哪个
Tensor version。一个无法解析的动态调用必须有 `OpaqueOperationDefinition`，
而不是被删除。

### SG 的递归结构

```text
OperationDefinition: World.evaluate
  └── OperationDefinition: policy.get_action
        └── OperationDefinition: solver.solve
              └── ControlRegion: CEM loop
                    ├── OperationDefinition: sample
                    ├── OperationDefinition: model.get_cost
                    └── OperationDefinition: update_distribution
```

每个 definition 可查询 `parent_definition`、`child_definitions`、source span、
输入输出 slots 和 contract。这个结构支持从任意 function 下降到 operator，
也支持从 kernel 或 operator 向上收敛到 region。

## 3.2 Execution Evidence Graph（EEG）

EEG 描述一次具体运行中**实际观察到的事情**。它不能由静态图直接推导，也
不能用一次运行补全未执行路径。

### EEG 节点

| 节点 | 含义 |
| --- | --- |
| `OperationInstance` | 一个 `OperationDefinition` 的动态调用；保留 InvocationID、进程、线程、循环实例和 call stack |
| `KernelInstance` | CUDA/CPU kernel 或 runtime launch 的实际活动 |
| `MemoryEvent` | malloc/free/copy/view/alias/host-device materialization 的实际事件 |
| `ValueObservation` | 某个 ValueVersion/Materialization 在某个时间的观察 |
| `ObjectLifetime` | Python object 的创建、绑定、逃逸和销毁范围 |
| `StorageAllocation` | 一次物理 allocation 的生命周期和 allocator token |
| `StorageRegion` | allocation 上的 offset/shape/stride/dtype 区域 |
| `ControlEvent` | branch/loop marker/wait/barrier/thread/process/stream 的观察 |
| `ResourceObservation` | device、stream、memory、CPU/GPU utilization 等资源事实 |
| `Measurement` | duration、count、bytes、timestamp、confidence 和 clock domain |
| `EvidenceRecord` | 记录来源、采集器版本、schema、scope 和缺失项 |

### EEG 边

```text
instance_of
observed_reads
observed_writes
observed_produces
binds_object
uses_storage
materializes
aliases
overwrites_version
captures_callback
escapes_to
controls_instance
same_stream_before
happens_before
measured_by
evidence_for
```

所有边都有 `status ∈ {Observed, Inferred, Unknown}` 和 scope。`Observed`
表示采集器直接看到；`Inferred` 表示满足明确 join 条件；`Unknown` 表示
没有足够证据。EEG 永远不做“缺边即无边”的封闭世界假设。

### 当前实现对应关系

当前 `Event`、`ExecutionGraph`、`ProgramGraph.merge_execution()` 已经提供
了 EEG 的一部分：

- `Event` 大致对应 Observation/OperationInstance 的原始记录；
- `invocation:*` Action node 大致对应 OperationInstance；
- `state:*`、object、region node 是 ValueObservation 的早期形式；
- `resource:*`、contract、measurement node 是 EEG 辅助证据；
- `record_order`、`stream_order`、`loop_controls` 是不同可信度的 ordering。

但当前实现仍把 Action、Operation、Evidence 和辅助维度放在同一个
`ProgramGraph` namespace 中。v2 应保留读取兼容，内部改为明确的 EEG schema。

## 3.3 Optimization IR（OIR）

OIR 描述**可以被分析和替换的区域**，不是描述所有原始 event。

### OIR 节点

| 节点 | 含义 |
| --- | --- |
| `OptimizationRegion` | 一组嵌套 operation/instance，可作为一个替换边界 |
| `RegionPort` | region 的输入、输出、state、resource、escape 和 ordering 接口 |
| `ValuePattern` | 输入/输出 ValueVersion、Provenance、Materialization 的模式约束 |
| `EffectSummary` | region 的 reads/writes/RNG/exception/IO/order/escape 合同及 completeness |
| `Guard` | 运行时必须成立的条件和检查成本 |
| `Invalidation` | 哪些新版本、写入、外部事件会使计划失效 |
| `Candidate` | 一个待评估的替换假设，带 evidence references |
| `PlanAlternative` | 原始执行、reuse、hoist、residency、fusion、prefetch 等方案的候选表示 |
| `CostModel` | saved work、guard、lookup、memory、sync、compile/warmup 等成本 |
| `ValidationScope` | Level 1 区域、Level 2 solve、Level 3 call、Level 4 episode |
| `Fallback` | 合同不成立、成本不划算或验证失败时的原始区域 |

### OIR 的关键约束

一个 OIR region 必须显式声明：

```text
input value patterns
output value patterns
mutable state inputs/outputs
control entry/exit
ordering constraints
external escapes
resource requirements
effect completeness
guards and invalidation
validation scope
```

一个 `module_call` 可以成为 region 的一个成员，但不能自动成为完整
OptimizationRegion。一个 region 也可以包含 Python preprocessing、多个
operator、kernel、copy 和 synchronization。

## 4. 逻辑值和物理实现模型

### 4.1 `LogicalValueID`

`LogicalValueID` 表示一个逻辑值的 lineage branch。例如：

```text
goal observation
current observation at environment step 17
model parameter W_q
candidate action sequence for CEM batch 2
```

它不表示 Python object、storage 地址或某个 Tensor 的内存内容。一个逻辑值
可以在生命周期中产生多个版本。

### 4.2 `ValueVersionID`

`ValueVersionID = (LogicalValueID, Version)`。

Version 是语义写入或状态更新的序号，不是 allocator epoch，也不是
`Tensor._version`。一次原地写、环境 step、RNG 状态更新或 module buffer 更新
会产生新版本；没有语义写入的 view/copy/device materialization 不必产生新
版本。

版本记录应包含：

```text
logical_value_id
version_number or immutable version token
parent_versions
semantic type / shape constraints
validity interval or control scope
provenance_id
version evidence
```

### 4.3 `ProvenanceID`

`ProvenanceID` 是不可变的来源/推导记录，不是内容 hash。它形成 DAG，记录：

```text
producer operation definition/instance
input ValueVersionIDs
parameters and semantic context
relation ∈ {origin, copy, view, transform, aggregate, mutate, materialize, unknown}
evidence and confidence
```

它解决“不同 object 表示同一个来源”和“相同 shape 不代表同一来源”的问题。

### 4.4 `ObjectID`

`ObjectID` 仍表示 Python object identity，带有 lifetime 和 binding history：

```text
ObjectID --binds_to(scope)--> ValueVersionID
ObjectID --owns/contains--> ObjectID or ValueSlot
ObjectID --escapes_to--> external boundary
```

一个 object 可以在不同时间绑定不同 ValueVersion；不同 object 可以在合同或
观察支持下绑定同一 ValueVersion。

### 4.5 `StorageAllocationID` 和 `StorageRegionID`

`StorageAllocationID` 表示一次物理分配生命周期。指针地址只是观察属性，不能
直接充当 allocation identity。`StorageRegionID` 表示：

```text
allocation_id
offset
shape
strides
dtype
layout
device
```

多个 view 可以共享一个 allocation，Region overlap 可以是 EXACT/PARTIAL/
DISJOINT/UNKNOWN。

### 4.6 `MaterializationID`

`MaterializationID` 表示一个 `ValueVersionID` 在某个物理资源上的表示：

```text
materialization_id
value_version_id
storage_region_id or external storage
device / memory tier / representation
producer instance
ready event
validity interval
coherence/invalidation state
```

同一个逻辑版本可以有：

```text
NVMe materialization
CPU DRAM materialization
pinned host materialization
GPU HBM materialization
GPU view materialization
serialized representation
```

H2D copy 通常产生新的 Materialization，不产生新的 LogicalValueID 或
ValueVersionID。若 cast/normalize 改变了语义值，则产生新的 LogicalValueID
和 ProvenanceID；若某个库合同证明它只是同一值的表示转换，可以把它表示为
同一版本的 representation/materialization 变化。这个判断由合同决定，不能
由方法名决定。

### 4.7 deepcopy、view、transform、mutation 的统一规则

| 操作 | 默认 v2 表达 | 不能直接做的事 |
| --- | --- | --- |
| exact view/reshape | 同一 ValueVersion；新 StorageRegion/view provenance | 不能据此假设独立 storage |
| exact device copy | 同一 ValueVersion；新 Materialization | 不能把 `.to()` 当成物理 copy 证据 |
| `deepcopy` 不可变值 | 新 ObjectID，可共享同一版本的 exact-content claim | 不能保证未来写入仍同步 |
| `deepcopy` 可变对象 | 新 LogicalValueID，`copy` provenance 指向源版本 | 不能把两个 object 永久合并 |
| normalize/cast/encode | 默认新 LogicalValueID，新 ProvenanceID | 不能只按 shape/dtype 合并 |
| in-place update | 同一 LogicalValueID 的新 Version | 不能沿用旧缓存 |
| aggregation/concat | 新 LogicalValueID，多个 parent versions | 不能只记录最后一个 storage |
| 未知自定义变换 | Opaque provenance，关系 UNKNOWN | 不能推断逻辑相等 |

因此，“跨 deepcopy / transform / materialization 的统一身份”不是把所有对象
强行归到一个 ID，而是通过：

```text
LogicalValueID
  └── ValueVersionID
        └── Provenance DAG
              └── MaterializationID / ObjectID / StorageRegionID
```

统一查询。内容相等、语义相等、同一逻辑版本和同一物理存储必须是不同的
claim。

## 5. Operation 的定义和递归展开

### 5.1 `OperationDefinition`

建议字段：

```text
operation_definition_id
kind: function | method | module | operator | kernel | transfer |
      allocation | branch | loop | callback | region | stage | opaque
code_id / library symbol / schema version
source span or generated origin
parent_definition
child_definitions
input ports / output ports
state ports
static effect summary
contract reference
```

一个 PyTorch `nn.Module` 的 `forward`、Torch operator、CUDA kernel launch
和 H2D copy 是不同 definitions；它们可以通过 `contains`, `lowers_to`,
`implements` 关联。

### 5.2 `OperationInstance`

建议字段：

```text
operation_instance_id
operation_definition_id
invocation / process / thread / stream
control_context
iteration identifiers
input/output ValueVersion references
effect observation
start/end clock
resource observations
```

当前 `InvocationID` 可以迁移为 instance identity 的一部分，但不能替代
`OperationDefinition`。

### 5.3 `OptimizationRegion`

Region 是未来 backend 的共同输入。它至少要有：

```text
region_id
granularity
member definitions/instances
parent region / child regions
entry and exit control contexts
input/output/state ports
effect boundary
resource boundary
cost observations
candidate alternatives
```

Region 可以是单一 operator，也可以是：

```text
Python preprocessing → H2D → encoder → predictor → cost → sync
```

这使 CUDA Graph、fusion、prefetch、residency 和 dead-work 有共同的表示，
而不要求它们都伪装成 module cache。

## 6. 三种图之间的转换

### SG → EEG instrumentation

SG 产生 instrumentation points：函数入口、module forward、operator schema、
allocation/copy、control boundary、外部 IO。它提供 expected definition ID，
但不预先制造 instance 或 effect。

### EEG → normalized value/effect facts

EEG 的 object/storage/kernel/stream 记录经过统一器得到 ValueVersion、Provenance、
Materialization 和 Effect facts。每个合并都带 evidence references；冲突保留
为 alternatives 或 UNKNOWN。

### SG + normalized EEG → OIR

优化器把语义定义、实际实例、ValueVersion DAG、ControlRegion 和 measurements
组合成 OptimizationRegion。只有 OIR 才会生成 candidate、Guard、Cost 和
PlanAlternative。

### OIR → backend

未来 backend 只接收验证过的 PlanAlternative 和 region interface，不能直接读取
一个不透明的 `Event` 列表，也不能修改原始 EEG。转换失败或验证失败时回退
OIR 中的 original alternative。

## 7. 优化单位和粒度选择

v2 不选择一个固定的最小单位。统一单位是递归 `OptimizationRegion`，其
`granularity` 根据优化目标选择：

| 粒度 | 适合问题 | 主要接口 |
| --- | --- | --- |
| instruction/IR op | 局部 algebraic simplification、dead value | scalar/data dependency |
| operator | kernel fusion、layout/cast 合并 | shape、dtype、device、alias |
| function/module | pure reuse、memoization、library contract | call boundary、effects、state |
| loop body | invariant hoist、early stop、capture/replay | iteration state、exit、exception |
| dataflow subgraph | prefetch、residency、KV/cache、producer reuse | value lifetime、materialization、ordering |
| pipeline stage | CPU/GPU overlap、batching、schedule | external contract、queue、resource |
| whole pipeline | end-to-end schedule、episode-level transformation | Q Level 4、IO、environment |

选择规则：


1. 取能够包含完整 effect 和 control boundary 的最小 region；
2. 如果 backend 需要跨多个 operation 的数据生命周期，则提升到 dataflow region；
3. 如果替换会改变循环退出、异常或外部 IO，则提升到 loop/stage/whole scope；
4. 如果成本和 guard 只在更大范围才可测量，不能用小节点的时间代替；
5. 同一 region 可以有多个 alternatives，planner 选择一个或原始执行。

具体对应关系：

- CUDA Graph 需要稳定的 loop/body region、固定 control/resource interface；
- KV cache 需要 value lifetime/dataflow region，不能只看 attention operator；
- kernel fusion 需要 operator subgraph 和 layout/alias contracts；
- prefetch 需要 producer-consumer、ready event 和 resource timeline；
- residency 需要 ValueVersion 到多个 Materialization 的生命周期图；
- exact reuse 需要 function/module region，但只有在其 state/effect boundary
  完整时才可以缩小到一个 call。

## 8. LeWM 反向验证

LeWM 的源码结构提供了检验模型的压力测试，但不会产生 LeWM-specific rule。

### 8.1 Semantic Graph 应该表达的区域

```text
World.evaluate
  └── WorldModelPolicy.get_action
        ├── _prepare_info
        │     ├── normalization
        │     ├── image transform
        │     └── numpy → Tensor
        ├── replan decision / action buffer
        └── Solver.solve
              └── CEM control region
                    ├── sample action candidates
                    ├── expand info across samples
                    ├── LeWM.get_cost
                    │     ├── encode goal
                    │     ├── encode initial observation
                    │     ├── action_encoder
                    │     ├── autoregressive predictor rollout
                    │     └── criterion / cost
                    ├── topk
                    ├── update mean and variance
                    └── callback/history
```

### 8.2 LeWM 实体映射

| LeWM 概念 | v2 实体 | 版本/来源特点 |
| --- | --- | --- |
| dataset row/raw pixels | LogicalValue + source provenance | dataset storage 可有多个 materialization |
| current observation | 每个环境 step 的 LogicalValue/Version | 每次 `env.step` 后更新；不能跨 step 默认复用 |
| goal observation | 当前 episode/replan scope 的 LogicalValue | 同一 replan 中通常稳定，但 reset/goal change 会产生新 version |
| normalized/resize image | 新 logical value 或同 version representation，取决于 exact transform contract | transform provenance 必须保留 |
| `goal_emb` | goal-derived LogicalValue | 在 goal version 不变且 encode contract 完整时，CEM step 间可能共享 |
| `emb` / initial embedding | observation-derived LogicalValue | `LeWM.rollout` 已有 `if 'emb' not in info` 的语义缓存；应建模为 region/state，而非 module repeat |
| action candidate batch | CEM iteration-specific LogicalValue | RNG、mean、var 和 candidate tensor 变化；不同 step 默认不能复用 |
| candidate action sequence | candidate-specific LogicalValue | 只有相同 action version/prefix 才可能共享 rollout 子图 |
| predictor rollout embedding | derived value per candidate path | 依赖 history、action sequence、model state；通常不是同一版本 |
| CEM mean/variance | mutable solver State | 每轮 top-k 后更新；跨 iteration reuse 会改变算法 |
| cost | candidate-specific derived value | 依赖 predicted embedding 和 goal embedding |
| model parameters/buffers | stable LogicalValue versions | eval 不代表无 hidden state，但参数 materialization 可长期驻留 |
| environment state/RNG/video | State/IO/ordering contract | 外部 effect 和 episode correctness，不能按数值相等删除 |

### 8.3 可能的通用优化区域

以下是模型应能表达的 generic hypotheses，不是当前启用的优化：

1. 同一 replan 中，goal preprocessing 和 `goal_emb` 可能是 loop invariant；
2. CEM sample 维度中，初始 observation encoding 可以在多个 candidate rollout
   之间共享；
3. `expand` 是 zero-stride view，不能误报成完整 Tensor allocation；
4. model parameter HBM materialization 可能跨 CEM iteration 和 environment
   step 保持有效；
5. candidate action 改变时，dependent action encoding、predictor rollout 和
   cost 必须失效；
6. CEM mean、variance、top-k、RNG 和 callbacks 是 evolving state，不应 reuse；
7. `action_buffer` 和 warm-start `_next_init` 是跨 replan 的部分状态，必须用
   control scope 和 environment index 建模；
8. video、metrics、environment step 和 callback 是外部/顺序 effect，不能因为
   返回值没有立即被使用就删除。

### 8.4 模型失败的信号

如果 IR 只能说“某个 Linear 重复 100 次”，却不能表达：

```text
goal_emb 是同一个 goal version
candidate action 是不同的 iteration state
emb 是 observation 的共享前缀
predictor rollout 依赖 candidate-specific action sequence
model parameters 是稳定 materialization
environment step 改变了外部 state
```

那么它仍然是 profiler/candidate detector，而不是 semantic-aware optimizer。
当前 v0.1 的 storage-based logical version、单一 `last_writer` producer table、
Action-centric candidate 和缺少 composite region，正好会丢失这些关系。这是
必须先修复的架构问题。

## 9. 收敛提前终止的预留位置

Tensor 变化粒度和重要性属于 OIR 的 `ValueEvolutionProfile`，不是 exact reuse
guard。未来可为 loop region 增加：

```text
version trajectory
delta metric (norm/relative/error/task metric)
importance/consumer sensitivity
termination contract
confidence and sampling policy
```

只有当 Q contract 允许近似、外部状态和 RNG 语义可保持、Level 2/3/4 validator
通过时，才可生成 `early_stop` alternative。v2 只预留实体和 relation，不实现
这个 backend。

## 10. v2 不变量

1. 同一 Storage 不等于同一 LogicalValue；
2. 同一 LogicalValue 不等于同一 Version；
3. 同一 ValueVersion 可以有多个 Materialization；
4. 同一 Provenance 不保证 exact semantic equality，必须有 claim；
5. OperationDefinition、OperationInstance、OptimizationRegion 不可混用；
6. 静态 relation 不能升级为 runtime observation；
7. 缺失 evidence 只能产生 UNKNOWN；
8. OIR 计划不能反向修改 EEG；
9. 每个 transformation 必须有 original fallback；
10. 任意优化都必须声明适用粒度、control boundary、value interface、effect
    contract、cost 和 validation scope。

## 11. 当前结论

当前 v0.1 适合作为：

```text
Execution Evidence Collector
+ conservative candidate prototype
+ proof/cost reporting
```

它还不是完整的 Semantic-aware Execution Optimization System。下一阶段的
重点应是 v2 identity/provenance/graph separation 和 LeWM pressure-test，而
不是增加更多 detector 或 backend。
