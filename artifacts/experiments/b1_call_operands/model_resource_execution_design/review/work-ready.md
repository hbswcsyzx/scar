# R0：Work → Outcome → consumer readiness 独立设计审查

日期：2026-10-18；工作树 `/tmp/scar-structured-model-280qf4mi`。仅只读源码/文档并写本报告；无 git、Python、pytest、LeWM、GPU、采集或网络请求。

## 1. 有界结论

**Proposed：采用“Program 静态端口声明 + 现 v2 EEG 的 typed execution 关联”，不再造一套 ProgramGraph、producer 或 state。**
WorkTicket 是一次真实提交的工作身份，ResourceOutcome 是该 ticket 的资源执行结果，ReadyRequirement 是一个具体 consumer 的要求；ReadyEvidence 连接这三者的精确工作/内容/分配代次与可见域。它们不能合并成 enqueue 上的 `ready=True`。

Ready 有两种最小成立方式：**已完成且对该 consumer 可见**，或**该 consumer 的实际执行被协议排在必要 work 之后且满足其可见条件**。后一种不要求 CPU 已观测 Completed；不能把所有 ready 都强制写成 Completed→Ready 的链。Ready 可供多个 consumer 使用，不消费 ticket 或一张单次许可。

R1 应先交付有限、可校验的记录与手工 IR/evidence 组合；不以完整 scheduler、CUDA 自动采集、全部库协议或完整 occurrence 恢复作为前提。未闭合部分保留准确义务及证据空缺，不能伪造肯定事实。

## 2. Observed：现有实现与真实缺口

| 已读实现 | 已实现 | 不能据此推出 |
| --- | --- | --- |
| `program/resources.py:61–175`；`resource_validation.py:23–116` | 静态 ResourceDefinition/Requirement/Use/Location、handle 属于原 Operation 的准确 Use；同 owner 关系检查。 | 动态实例相同、跨 occurrence pairing、资源可用或工作完成。 |
| `v2/evidence.py:32–43,70–78,140–190,220–232` | OperationInstance、物化观察、typed HB/uses-resource 等证据边；外部节点注册。 | WorkTicket、queue/event generation、consumer visibility 或部分完成协议。 |
| `v2/correspondence.py:20–57` | definition↔instance、source↔instance、slot↔logical-version。 | Program OperationID/UseID/StateVersion 的精确 occurrence→materialization 桥。三个现有 kind 不足以隐式补齐此桥。 |
| `v2/values.py:106–159` | allocation/region、Materialization→ValueVersion、可选 producer、`ready_event: str`。 | ready_event 是有类型完成证据；allocation 地址/可选 lifetime_scope 已证明生命周期。 |
| `ir/provenance.py:305–340,600–635` | allocation lifetime witness、结束时 invalidate；mark_ready 仅接受 Observed kind；guard 仍检查 mutation coverage。 | mark_ready 已核验正确 work/event generation 和 consumer visibility。它当前只写 READY 及 event label，不能升级为本门 typed-ready 校验。 |

这不是本轮复现的运行缺陷，也不改旧接口解释。主规格已明确这些边界：`WHOLE_PROGRAM_MODEL.md:303–320`、`RESOURCE_PROTOCOLS.md:295–335`、`FIRST_STAGE_COMPLETION_MATRIX.md:29–31`。

## 3. Proposed：最小字段关系

以下是可实施草案，不是现成 API，也不是本轮冻结字段。普通不可变 typed records、exact IDs/tuple、判别联合；避免用裸字符串保存 machine facts。

### 3.1 静态层只索引 canonical 定义

```text
WorkSite = (operation: OperationID, slot: nonnegative int)
WorkInterface(
  site: WorkSite,
  executor: existing ResourceRequirementID,
  queue: existing ResourceRequirementID | None,
  resource_handles: tuple[owned UseID, ...],
  effects: tuple[CanonicalEffectRef, ...], rule: VersionedProtocolRef)
CanonicalEffectRef = Access(operation, access_index)
                  | CompletionState(operation, kind, result_index)
ReadyUse(operation, consumer_use: UseID,
         access_index: int | None, visibility: TypedVisibilityRequirement,
         rule: VersionedProtocolRef)
```

