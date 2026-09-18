# SCAR 当前 IR 到 IR v2 的迁移方案

状态：**审查和迁移计划**。

本文件说明当前代码中哪些部分可以保留、哪些部分需要重构，以及如何在不
破坏已有 trace 的情况下建立 Semantic Graph、Execution Evidence Graph 和
Optimization IR。当前阶段不删除现有代码，也不实现新的 optimization backend。

## 1. 当前实现盘点

### 当前保留价值

| 当前组件 | 现在表达的内容 | v2 的归属 | 结论 |
| --- | --- | --- | --- |
| `CodeID` | 源路径、qualname、版本 fingerprint | `OperationDefinition` identity / `SourceAtom` correspondence | 保留概念，扩展 kind/schema |
| `InvocationID` | 一次动态调用 | `OperationInstance` identity 的组成部分 | 保留，增加 definition/control scope |
| `Event` | append-only runtime record | EEG raw evidence | 保留 JSONL 兼容格式 |
| `ExecutionGraph` | event collection/grouping | EEG ingestion buffer | 保留，限制其职责为 raw evidence |
| `ActionLabel` | VAL/REP/MEM/XFER/STATE/CTRL/ORDER/IO/OPAQUE | operation/effect facets | 保留作为 facets，不再当作 node taxonomy |
| `Effect` | reads/writes/allocates/frees/aliases/escapes 等 | `EffectObservation` / `EffectSummary` | 保留字段，增加 scope/completeness/claim refs |
| `Region` | storage geometry 和 overlap | `StorageRegion` | 保留物理几何逻辑，去掉 logical identity 负担 |
| `ObjectEntity` | Python object + region | `ObjectLifetime` + bindings | 重构为生命周期和 value binding |
| `StorageVersionRegistry` | storage token/epoch/logical epoch | `StorageAllocation` invalidation evidence | 只保留为物理 observer，不再生成完整 LogicalValue |
| `Materialization` | version/storage/device/producer/ready | `Materialization` | 保留，改为挂在 ValueVersion 上 |
| `ProgramGraph.validate()` | 节点/边/schema/source coverage 检查 | SG/EEG/OIR 各自 schema validator | 拆分，保留 v1 reader |
| `merge_execution()` | 静态/动态/辅助节点合并 | EEG ingestion + correspondence | 重构，禁止直接混合 graph namespaces |
| `graph_candidates` | 从 Action→State 边重建重复候选 | OIR builder 的旧 adapter | 暂停扩展，后续迁移 |
| `Opportunity` | detector candidate + cost + proof | OIR `Candidate`/`PlanAlternative` | 重构字段和层次 |
| `select_candidates` | 选择 TRANSFORM/REJECT/UNKNOWN/KEEP | OIR planner | 保留决策语义，改为 region/alternative 输入 |

### 当前结构性问题

1. `GraphNode.kind` 混合了 K/Σ/A/R/Q/M 和静态/动态语义；同一节点模型无法
   表达 operation definition、instance、value 和 evidence 的生命周期。
2. 动态 state ID 通常取 `logical_version` 或 object ID，而这个 token 目前由
   storage pointer/epoch 推导；deepcopy、transform、materialization 之间没有
   provenance DAG。
3. `ProgramGraph.merge_execution()` 通过 `last_writer` 为 logical version
   连接 producer，适合局部 trace 依赖，但不能表示多输入 provenance、copy
   branch、版本区间、未观察 producer 或不同 materialization。
4. `Event.inputs/outputs` 是字典描述，缺少端口、semantic type、value version、
   materialization 和 binding scope 的严格 schema。
5. `Opportunity` 的 `code_id` 不能唯一确定可替换 region；同一 CodeID 可能
   在不同 loop、thread、resource 和 state scope 具有不同合法性。
6. `operation_view()` 是有用的可视化投影，但仍建立在 v1 mixed graph 上；
   它不是 v2 的 Optimization IR。

