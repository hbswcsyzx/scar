# G4：逻辑值、来源与物理表示 registry

状态：**Proposed — 实施设计，尚未通过 G4**。

依赖：[NEXT_PHASE_PLAN.md](NEXT_PHASE_PLAN.md) 的 G2、G3 验收完成后进入实现。
本文不增加 detector、backend 或源码变换。验收结果以独立 G4 report 为准。

## 1. Registry 要回答的问题

对于某次操作实际读到的值，SCAR 必须能够回答：

1. 这个值来自哪个来源或哪个操作？
2. 它是那个逻辑来源的哪个版本？
3. 当前 Python object、allocation、view、device copy 分别是什么？
4. 哪次写入、别名或 escape 会使当前表示失效？
5. 两个记录相等的证据是什么，证据在哪个范围内有效？

registry 产生身份、来源、有效范围和 guard 结果。它不据此宣布函数纯净，也不
自行批准 reuse、hoist 或删除 import。

G3 normalizer 对每个捕获记录创建 provisional snapshot identity。G4 必须保留
这个观察事实，另加有证据的关联。不能把 legacy `logical_version` 字符串、
同一个 pointer 或相同 shape 转换为已证明的逻辑等价。

## 2. 核心实体与关系

| 实体 | 精确定义 | 身份来源 |
| --- | --- | --- |
| `LogicalValueID` | 一个逻辑来源或独立演化分支 | origin/producer 事件、语义输出端口和 registry 分支序号 |
| `ValueVersionID` | 该分支的一次不可变历史值 | LogicalValueID 与语义写入序号 |
| `ProvenanceRecord` | 输出版本由哪些输入版本、哪个操作产生 | 实际 producer、版本边和证据 |
| `ObjectID` | 一次 Python object 生命周期 | process、registry handle 与 lifetime generation |
| `StorageAllocationID` | 一次物理分配生命周期 | allocation witness 或受跟踪 storage lifetime |
| `StorageRegion` | allocation 上可寻址的表示区域 | allocation、offset、shape、strides、dtype |
| `Materialization` | 某个版本在某个资源上的具体表示 | version、region、device、producer、ready 状态 |
| `BindingInterval` | 某个 slot 在一段执行范围内绑定的 object/version | slot、执行 scope、起止事件 |
| `ValidityRecord` | 某个物理表示在哪个执行范围内仍表示某个版本 | 写入覆盖、别名、escape、readiness 与失效证据 |
| `EqualityEvidence` | 两个特定版本/表示在特定时刻满足哪一种等价关系 | 比较方法、输入证据、合同和有效范围 |

`LogicalValueID` 不包含 storage 地址；object 地址和 storage 地址只是可观察
属性。不同 allocation 可以表示相同历史版本，同一 allocation 也可以先后
表示不同来源的数据。

版本记录是历史事实，不能随当前物理 buffer 被覆写而修改。写入使物理表示的
有效区间结束，并产生新版本。已经复制到其他 allocation 的旧版本可能继续有效。

静态 slot 也不是动态值：同一参数或变量 slot 在不同 invocation 中可以绑定
不同 object/version。因此 `BindingInterval` 必须包含 invocation/control
scope，不能只用变量名或源码位置。

## 3. 必须先补齐的 typed records

这些字段承担正确性判断，不能只藏在无约束 metadata 中。

```text
BindingInterval
  slot: ValueSlotID
  object: ObjectID
  version: ValueVersionID
  scope: execution scope / invocation
  start_event, end_event
  evidence

MutationCoverage
  scope
  observed_writes
  foreign_aliases
  escaped_boundaries
  completeness: COMPLETE | PARTIAL | UNKNOWN
  evidence

ValidityRecord
  materialization: MaterializationID
  version: ValueVersionID
  start_event, end_event
  state: VALID | INVALID | NEEDS_VERIFICATION
  reason
  evidence

EqualityEvidence
  left, right: version/materialization references
  relation
  method
  compared_at
  contract
  validity_scope
  evidence

GuardResult
  state: VALID | INVALID | NEEDS_VERIFICATION
  checked_versions / materializations
  required_facts
  reason
  evidence
```