- WorkSite.slot 区分一次 host operation 可能提交的多个工作种类；同 site 在循环多次执行，不能共用一个动态 ticket。运行时可变个数用 ticket 的 scoped ordinal 区分，不把个数硬编码成静态结果列表。
- Use 必须是此 Operation 原有 Use，effects 必须准确索引其 StateAccess，或其真实 NORMAL/RAISE CompletionSignature 中 State 端口；不复制一份 before/after、footprint 或结果列表。
- ordinary reference 结果、真实 completion 结果或库内 opaque 工作均可参与提交；ticket 不强制对应 Python 返回 handle。失败前已提交但未返回 handle 的工作不能消失。
- 队列、event、allocator、buffer 的可变状态仍只在既有 StateLocation/StateVersion/StateAccess 中。ResourceLocation 是对应关系，不证明 selector/动态 owner 相等。
- 同一个静态 operation 同时可能有 host return、部分状态和多个未完成 work；不要把一个 WorkSite 定义直接写成肯定提交，也不要把正常返回枚举改名为资源 Completed。

### 3.2 execution 层记录发生及来源

```text
ProgramOccurrenceBinding(operation: OperationID,
                         instance: OperationInstanceID, evidence: EvidenceClaim)
UseOccurrence = (owner: OperationInstanceID, use: UseID)
WorkTicket(id: WorkTicketID, site: WorkSite, enqueue: OperationInstanceID,
           ordinal: nonnegative int, executor: ResourceLifetimeRef,
           queue: ResourceLifetimeRef | None,
           dependencies: tuple[WorkTicketID, ...],
           outputs: tuple[MaterializationBindingRef, ...], evidence: EvidenceClaim)
ResourceOutcome = Completed(ticket, witness)
                | Failed(ticket, diagnostic_ref, partial_effects_ref, witness)
                | Cancelled(ticket, protocol_result_ref, partial_effects_ref, witness)
ReadyRequirement(consumer: UseOccurrence, materialization: MaterializationID,
                 visibility: VisibilityTarget, required_work: tuple[WorkTicketID, ...],
                 writer_coverage: ProofClaim)
ReadyEvidence(materialization: MaterializationID, visibility_scope: VisibilityScope,
              basis: CompletedVisibility | OrderedVisibility,
              establishing: ExistingExecutionPoint,
              rule: VersionedProtocolRef, evidence: tuple[EvidenceClaim, ...])
```

- `WorkTicketID` 是新的独立 EEG 身份；不是 OperationID、OperationInstanceID、ResourceID 或 MaterializationID 的别名。执行 scope 来自所属 evidence bundle/run；跨 bundle 必须显式 scope，不接受字符串同值拼接。
- queue=None 只用于明确的无队列执行合同，不为同步 CPU 工作捏造 queue；queued profile 必须有准确 queue。ReadyEvidence 不绑定一个独占 consumer；查询对每个 requirement 选取匹配 evidence 并逐项重检，便于合法复用。
- ProgramOccurrenceBinding 是现 Correspondence 的必要 typed 补充；核验 instance 所属 semantic definition 与 Program source/provider 对应，歧义保留 `ambiguous/unresolved`，不按 op 名或时间戳猜配。它不要求先完成自动桥接；R1 可明确提供声明绑定并标 Declared。
- UseOccurrence 精确锚到一次消费的原 Use；state 输入由该 Use/Access 的当前 StateVersion 派生。不能用“这轮所有版本集合”替代有序实际绑定。必要输出物化绑定指向原 ordinary/completion port 的该次结果，不造另一处 producer。
- `MaterializationBindingRef` 引用 occurrence/denotation 对应；从既有 Materialization 取 ValueVersion，从 StorageRegion 取 Allocation，不重复保存可矛盾的 logical version/allocation 字段。字段缺失时给出具体未解析引用/义务。
- `ResourceLifetimeRef` 指向已有 v2 ResourceID 的该生命周期证据；静态 ResourceDefinitionID 不能冒充动态 executor/queue。allocation 沿现 StorageAllocationID 表示一次生命周期；证据不足时不能凭 allocator_token/地址相等认同一代。
- event generation 至少是 `(event ResourceLifetimeRef, record OperationInstanceID, marker ordinal)`；queue 的 generation/prefix 至少锚其生命周期及实际提交/record/wait 时点。整数或名字本身不是证据。
- 若引用的是实际外部完成点而非 Python 操作，使用 typed execution point；不虚构一次 Python OperationInstance。现 CONTROL_EVENT 字符串端点不能自动授完成语义。