## 2. 目标模块边界

建议把 `scar/ir/` 逐步拆成以下逻辑模块。物理目录可以分阶段迁移，先保证
schema 和 import compatibility：

```text
scar/ir/v2/
├── ids.py              # Definition, Instance, LogicalValue, Version, Provenance
├── semantic.py         # SG nodes, ports, control regions, static contracts
├── evidence.py         # EEG nodes, observations, evidence references
├── values.py           # object, allocation, storage region, materialization
├── correspondence.py   # SG ↔ EEG mapping with confidence/multiplicity
├── effects.py          # observed and summarized effects with completeness
├── optimization.py     # regions, ports, guards, invalidation, alternatives
└── schemas.py          # versioned serialization/validation
```

现有 `scar/trace/` 继续负责采集，不能直接构造 OIR；现有 `scar/analysis/`
先改名义为 evidence normalizer/reporting，暂不扩展 detector；现有
`scar/planner/` 保留为旧 planner adapter，直到 OIR region schema 稳定。

## 3. 保留部分

### 3.1 Trace 和 profiler

以下必须保留为 v2 的 evidence source：

- Python profile call/return、C-call、thread/process identity；
- Torch module hooks、TorchDispatch operator boundaries；
- Kineto/CUDA kernel、memcpy、barrier、stream；
- resource sampler；
- line/bytecode loop marker；
- raw timestamp、duration、clock domain、process/thread/stream；
- append-only `events.jsonl`、`entities.jsonl` 和 metadata。

它们记录“发生了什么”，不负责决定“应该怎么改”。trace schema 应增加
`collector`, `schema_version`, `scope`, `raw_reference`，但不把 raw record
改写成推理结论。

### 3.2 低层物理几何

`Region.overlap()`、storage allocator token、device、dtype、shape、stride、
offset 和 stream relation 都是 v2 所需的低层事实。它们应移动到 `values.py`
或 `evidence.py`，但不再直接作为 LogicalValue identity。

### 3.3 Effect uncertainty

`Knowledge` 和 `collection_knowledge` 的方向是正确的。迁移时需要把：

```text
observed members
completeness
scope
evidence references
```

分开存储。`[] + UNKNOWN` 继续表示“没有观察到成员且集合不完整”。

### 3.4 Proof ledger 和四级 validation

`ProofObligation`、`PROVEN/DISPROVEN/UNKNOWN`、Level 1–4 validation 是未来
OIR 必须保留的接口。它们要从 `Opportunity` 中独立出来，挂在
`Candidate`/`PlanAlternative` 上。

## 4. 必须重构的部分

### 4.1 Graph

当前 `ProgramGraph` 先改成 v1 compatibility graph：

```text
ProgramGraphV1 reader/writer
        │ adapter
        ├── SemanticGraphV2
        └── ExecutionEvidenceGraphV2
```

新的 graph namespace 不允许用相同 string ID 混合：

```text
sg:operation-def:...
eeg:operation-instance:...
sg:value-slot:...
eeg:value-observation:...
oir:region:...
```

静态 source graph 继续保证物理行覆盖，但每行通过 `SourceAtom` 关联到一个
或多个 `OperationDefinition`/`ValueSlot`/`ControlRegion`。空白、comment、
无法解析的动态代码使用 `OpaqueOperationDefinition` 或 source coverage
record，不伪装成可优化操作。

### 4.2 State identity

当前 `StorageVersionRegistry.token()` 只能作为物理 invalidation evidence：

```text
storage token → StorageAllocationID + allocation epoch
mark write    → observed mutation event
```

它不再直接生成 `LogicalValueID`。新的 Value registry 需要维护：

```text
ObjectID → binding intervals → ValueVersionID
ValueVersionID → ProvenanceID
ValueVersionID → MaterializationIDs
MaterializationID → StorageRegionID / device / ready event
```

