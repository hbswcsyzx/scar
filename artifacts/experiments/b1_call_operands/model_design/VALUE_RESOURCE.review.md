# Whole-program Value / Resource interface review

2026-10-16。只读审查：`WHOLE_PROGRAM_MODEL.draft.md`、冻结 worktree
`dcd4986` 的 `scar/ir/program/model.py`、`scar/ir/v2/values.py`、
`scar/ir/provenance.py`、`scar/ir/v2/contracts.py`。未修改产品代码、未运行目标。

## 1. 结论与当前缺口

五类完整模型可以成立，但 **Value 的静态定义、动态出现、逻辑内容三层不能各自
成为一套未连接的规范身份**。当前 `ProgramGraph.ValueID` 是静态 SSA 定义；
v2 `ValueVersionID` 是运行期逻辑数据版本，两者并非同类 ID。目前缺少强类型、
可验证的一对多对应。只给 `DataValue` 增加 `logical_version` 字段会把循环中
多次定义、引用内容变化及路径合流全部混淆。

现有 provenance registry 的 allocation lifetime、区域重叠、外部 alias coverage、
exact contract 可保留为证据实现。`ready_event: str`、单一 `ReadyState`、
`mark_ready(handle, observed_event)` 仍不足以证明具体工作代次、消费者及可见性。
旧 `ResourceRequirement(id: ResourceID, selector: str)` 也不能同时承担声明、约束、
实际资源和 handle 身份。

## 2. 唯一身份链与建议 schema

下列为接口规格，不宣称已实现。`*ID` 均强类型；ID 本身不证明相等、顺序或不相交。

```text
ValueDefinition = 现有 program.ValueID
ValueOccurrenceID = (capture, activation, definition: ValueID, visit)
ValueOccurrence {
  id, producer_occurrence | incoming_edge_occurrence,
  denotation: DataDenotation | ObjectDenotation | ProtocolDenotation
}
DataDenotation { version: ValueVersionID }
ObjectDenotation { object: ObjectID }
ProtocolDenotation { typed protocol value }

LogicalValue { id: LogicalValueID, domain: LogicalDomain }
ValueVersion {
  id: (LogicalValueID, unique_revision),
  defining_provenance: ProvenanceID
}
ValueDerivation {
  id: ProvenanceID, producer: OperationOccurrenceID,
  ordered_inputs: (UseOccurrenceID, ValueVersionID | StateVersionOccurrenceID)*,
  outputs: ValueVersionID*, protocol_version, evidence
}
```

`LogicalDomain` 明确抽象载荷的类型/shape/元素解释；device、承载地址和布局等物理
表示另存。能否把 dtype 变化视为纯表示变化，必须由该 domain 的明确解码合同决定。

- `ValueID` 是规范静态定义，不再另造平行的静态逻辑值定义表。v2 的逻辑版本表是
  同一完整模型的动态 denotation 层。旧 `StaticValueID` 如保留，只能是来源索引的
  对应，不可成为第二套操作结果的权威定义。
- 相同静态定义有多次动态 occurrence；不同静态定义可通过传参、已证明的透明复制
  指向相同内容版本。每个动态 Use 保留实际来源 occurrence，不能只记版本集合。
- `LogicalValueID` 是自动产生的内容演化族，不是变量名、存储或业务概念。
  origin/一般 transform 创建族；已证明保持抽象载荷的物化可沿用版本；mutation
  由实际前驱版本产生新 revision。同族允许分叉，不允许用全局 `latest` 当作所有
  alias/副本的当前值。revision 是唯一标签，祖先/先后取显式边，不能靠数字比较。
- `ValueVersionID` 表示一次不可变的内容定义，不要求保存该内容。不同版本可相等，
  同一版本可有多个副本；身份归并必须来自协议证明，不来自 shape/样本巧合。