### 3.3 basis 必须区分两类证明

`CompletedVisibility` 引用必要 ticket 的准确 Completed outcome + 把输出引入指定 consumer domain 的实际操作/封闭规则。`OrderedVisibility` 引用 ticket、recorded event generation/queue prefix、真实 wait/order 操作及 consumer execution domain，证明必要 work 会在该 consumer 实际访问前完成且可见；不产生一条虚假 Completed 观察。

`VisibilityTarget` 最少区分 `Host(context)`、`Queue(resource lifetime, consumer occurrence)` 与 `Persistence(endpoint, durability contract)`。device 完成、host 可读、buffer flush、OS 接收、持久化是不同命题，不应放进一个线性 READY 等级。consumer 可见也不证明输出数值符合预期或不含未报告错误。

## 4. 最小严格算法与失效

1. 先 core/schema/引用检查。复用 `model.py:349–397` 的 Use/StateAccess；`validation.py:425–460,519–540` 检当前状态、所有域和异常新后态。core 只检查程序结构，未给 resource HB。
2. 校验 WorkSite→原 Operation、execution instance→site、原 Use 所有权及物化 occurrence 的 scope/pairing。每个 ticket 只对应一次提交 occurrence+ordinal；一个 enqueue 可以有多个 ticket，一个 static site 可以执行任意多次。
3. 验证精确资源 lifetime、event record generation 和 queue prefix 的 typed 关系。HB 只来自带版本/适用条件的真实协议或证据，不从 start/end_ns、同 stream 名、host 顺序或 `OrderEdge(OperationID,OperationID)` 推出跨资源完成。
4. 对每个 ReadyRequirement，将 consumer 原 access footprint 映射到物化区域；要求所有相关 writer/dependency 已覆盖。`required_work` 是显式下界，不因列了一个 producer 就默认为完整；writer_coverage 未闭合则结果不能为 satisfied。
5. 在有限已知 ticket/event/order 关系上作带 rule/domain 的可达性闭包：Completed 分支另检可见；Ordered 分支要求每个必要工作到精确 consumer 的有效路径。两条事实只因各自终点/owner 相同才可组合，不能 union 工作集合和 consumer 集合后交叉配对。
6. 多 writer 的必要集合取 AND，不取“任一 ticket 已完成”。同 queue 不免除前后写依赖；跨 queue 只覆盖实际 wait 所捕获的前缀，不覆盖随后新提交。循环的前一 visit event/marker 不能证明新 visit，有限观测域无 seed 不凭 cycle 造 ready。
7. 检 exact materialization/version、allocation lifetime、consumer point 与 mutation/alias coverage。任一相关覆盖写、新内容 version、allocation 结束/复用、未知外部 alias 写，使旧证据不再支持这次新消费；已观测的历史完成事实不删除。
8. 无法证明 disjoint 的写按可能相关处理；R1 可先 coarse invalidate。若精确 footprint 和无 alias 证据足够，可保留不相交部分，但不能以 LocationID 不同授 disjoint。
9. 证据可被多个 consumer 使用，只分别重检 scope/domain/版本/当前内容条件；不实施单次消费或 consumed 位。一次 ReadyEvidence 可作为多个 requirement 的 basis，但不能扩大其原覆盖域。