时间范围优先使用同一执行 scope 内的事件顺序；不能把 Kineto 与
`perf_counter` 时间戳直接比较来证明绑定或有效区间。

当前 v2 `EquivalenceClaim` enum 不足以独立保存一次比较及其时效性；实现时需
增加 typed equality record 及 codec/validator。相似地，`ObjectBinding.scope`
字符串不能代替 typed 起止区间。

## 4. “没有观察到写入”与“值未变化”

必须区分三个事实：

| 事实 | 允许的行为 |
| --- | --- |
| 观察到写入 | 结束受影响 materialization 的有效区间，创建新版本和 MUTATE provenance |
| 写入观察不完整或出现外部别名 | guard 为 NEEDS_VERIFICATION，记录无法继续证明稳定的原因 |
| 完整范围内确定无写入，或完成有效的精确比较 | 在明确 scope 内允许 VALID |

第二种情况不能伪装为“Observed mutation”。可以创建新的 provisional observation，
但不能凭空添加一次实际写入。`INVALID` 表示已有不满足条件的证据；
`NEEDS_VERIFICATION` 表示缺少必要证据，必须指出缺失事实与下一步验证方法。

`torch.from_numpy` 是必要的反例：NumPy 可能修改共享 buffer 而 Torch `_version`
不变化。只有 Tensor 的 `_version`、object 身份或有限 prefix 不变时，guard
仍不能通过。已知 NumPy 写入可以通过显式观察入口报告；未被观察的外部写入
风险由不完整 coverage 表达。

inference tensor 使用相同规则。读取 `_version` 失败不应导致 registry 失效，
更不能把失败当作“此 Tensor 永远不变”。

## 5. 来源和变换规则

### 5.1 Origin

`origin` 为来源事件的输出端口创建新 LogicalValue 和 v0。
dataset row、解析结果、函数参数首次进入受观察范围都可以作为 origin；其中
“首次观察”不等于已经证明最终的数据来源，证据不充分时必须注明 provisional。

相同内容也不自动合并来源。来自两个文件的同值 scalar 可以具有不同 provenance，
并由独立 equality evidence 表达相等。

### 5.2 Copy 与 deepcopy

不可变值经过有明确语义保证的复制，可以产生新 object/materialization，引用
同一历史版本。

可变对象的 deepcopy 产生独立演化分支：新 LogicalValue、新 object、独立
allocation，COPY provenance 指向源版本，并记录复制时的 exact-content
关系。之后修改任一侧不能使另一侧同步推进版本。

任意 Python `copy.deepcopy` 调用本身不是上述保证。对象可自定义
`__deepcopy__`，Tensor subclass 也可能拦截行为。只有受支持的实际类型、
版本化操作语义或有效比较证据才能支持 exact claim；否则保留 copy hypothesis。

### 5.3 View、reshape、slice、expand

共享 allocation 与逻辑等价分别建模。

`StorageRegion` 的 offset、strides 以 dtype element 为单位；检查 overlap 时
必须转换到一致的字节地址含义。zero-stride expand 共享原有地址，不代表分配
`numel × element_size` 的新 buffer。空 region 不访问元素；negative stride
需要完整边界检查。

只有完整、无损且有明确索引映射合同的 representation change 才能共享同一
ValueVersion。slice、permute、broadcast 等改变了可观察索引关系时，默认创建
VIEW/TRANSFORM 派生逻辑值，保留映射和 shared allocation 关系。不能仅因为
storage 相同就合并不同 view。

已有 `IR_DESIGN_V2.md` 中“exact view/reshape 同一版本”的规则应按上述
representation contract 解读。实现 G4 时需要同步明确这个边界。

相交 region 的写入使相关物理表示失效；无法精确判断 overlap 时按可能相交
处理。区间包围盒不相交可以证明无重叠，但包围盒相交不一定证明 strided
元素确实相交，不能把近似结果冒充 exact overlap。

### 5.4 CPU/GPU materialization

受支持且成功完成的 exact device copy 可以让两个 materialization 引用同一
版本。新的 device/region/readiness 必须分别记录。