- ReferenceValue 的 occurrence 指向 ObjectID，**不能永久指向初次观察的内容版本**。
  实际读取经 `StateRead(object/location, incoming StateVersion, selector)` 才产生
  对应 DataDenotation。局部重绑改变 binding，不等于改写对象内容。
- 静态 `StateVersionValue(ValueID)` 同样需要 occurrence；它不是 v2 的内容版本 ID。
  状态更新可同时改变内容、ownership、offset、队列等，不能全部解释为 tensor 值。

保留一个 `ProvenanceID` 强类型族，但其记录应为判别联合：`ValueDerivation` 与
`RealizationDerivation`。后者记录 source/target materialization 和运输/布局协议，
不为保持版本的物化制造 `v -> v` 的逻辑祖先边。现有代码已特判该情形，但规范层
应直接区分这两种关系。相同 provenance 或共同祖先也不证明相等。

## 3. object、allocation、materialization 与可变状态

```text
ObjectIdentity { ObjectID, capture/process, lifetime, type_evidence }
Allocation { AllocationID, resource: ResourceInstanceID, lifetime, capacity }
StorageRegion { allocation, byte/element addressing convention,
                offset, shape, strides, dtype, layout }
Materialization {
  MaterializationID, content: ValueVersionID, representation_contract,
  backing: StorageRegion | FileExtent | OpaqueBacking,
  producer_occurrence, validity_interval, readiness_requirement
}
ObjectAccessBinding {
  object: ObjectID, selector, state_interval,
  backing_region | resource_handle | ordinary_object_state
}
RealizationDerivation {
  ProvenanceID, producer_occurrence,
  source_materializations*, target_materializations*, protocol, evidence
}
```

Object 与 materialization 是显式多对多关系，带时间/状态范围；不能要求每个 Python
对象只有一个永久 `ValueHandle`。同一 tensor object 可在不同时刻表示不同内容；
多个对象可指向同一 allocation 的重叠区域。地址和 allocator token 只作为证据，
allocation identity 必须包含生命周期；跨 wrapper 的潜在同一分配也需要对应证明。

操作连接规则：

| 情形 | 内容、对象、状态与物化的连接 |
| --- | --- |
| 普通赋值/alias | 传递同一 ObjectID；新 binding occurrence，不制造内容复制 |
| 已知透明 copy | 新对象/承载；证明保持载荷时可同版本；写入独立副本后产生新版本，不能污染其他副本 |
| deepcopy | 先走实际 dispatch 与 memo/object-graph 协议；自定义方法可能改值、写状态或 raise，不能按名字归并 |
| view/expand/transpose | 对象与区域新描述，保留共享 allocation 与 zero stride；通常新逻辑选择/形状版本及 VIEW 来源，不默认分配或内容相等 |
| cast/normalize/encode | 新值推导，显式输入和状态；量化/舍入一般改变载荷，不能默认保持版本 |
| in-place 写 | 从真实前驱状态和输入计算 post-state；重叠/可能重叠物化结束旧的有效区间，已证明不相交区域可保留 |
| NumPy/外部写 | 外部 alias 与逃逸加入 coverage；未观察写入时不能声称已发生 mutation，也不能声称未变；在未知边界保守切断稳定性证明 |

历史 ValueVersion 定义不因写入而消失；失效的是“此物理区域现在仍承载它”的事实。
不为保存历史定义复制大 tensor，不保存强对象引用。shape/少量样本可排除相等或
选择核验时机；样本相同、Torch `_version` 相同和 pointer 相同均非稳定性证明。

## 4. Resource 的三层身份和 handle

```text
ResourceDefinition { DefinitionID, kind, origin: declaration | creation_op | external_role }
ResourceRequirement { RequirementID, user: Operation/Region port,
                      kind, typed_constraints, relation_constraints }
ResourceInstance { InstanceID, kind, capture/process/context, lifetime,
                   parent_resource_relations, observed_identity_evidence }
ResourceRealization { definition_occurrence?, instance, evidence }
RequirementBinding { requirement, use_occurrence, instance, constraint_evidence }
ResourceHandleBinding { object_or_fd_identity_with_epoch, instance,
                        rights, ownership, state_interval }
```