### canonical state 与异步时刻

enqueue 的 canonical after-state 可表示“当前状态含待完成工作/目的内容承诺”，**不能同时宣称内容已经稳定可读**。Ready 是对此状态/物化在某 consumer 上是否可用的额外关系；无需另造 work.after-world。
真实 wait/query/helper 若读写队列或可见状态，继续通过其原 StateAccess/INVOKE 产生 after；纯外部完成观察只描述原 effects 的资源实现，不成为第二个 StateVersion producer。未有源码操作展开时保留 typed opaque boundary，不能捏造同步 call 来让状态图看似闭合。

Host Threw 可能已有 ticket 和部分写；Resource Failed/Cancelled 也可能已有部分输出。ticket 无 outcome 仅表示 outcome 未提供，不自动表示 pending、确定未完成或永不完成。取消请求不等于 Cancelled，更不等于 quiescent/free；借用/retention 的撤销需独立协议证据。异步错误若后来从某 host INVOKE RAISE 报告，需要明确关联，不能按最近报错行归因。

## 5. 具体反例与最小规则

| 反例 | 最小拒绝/保留条件 |
| --- | --- |
| enqueue 正常返回；kernel 仍在运行；立即 host 读结果。 | Returned 不种 Completed；缺 host visibility 义务仍 UNKNOWN。 |
| Q1 producer→同队列/正确 wait 后 Q2 consumer；CPU 从未 synchronize。 | 可以 OrderedVisibility 满足该 device consumer，不误拒为“必须 CPU 完成”；host 读仍未获准。 |
| event E 记录 g1 后复用 g2；用 g1 wait 解释 g2 的工作。 | marker 必须匹配 record occurrence+generation+所覆盖前缀；同 E handle 不够。 |
| 两个 work 分别写物化左右半区；只完成左侧便声明整体 ready。 | 完整消费要求两个 writer 全覆盖；不能用单 producer 字段代替多工作。 |
| wait_stream 取了旧前缀；对方后来又向同 buffer 提交写。 | 新 ticket 不在捕获 cut；新 writer/内容 version 使当前 requirement 未满足。 |
| 两个 wrapper 都叫 default stream，但 context/lifetime 不同。 | 真实 queue/resource occurrence pairing 缺失，不授相同队列顺序。 |
| host 提交一项工作后下一项抛错；异常路径丢掉先前工作。 | RAISE 保存实际 partial states 与已提交 ticket；不自动回滚/取消。 |
| cancel 返回成功，但设备仍可能访问旧 source allocation。 | 需要取消结果和实际 quiescence/borrow-release 条件；不能推出可复用承载。 |
| M(v1) ready；in-place 写成 v2 或相同地址换 allocation lifetime；沿旧 ready_event 使用。 | exact 内容/物化/分配生命周期匹配，外加相关写 coverage；旧事实只保留历史意义。 |
| buffered write/flush/close 返回；声称文件在故障后一定恢复。 | 不授 Persistence；需要同 endpoint/version 的特定 sync/durability 合同，不能由 device/host ready 代替。 |

上述是模型反例，不是本轮 native/GPU 实测。涉及队列、wait_stream、record_stream 和文件规则的依据为已读本地协议分册 `RESOURCE_PROTOCOLS.md:225–248,321–335`；本报告不新增具体 CUDA/文件系统版本的事实证明。

## 6. 证据缺失怎么保留