初期无法证明的 binding 必须生成 UNKNOWN claim，不能根据 data_ptr、shape 或
少量前缀值做逻辑合并。

### 4.3 Candidate

当前 candidate：

```text
code_id + supporting_events + reason + backend
```

迁移为：

```text
Candidate
  target_region_id
  observed_instance_ids
  input ValuePattern
  output ValuePattern
  state/control/resource boundary
  evidence references
  proof obligations
  alternatives
```

`module_call` 只能是一个 observation，不能默认是 region。旧 detector 的结果
可以作为 `LegacyCandidateEvidence` 导入，但不能直接进入 transform selection。

### 4.4 Planner

当前 planner 对 candidate 的 `expected_savings_ns` 做决策。v2 planner 需要
先选择 region，再比较 alternatives：

```text
original region
exact reuse region
hoisted region
resident materialization region
fused region
deferred region
```

每个 alternative 绑定自己的 guard、memory/lifetime、compile/warmup、sync、
validation 和 fallback cost。planner 仍然输出 `TRANSFORM/REJECT/UNKNOWN/KEEP`，
但决策对象是 region alternative，不是一个 CodeID。

## 5. 迁移阶段

### M0：冻结 v1 证据

- 保持当前 v1 JSONL/graph 可读；
- 为已有 generic trace、LeWM trace、copy/view/alias fixture 建立 golden
  checksums；
- 记录 v1 graph 是 evidence compatibility artifact，而不是 v2 truth；
- 本阶段不新增 detector/backend。

### M1：先实现 v2 identity schema

只添加数据类和 schema validator，不接 planner：

```text
OperationDefinition
OperationInstance
LogicalValueID
ValueVersionID
ProvenanceID
MaterializationID
StorageAllocationID
StorageRegionID
ObjectBinding
```

必须先通过以下 micro fixtures：

1. 同 object 原地写产生新 Version；
2. 两个 view 共享 allocation/同版本但 Region 不同；
3. H2D 产生新 Materialization，不产生新 logical version；
4. deepcopy 产生新 object，并建立 exact-content-at-creation provenance；
5. normalize/cast 产生 derived logical value；
6. 两个 object 由同一 dataset row 派生但未来可独立修改；
7. allocator pointer 复用不恢复旧 version；
8. unknown custom function 不被合并。

#### 当前实现证据

M1 的第一版已经位于 `scar/ir/v2/`，但仍保持与 v1 完全隔离：

- `ids.py` 提供 typed `LogicalValueID`、`ValueVersionID`、`ProvenanceID`、
  `ObjectID`、`StorageAllocationID`、`StorageRegionID`、`MaterializationID`、
  `OperationDefinitionID`、`OperationInstanceID` 和 `ControlRegionID`；
- `values.py` 提供 `ValueGraph`、版本 ancestry、provenance relation、object
  binding、storage region 和多 materialization；validator 检查引用完整性、
  provenance output 一致性和版本 ancestry cycle；
- `semantic.py` 提供可递归展开的 `OperationDefinition`/`ValueSlot`/
  `ControlRegion`，`children_of` 和 `descendants_of` 不合并 child identity；
- `evidence.py` 提供独立的 `OperationInstance`/`ValueObservation`/
  `EvidenceGraph`，保留 definition 与 instance 的区别；
- `tests/unit/test_ir_v2.py` 覆盖同一 logical version 的多 materialization、
  view/region、in-place mutation、deepcopy、transform、allocator token 复用、
  unknown custom transform、递归 operation 和 invalid graph。

当前证据是 **Implemented / Verified at schema level**。它还没有接入旧
`TraceSession`、静态 source builder 或 planner；这些属于 M2–M5，不能把 M1
的 schema tests 描述成已经完成的真实 LeWM v2 graph。

### M2：raw trace 到 EEG