`.to()` 同设备返回同一对象时不创建虚构的物理 copy；dtype 改变默认属于
semantic transform。异步 copy 未完成之前目标 materialization 不能作为 ready
输入使用。只有 runtime memcpy evidence 才能支持物理搬运事实；逻辑 copy
合同与物理 copy 测量不是同一个证明。

可独立修改的多个 copy 必须在分支/写入模型中保留各自历史，不能通过“同版本”
关系传播并不存在的写入。来源版本仍有效的其他 materialization 不应无故失效。

### 5.5 Transform、aggregate、serialization

normalize、cast、encode 等默认创建新 LogicalValue，TRANSFORM provenance
记录全部相关输入版本。aggregate 同样产生新值，保留所有输入 ancestry。

serialization/deserialization 默认是 transform。只有明确的类型、格式版本、
编码合同与执行证据才能建立无损还原关系；相同 shape 或文件名不足以证明。

来源图不应因“语义等价”产生自环。保留原版本的 materialization 事件不是一次
新的语义生产者；新逻辑值的 provenance 与物理表示的 derivation 要分别校验。

## 6. 生命周期与别名

allocation identity 必须包含生命周期 witness，不能只用 data pointer。
运行时 adapter 可以使用 process-local registry handle、弱引用与 generation。
对象销毁或显式 allocation/free witness 结束当前生命周期；地址复用创建新 ID。

`_cdata` 或某个 allocator token 本身也不能被视为永不复用的全局 ID。
无法证明两个观察属于同一 allocation 生命周期时保留独立身份，而不是强行合并。

NumPy 与 Torch 可能用不同 storage wrapper 表示共享 buffer。捕获到实际
`from_numpy` 操作时可以记录共享来源与 alias witness；仅看到相同或相交地址时
应保留范围和证据等级。未封闭的 ctypes、NumPy、callback 或未知消费者使
相关 mutation coverage 降级。

registry 默认不强引用全部 Tensor。否则 tracing 会改变对象和 allocation
生命周期，造成额外显存驻留。只有显式 enrollment 的 checkpoint 可以保留受预算
限制的额外存储。

## 7. 有限采样和按需比较

常规观察只需要 descriptor、身份、版本事件和可选的有限 prefix。

```text
shape/dtype/representation 不同
  -> 根据所检查合同拒绝 equality

prefix 不同
  -> 对应范围内不相等

shape/prefix 相同
  -> 仅通过 cheap filter，尚未证明完全相等
```

GPU prefix 采集本身可能造成 copy 和 synchronization，默认关闭；启用时必须
记录成本。对需要 materialization equality 的比较，device 可以不同；不能把
device 不同一概当作逻辑值不同。

只有进入候选审查的值才能 enrollment：创建一个有内存预算和有效区间的
checkpoint，以便之后精确比较。checkpoint 不需要每次迭代创建，也不应把完整
Tensor 值写入 JSONL。退出 scope、对象失效或超过预算时释放 checkpoint。

重要边界：旧观察如果只保存 shape/prefix，后来做一次全量比较不能追溯证明
旧观察的未采样元素相同。新 checkpoint 只支持从其建立时刻开始的比较。

仅保存对同一可变 Tensor 的引用不是 checkpoint：它可能已经随原 Tensor 被
原地修改，随后与自身比较会得到无意义的“相等”。

“exact”也必须指定合同。数值相等、bitwise 相等、NaN payload、signed zero、
layout、dtype、容器类型可能有不同要求。摘要相等只能形成注明碰撞假设的
equality evidence，不能悄悄取代合同要求的精确比较。

## 8. 计划 API

下列为接口边界设计，名称可以随实现调整；各项语义和证据要求必须保留。