沿用 `EvidenceClaim.kind` 与 `ProofClaim.status` 两轴（`common.py:29–46,83–123`）。Declared/Observed 说明来源，不等于该 readiness 命题 PROVEN。
返回 requirement、已知 ticket/版本/消费端口、basis 候选和逐项缺口，例如 `missing_event_generation`、`unpaired_queue_lifetime`、`unresolved_materialization_binding`、`writer_coverage_partial`、`missing_host_visibility`、`cancel_quiescence_unknown`。不能只给无内容 UNKNOWN，也不能以无 Completed 记录判 DISPROVEN。
结构矛盾（错误 Use owner、跨 scope、已知代次不符、物化版本矛盾）是 invalid；证据不足是合法未闭合接口。对“必须 ready”的 consumer 可报告未满足义务，不能把原程序/静态图一律判非法。当前旧 `ready_event` 和 mark_ready 不自动生成 typed ReadyEvidence。

## 7. 有限 R1 验收建议

交付：上述静态引用与 execution 关系的严格 records/codec/query，绑定一个手工 canonical enqueue→NORMAL/RAISE→wait/consumer IR；无需 scheduler、GPU 或新 backend。

1. 普通/INVOKE 两类 canonical state anchors、准确 Use query、显式 Declared pairing；坏 IDs/端口/跨 occurrence scope 拒绝，不复制 producer。
2. 同一 enqueue 多 ticket、同一 static site 两次执行不同 ticket；event g1/g2 正反例。
3. 一个 Completed、一个正确 Ordered consumer 正例；缺 visibility、host/device 混用反例。
4. 两个 writer/跨队列 AND、捕获 prefix 之后再提交、两次 consumer 合法复用。
5. RAISE 前已提交工作、Failed 部分状态、cancel request/Cancelled/quiescence 区分。
6. M(v1)→覆盖 v2、allocation 地址复用、未知 alias 写失效；持久化要求不被 flush/close 冒充。
7. 无事件/物化/writer 证据仍能 roundtrip 并准确列义务；旧 wire 不自动授新 capability。

这只关闭“声明结构与有限组合”分母。实际 resource instance/denotation 自动恢复、协议版本对应、测量覆盖、资源完成/可见性运行证据与优化授权分别保持未证；不要求先造完整编译器来实施 R1。

## 8. 本次绑定的源 SHA256

```text
docs/M1_RESOURCE_INTERFACES.md b8d02ddf84e6368cd08b4b2127d5a77458e8b5de3847f713573be8318bc931e5
docs/model/RESOURCE_PROTOCOLS.md 5033fd3221d112dcebcbf087788440d7545effc88330dff589ed3ed4cdd482e4
docs/WHOLE_PROGRAM_MODEL.md ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509
docs/FIRST_STAGE_COMPLETION_MATRIX.md 256a6486bed0429e90f50ce7a5a1a892f13f9ad52fe95a80cd55b15da566b862
scar/ir/v2/evidence.py dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5
scar/ir/v2/correspondence.py 7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5
scar/ir/v2/values.py 2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259
scar/ir/v2/ids.py d11e038a6a4c7de6dee5c8050182a97ddb4a6a6a399c466836ca64d6d9cb0a23
scar/ir/v2/common.py 691a7ec169c81cb51e271731ea11ee4c2aed38b5553b1f48f072a8ff368979b9
scar/ir/program/ids.py 927b81d1ce9e3f821557052ee53db6ae80ee7a4f3d4435fc2fc918f54b359400
scar/ir/program/resources.py 167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f
scar/ir/program/resource_validation.py f2709a6d9e9898bc5ecb87ae2396510750550fde1bb071f8ab9808569f352c39
scar/ir/program/model.py 3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1
scar/ir/program/validation.py 04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264
scar/ir/provenance.py f8f11d353a05c9b2ec893ae5ab3da7be747b4a2ea3b28a21eb1f7891237523c1
scar/analysis/region_queries_v2.py d110d948730fe0e5ab121a5545dd9299eb5263397c68ae2a5c8378996cb5e546
```