让现有 `TraceSession` 只写 raw EEG records；新增 normalizer 将 module/operator/
kernel/copy/sync 对齐为 `OperationInstance`、`MemoryEvent`、`ValueObservation`
和 `ControlEvent`。此阶段只生成报告，不执行优化。

### M3：静态 source 到 SG

把 `from_source/from_project` 的 AST/CFG/variable facts 转换为：

```text
SourceAtom → OperationDefinition / ValueSlot / ControlRegion
```

源码标签仍然是 `Inferred` syntax evidence。每个动态 call 通过 path/span/
library schema correspondence 关联到 definition，保留一对多 ambiguity。

### M4：SG ↔ EEG correspondence

建立可审计的 mapping：

```text
definition_id
  ↔ instance_id(s)
  ↔ source span / library schema
  ↔ evidence scope/confidence
```

一个 definition 可以没有 instance，一个 instance 可以只有 opaque/library
correspondence；两者都不能被默认为 dead 或 pure。

### M5：构造 OIR，但只报告

从 SG+EEG 生成 `OptimizationRegion` 和 `ValuePattern`，输出 region graph、
effect boundary、control boundary、provenance、cost measurements 和 proof
ledger。不得调用现有 backend。

第一批 OIR pressure tests 应来自 LeWM 的：

```text
goal encode
initial observation encode
CEM iteration
candidate rollout
mean/variance update
replan/action buffer
environment step
```

目标是确认模型能表达它们，而不是找到一个可以立即 cache 的 module。

### M6：重写 candidate/planner

只有 OIR schema 经过审查后，才把旧 `graph_candidates`、`loops`、`materialization`
等 detector 迁移成 OIR builders。旧 backend 在新的 region/effect/value
contract 上重新评估；本阶段不能假定现有 exact reuse 继续适用。

## 6. 迁移期间的兼容规则

1. v1 trace 永远可读取；
2. v1 `logical_version` 只能导入为 `legacy_storage_version` evidence；
3. v1 candidate 只能显示为 legacy observation，不能自动转换为 `TRANSFORM`；
4. v2 graph 不覆盖或修改原始 artifacts；
5. 同一执行可以同时存在 v1 report 和 v2 report，二者通过 run ID 关联；
6. schema version 明确拒绝静默向前兼容；
7. v2 缺少 provenance 时输出 UNKNOWN，而不是回退到 pointer/shape 相等。

## 7. 不要迁移成什么

以下方向会把 SCAR 拉回 profiler/candidate detector，应明确禁止：

- 把所有动态 event 直接命名成 OperationDefinition；
- 用 `Tensor._version`、data pointer、shape 或前缀 fingerprint 作为逻辑身份；
- 把所有 `deepcopy` 合并成相同 Tensor；
- 把所有 `Module` 当作 pure function；
- 把 `record_order` 当作跨线程/跨 stream happens-before；
- 让 detector 直接创建 backend invocation；
- 用缺少 consumer 的 trace 证明 dead；
- 为 LeWM 增加 goal、CEM、embedding 名称匹配规则；
- 在 v2 schema 未稳定前增加更多 backend。

## 8. 下一阶段路线

```text
架构审查（当前）
  ↓
v2 identity/provenance schema + fixtures
  ↓
EEG raw normalization
  ↓
SG source/library model
  ↓
correspondence and ambiguity
  ↓
OIR report-only bridge
  ↓
LeWM pressure-test review
  ↓
candidate/planner migration
  ↓
重新评估旧 backend
  ↓
再选择第一个 composite transformation
```

最终目标不是让 v2 报告里出现更多候选，而是让每一个候选都能回答：

```text
它替换哪个 region？
输入输出是哪一个 ValueVersion？
来源和 materialization 是什么？
哪些 control/effect/escape 必须保持？
什么事件会使它失效？
成本如何测量？
验证范围是什么？
失败时如何回退？
```

在这些问题能够由 IR 明确回答之前，SCAR 不应继续扩大 detector 或 backend
数量。