Definition 是程序中的资源角色/创建定义；Requirement 是使用处的约束；Instance 是
实际共享实体。一个创建定义重复执行可产生多个 Instance，一个 requirement 在不同
occurrence 可绑定不同 Instance。外部 Instance 可以满足 requirement，无须伪造其
源内创建定义。Resource 状态仍用独立 StateLocation，不能把 Instance 当状态版本。

文件需要至少区分 namespace/path 绑定、文件实体、open-file-description、handle。
不同 path 可指同一文件；两次 open 可共享内容但 offset 不共享；dup handle 可共享
open-file-description/offset；fd 数字复用不沿用旧身份。关闭 handle 不等于删除文件，
flush/close 也不默认证明断电持久化。stream 需设备 context 与生命周期，不能仅用
Python wrapper 或 `cuda:0` 字符串当身份。

## 5. work、ready 与跨资源可见性

```text
WorkTicket { WorkID, issue_occurrence, executor_instance, queue_instance,
             queue_generation, ordered_dependencies, accesses }
ReadyRequirement { consumer_occurrence, required_work/access,
                   resource, visibility_scope }
ReadyCapability { work_or_event_generation, resource, visibility_scope,
                  established_by, happens_before_evidence }
```

host enqueue 正常返回只产生 work 身份；同 stream 的合法消费可由队列顺序满足依赖，
不要求多加 CPU synchronize。跨 stream 消费或 host 读取需对应范围的证据。重复记录
的 CUDA event 有不同 generation，不能凭相同 event handle 或名字“已完成”。异步
copy 的源区域在完成前保留读取/借用约束，目的区域在相应条件成立前不是有效就绪
副本；后续覆盖还会结束有效性。Work 完成与表示未被覆盖是两项独立条件。

## 6. 必须击穿的反例（规格验收，不是新增 backend）

1. `for ...: x.add_(1); f(x)`：ObjectID/AllocationID/静态 ValueID 可不变，每次读取
   的动态 StateVersion/内容版本不同；不得复用初值。
2. `a=np...; t=torch.from_numpy(a); a[...] = ...; f(t)`：Torch 版本可不变。
   未覆盖外部 alias 就保留未满足稳定性义务，不用采样通过替代写覆盖证明。
3. `b=deepcopy(a); b[0]=...`：初始载荷即使相等，也有独立可变对象和副本。
   自定义 `__deepcopy__` 更可写计数器或返回不同值；复制操作不能凭名字删除。
4. `v=x.expand(N,...); v[...]`：zero-stride view 不等于完整分配；写 footprint
   可重叠。按 numel 记独立存储或把 view 归为内容相同都会破坏正确性。
5. `float32 -> float16 -> float32`：shape 与前几个值可能相同，其余值/NaN payload/
   舍入不同。应有 TRANSFORM 推导，不能自动归并精确版本。
6. CUDA stream A 上覆盖 buffer 后，stream B 未 wait 即读取：相同逻辑内容声明不
   建立同步；旧 event generation 的完成也不能证明本次结果可见。
7. `dup(fd)` 与重新 `open(path)`：两者可读同文件，但 offset 共享关系不同；文件
   bytes 相等不使它们可互换。视频/tensor 写出均需有序写与关闭/失败状态接口。
8. 相同值的 cached Tensor 被调用方原地写，或 Tensor 的 autograd 关系不同：
   **内容相等不等于可替换物化**。替换还需 device/representation、identity/alias、
   ownership、lifetime、ready、梯度依赖及合同允许的效果一致。

验收顺序：先冻结上述身份与连接规则；再用独立构造/反例验证自动前端确实输出这些
接口；随后才讨论区域化简。当前代码的类型表、通过测试数或人工路径图都不能替代
这两道验收。