```python
registry.origin(descriptor, evidence) -> ValueHandle
registry.bind_slot(slot_id, handle, interval, evidence)
registry.view(source, result_descriptor, mapping, evidence) -> ValueHandle
registry.copy(source, result_descriptor, copy_contract, evidence) -> ValueHandle
registry.transform(inputs, result_descriptor, operation, evidence) -> ValueHandle
registry.mutate(handle, written_region, evidence) -> ValueHandle
registry.escape(handle, boundary, evidence)
registry.invalidate(handle, reason, evidence)
registry.guard(handle, scope) -> GuardResult
registry.checkpoint(handle, budget) -> Checkpoint
registry.compare(checkpoint, current, contract) -> EqualityResult
registry.attach_observation(observation_id, handle, evidence)
```

IR 层只依赖 typed descriptor 与 evidence；Torch/NumPy 观察和内容比较由 runtime
adapter 提供。`copy`/`view` 接口不能把调用方传入的操作名称自动升级成 Observed
exact semantics，必须检查 evidence 和对应操作合同。

`attach_observation` 连接历史 G3 observation 和新 registry 事实，不删除原来的
capture identity。模糊关联保留候选 correspondence，不能合并 ValueVersion。

## 9. 实施顺序与验收

| 顺序 | 产物 | 必须通过的检查 |
| --- | --- | --- |
| G4.1 | typed records、codec、cross-graph validator | interval、version、materialization 引用一致；dangling reference 和非法时间范围拒绝 |
| G4.2 | descriptor-based registry | origin/copy/view/transform/mutate/aggregate/escape 的 lineage 和失效正确 |
| G4.3 | Torch/NumPy CPU adapter | from_numpy、inference、deepcopy、view、allocator lifetime 反例 |
| G4.4 | bounded checkpoint | 未采样位置修改无法骗过 guard；预算、释放和 prospective-only 证明 |
| G4.5 | 小型 CUDA materialization | exact H2D/DtoH identity、dtype transform、same-device no-op、ready 状态分别验证 |
| G4.6 | G3 关联与报告 | legacy tokens 不升级；证据充分时明确连接；coverage 与缺失事实可审计 |

验收测试必须验证行为，不能只手工填写关系再检查这些关系存在：

- 用实际 `torch.from_numpy`，在 prefix 之外通过 NumPy 修改内容；旧 guard 不得
  VALID。区分显式 observed mutation 与未观察写入导致的 NEEDS_VERIFICATION。
- 在 `torch.inference_mode()` 中创建并修改 Tensor，不能依赖 `_version`。
- 用确定的 allocator/lifetime fixture 重用同一地址，验证 allocation ID 不同；
  不依赖真实 allocator 恰好重用地址来决定测试是否有覆盖。
- 实际 view/expand 验证 offset、stride 和 allocation，共享写入影响相交视图；
  disjoint view、zero-size view 与外部 alias 均有反例。
- 实际 mutable deepcopy 后分别修改两侧，确认 lineage 独立且保留 COPY ancestry。
- GPU 可用时做极小 exact copy 验证；物理 memcpy 测量和逻辑 materialization
  验证分别记录。缺少 GPU 时不得用 skip 冒充完整 G4 GPU 验收。
- 同一 shape/dtype 的 transform 输出不能误认为原 logical value。
- callback/foreign escape 之后旧稳定性证明失效。
- 一次普通 metadata observation 不创建完整 Tensor 副本；checkpoint 只在
  enrollment 时创建，超过预算明确拒绝，释放后额外引用消失。
- G3 相同 legacy object/storage/version 字符串仍不能独自建立 exact equivalence。

每个检查绑定实际测试 node，机器报告记录代码 revision、源码摘要和测试结果。
G4 通过不代表 LeWM 已优化，也不代表任意 Python 程序的所有写入已被捕获。

## 10. 保留风险与后续边界

任意 native extension、外部进程、共享内存或未观察的别名写入无法从 Tensor
元数据推导。registry 必须允许返回具体的验证需求，不能为了消除 UNKNOWN
而制造证明。

并发 mutation 与 CUDA asynchronous execution 需要明确 happens-before。
没有相应 ordering witness 时，内容比较只证明被同步保护的检查时刻，不能
延长为未来调用都有效。

G4 完成的是身份、来源和有效性设施。G5 才组合程序范围内的 effect closure、
consumer boundary 与 contract；G6/G7 才利用这些事实构造 region 和修改计划。
