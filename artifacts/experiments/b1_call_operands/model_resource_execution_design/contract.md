# 资源执行合同 R0

**状态：R0 关系合同；具体 wire/records 在 R1/R2 验收。** 基线 `309fb35`；
本文件定义下一批接口关系，不声称已有 ResourceInstance/WorkTicket/typed-ready 产品。
六个本机 stdlib 见证
已运行；CUDA 规则只核对官方协议和本机安装源/header，没有运行 GPU 实验。

## 1. 规范实体不变，补足跨层关系

ProgramGraph 是程序定义图，仍以原 Operation/Value/StateLocation/Region/Resource
及 Use、StateAccess、CFG 为规范来源。ExecutionModel 是这些定义的发生、实例和
关联；EvidenceGraph 保存工具的观测，不按 ID 名字与发生层合并。

```text
ProgramGraph（有版本的静态定义）
    ↓ definition / occurrence（精确外键）
ExecutionModel（activation、visit、resource lifetime、work、order）
    ↔ explicit scoped correspondence ↔ v2 EvidenceGraph / provider facts
    ↔ existing ValueGraph（logical version / allocation / materialization）
```

operation-centric 显示图可投影这些关系；没有第二套可修改的 producer/use/state。
同一个原生或 profiler event 可对应多个 core occurrence，反向也可一对多。未能
对应时保存 Unresolved(reason, scope, original_fact)，不捏造 core 操作或缺省纯性。

新 bundle 显式登记 program、values、evidence/contract 的 ProviderArtifact。跨 bundle
端点使用 `(artifact digest/schema, exact typed ID)`，单 bundle 内可由准确 owner 派生
artifact；相同 `mat:x`、`alloc:x`、`opinst:x` 文字不跨 artifact 自动合并。证据引用
使用 ProviderFactReference + typed execution/capture scope；旧裸字符串只保留原文，
不作新接口外键。下文 Unresolved 各分支携 reason、准确 scope、原事实引用（没有
原事实时明确 MissingEvidence），不是省略字段或已知空集合。

## 2. 最小发生基础：定义不是运行身份

以下记录均 frozen/exact typed；ID 为不复用的 opaque identity，不以计数器顺序
推出 happens-before。raw pid/tid、pointer、fd、clock timestamp 只作诊断或证据。

| 记录 | 字段及含义 |
| --- | --- |
| ProgramSnapshot | canonical core artifact（复用 ProviderArtifact）及其准确 schema/digest；验证绑定传入 ProgramGraph 的字节，不凭源码路径猜同图。 |
| ExecutionRun | 新 RunID；一次明确采集/执行的命名域。window/clock 是证据范围，不定义对象或资源生命周期。 |
| ProcessInstance | 新 ProcessInstanceID、RunID、实际进程 incarnation 的来源；raw pid 可复用，不能单独作 key。 |
| HostThreadInstance | 新 HostThreadInstanceID、准确 ProcessInstanceID、线程 incarnation 依据；raw tid 仅诊断。实际线程已有此身份时，资源引用复用它，不再 mint 平行线程实例。 |
| RegionActivation | 新 RegionActivationID、snapshot、RegionID、ProcessInstanceID、入口来源。表示实际进入的区域发生；body 创建而未进入不伪造 body activation。挂起/恢复保留本 body activation，新的恢复 visit/segment 不合并 caller context。 |
| ExecutionSegment | 新 ExecutionSegmentID、activation、`HostThreadInstanceID | UnresolvedHostThread`、typed ingress（InitialEntry / ResumeIngress / CaptureIngress）。每次恢复为新 segment，普通 CFG 转移不凭空换 segment；同 activation 的不同恢复可在不同线程/当前 caller 上。缺失 thread 来源不能伪造身份或授该 thread 的顺序/可见性。 |
| BlockVisit | 新 BlockVisitID、ExecutionSegmentID、准确 BlockID；activation 沿 segment 派生。同 loop block 多次进入为不同 visit。入口或真实 predecessor transfer 是来源，缺失则明确 unresolved。 |
| OperationOccurrence | 新 OperationOccurrenceID、BlockVisitID、原 OperationID；验证静态 block ownership 与动态 visit。原 op 在同 block 的准确位置派生，不另填 producer。 |
| ValueOccurrence | 新 ValueOccurrenceID、原 ValueID、定义发生。OperationResult 对应准确 occurrence/result；BlockArgument 对应准确 visit/formal；literal 对应该 activation 的定义范围，不凭 spelling 合并 object identity。 |
| UseOccurrence | `(OperationOccurrenceID, 原 UseID)`；实际读取的 ValueOccurrence。静态 Use 的 owner/value 必须吻合；`f(x,x)` 保留两个有序端口。 |
| AccessOccurrence | `(OperationOccurrenceID, 原 StateAccess index)`；before Use 与 after ValueOccurrence 只沿原访问解析，不复制 mode/location/footprint 或造新 state version。 |
| ExecutionPoint | `BEFORE/AFTER(OperationOccurrence)` 或 `EDGE(OperationOccurrence, actual successor index)`，以及带准确证据域的 capture/import/native EvidencePoint。EDGE 必须对应原真实 CFG/completion，不能默认 NORMAL=index0；native 点不伪装成 Python 操作。 |

Transfer 指准确 predecessor occurrence/successor index 与目标 BlockVisit。
actual Use/CompletionResult/ResumeInput 到 formal 的关系从原边派生，不能另填任意
value route。caller completion、callee body completion 和资源 outcome 保持不同类型。
partial trace 不推断未观测的 transfer，也不把 absent completion 变成正常结束。

ProgramSnapshot 明确采用 UTF-8、无附加 newline 的当前 canonical core `dumps(graph)`
字节，绑定准确 `scar.program-graph` schema_version、SHA256、size；验证先 require_valid，
再重新编码比对。旧 raw artifact 有不同空白时单独保留原 digest 与 normalization
对应，不冒称两者同 bytes。constructor 不打开 URI；R1 validator 校验实际传入图。
ExecutionSegment 的 resume ingress 连接原 BodyDrive/Suspend successor 等真实端口及
当前状态/context，不复制 yield 时 world 或旧 caller；unresolved capture 不补造入口。

旧 `v2.OperationInstanceID/OperationDefinitionID` 与新的 core occurrence 不同。
`InvocationKey/CallRecordAnchor/ReferenceOccurrence` 可作旧采集的局部来源，但它们
不具备上述全部定义/visit/state 义务。显式对应关系保留双端、scope、依据、缺口和
歧义，不能给旧事件换一个前缀就声称 source/runtime 已对应。

R1 只落实发生及资源接口结构，不实现完整 source lowering、trace reconstruction
或 denotation。资源相关 StateOccurrence 使用 ValueOccurrence 对应的原 StateVersion，
不会把它冒充逻辑 ValueVersionID；数据 denotation 的完整桥仍是后续独立义务。

## 3. Resource identity、realization 与 handle

```text
ResourceInstance(id: ResourceInstanceID, kind, role,
                 identity_realm, origin, identity_evidence)
ResourceOrigin = CreatedAt(OperationOccurrence) | ImportedAt(ExecutionPoint)
               | UnresolvedOrigin(reason, original_fact)
IdentityRealm = RunRealm(RunID) | ProcessRealm(ProcessInstanceID)
              | ExternalRealm(ExternalRealmID, namespace_definition: ProviderFactReference)
ResourceTarget = Instance(ResourceInstanceID) | Allocation(StorageAllocationID)
               | Process(ProcessInstanceID) | Thread(HostThreadInstanceID)
ResourceRealization(definition: ResourceDefinitionID,
                    binding_site: owner occurrence/activation entry,
                    target: ResourceTarget, evidence)
RequirementBinding(requirement: ResourceRequirementID,
                   owner: exact operation occurrence / RegionActivation entry,
                   target: ResourceTarget, constraint_obligations)
HandleEndpoint = ObjectReference(ValueOccurrence, existing ObjectID)
               | NativeDescriptor(ValueOccurrence, namespace, NativeHandleLifetimeID)
               | UnresolvedHandle(ValueOccurrence, reason, original_fact)
HandleBinding(handle: HandleEndpoint, target: ResourceTarget,
              rights, ownership, start: ExecutionPoint, end: ExecutionPoint | unknown,
              current_state_support, validity/coverage, evidence)
ResourceAccessBinding(operation: OperationOccurrenceID,
                      requirement_binding: exact binding key,
                      handle: ExplicitHandle(exact binding key)
                            | ImplicitBinding(original rule/selection-state refs)
                            | UnresolvedHandleAssociation,
                      current_state_support, constraint_evidence)
```

1. ResourceInstanceID 已标一个资源生命周期，**不再给相同生命周期叠加另一个可变
   generation counter**。新的真实生命周期产生新 ID；同实例状态 open/closed/
   capacity/offset 等变化由已有 StateLocation 版本表达。runtime 地址、fd 数字或
   device 字符串相同不使 ID 相等。identity realm 属 run/process-incarnation 或有
   依据的外部身份域，不属于 observation window 或 clock。realm 是身份命名域，
   不表示所有权或在该 activation/window 结束即销毁。
2. 一个静态创建定义重复执行可产生不同实例；静态 ID 不证明实际同一或不同。
   realization 的 binding site 必须对应原定义的提供操作/外部 Region 端口；实例
   首次创建与每次取得/别名引用分别保存。不得因一次取得已有资源又伪造新创建。
   没有新鲜性证据不靠 `CreatedResource` 名字推断 fresh。
3. Region-owned requirement 按**准确 owner activation**绑定，其内部 ResourceUse
   解析同一次入口身份绑定；不能每 use 改绑，也不能从词法嵌套猜最近 caller。
   capacity/rights/open 等当前约束仍在每次 resource access 的状态上重新核对，
   不能由入口绑定承诺整个 activation 永久满足。资源可
   经闭包/参数逃逸并活过创建 activation，生命周期不截断在函数返回。
4. handle lifetime 与 referent lifetime 分开。dup 可产生新 handle lifetime 并指向
   同一 open-file-description；不同 open 可指同一 file entity、不同 description。
   关闭一个 handle 不推出其他 handle 或 referent 已结束；复用原 fd 必须是新
   handle lifetime。end 未知不证明还活着；无覆盖证据的图外 close/write 保留缺口。
5. file entity、open-file-description、路径绑定和 descriptor 是不同角色：路径是
   数据，路径解析是状态，offset 属 description；rename/replace 不改已打开 handle
   的 referent。相同路径字符串不证明资源/内容版本相同。
6. 内存已有 StorageAllocationID，继续标一次 allocation 生命周期；**不为同一
   allocation 再 mint 平行的 ResourceInstanceID**。memory pool/device/queue 可用
   新资源实例，AllocationPlacement(allocation, pool/device instance, evidence)
   连接承载关系；不是 same-identity。Materialization 仍沿原 StorageRegion 解析
   allocation/shape/strides。ResourceRole/MEMORY_POOL 的 requirement 不能绑定成
   某个 allocation；tagged target 的类别和角色必须吻合。
7. raw OS fd 是数据/协议返回而非 Python object reference；HandleBinding 可接
   精确 descriptor ValueOccurrence，不能强迫给整数捏造 ObjectID。Python wrapper
   已有 ObjectID 生命周期，不额外给同 wrapper mint 一个 handle lifetime；它的
   状态可变时允许同对象后续重新绑定。fd slot lifetime 与底层资源另有依据地关联。
   ResourceUse.handle 当前只接受 ordinary reference；descriptor 动态关联可准确引用
   原 Data/Protocol Use，但不假称旧静态 handle 字段已支持它。静态扩展若需要，须
   明确版本化，不能通过修改旧字段解释破坏历史合同。

ImplicitBinding 用于原 ResourceUse.handle=None、通过当前 executor/queue 等隐式
选择资源的本次访问；不制造 ValueOccurrence，也不把“无显式 handle”当未知。
它只说明本次 core 端口没有显式 handle，不推出底层 native 没有 handle；原 static
handle 已声明时不能借此绕过 ExplicitHandle 的准确 Use 对应。选择依据缺失时用
UnresolvedHandleAssociation，其形状不强制不存在的 handle ValueOccurrence。

NativeDescriptor.namespace 使用准确 Process/Resource identity realm 下的 typed
handle namespace（协议 ProviderFactReference），不是任意名字。ObjectReference
必须有相应 reference occurrence→ObjectID 的依据，NativeDescriptor 则依该 namespace
的 scalar/protocol denotation 与 slot state；缺对应时使用 UnresolvedHandle。

rights 为 RightsClaim(tuple[ProtocolRight], Completeness, StateSupport, evidence)
或 UnresolvedRights。ProtocolRight 指有版本的协议及成员 FactReference，不能
以任意 label 授权；空 known set 与 coverage 未知不同。ownership 是一组带 holder
的 OwnershipClaim 或 UnresolvedOwnership：holder 为原 ObjectID、native handle
lifetime、ResourceTarget、activation 或 work；ReleaseAuthority（OWNED/BORROWED/UNKNOWN）
与 Sharing（EXCLUSIVE/SHARED/UNKNOWN）分开，owned 不蕴含 exclusive，也不是 refcount。

StateSupport 是指原 StateVersionValue 的 ValueOccurrence tuple；claim 不存状态
payload。ConstraintRef 严格索引原 requirement 的 capacity/relation tuple，或有版本
协议签名的 condition（及其原 canonical operands）；所需集合从原 requirement/profile
派生，不能删 obligation 换取 satisfied。kind/role、同owner关系仍按原记录校验；
device/rights 等旧表尚未支持的静态约束不得冒充已存在，后续扩展须显式版本化。
要求/观测都引用 canonical current-state support；两个已知点有效也不证明中间整个
interval 有效，缺口与图外 close/write 不能被 start/end 吞掉。

identity_evidence、constraint_obligations 和 validity 是声明/观测/推导各自的依据，
不是填上 PROVEN 即获授权。相冲突的 claim 不覆盖旧行；解析返回冲突及来源。
结构 validator 校验外键/角色/代次/边界，实际身份及动态约束满足留独立 evidence。

## 4. 工作提交、终结与效果

```text
SubmissionOrigin = WithinOperation(OperationOccurrence, physical_submission_fact)
                 | ExternalWorkSource(scoped EvidencePoint)
CanonicalEffectOccurrence = AccessOccurrence
    | InvokeBoundaryStateEffect(invocation: OperationOccurrence,
                                input_state: exact UseOccurrence,
                                post: ActualCompletionState | UnresolvedPost)
ActualCompletionState = actual successor/result index -> original State formal occurrence
WorkSubmission(ticket: WorkTicketID, origin: SubmissionOrigin,
               executor: exact ResourceAccessBinding ref | UnresolvedExecutor,
               scheduling: Queued(exact queue binding/prefix)
                         | DirectExecution(exact host/executor) | UnresolvedQueue,
               dependencies: explicit work/order refs,
               effects: CanonicalEffectOccurrence refs,
               materializations: original MaterializationID refs,
               retention: work-holder OwnershipClaim refs | UnresolvedRetention,
               alignment/coverage obligations, rule/evidence)
ResourceOutcome(ticket, kind: COMPLETED | FAILED | CANCELLED,
                observed_at: ExecutionPoint, diagnostic?,
                protocol_result: exact scoped value/fact ref | UnresolvedResult,
                effect_frontier: canonical access/output refs,
                quiescence/visibility obligations, rule/evidence)
```

- ticket 是一次工作身份，queue lifetime 与该次工作不同；同 enqueue op 反复执行
  必须区分 occurrence/ticket，不能绑定到静态 op 或 event 名称。
- 同步 CPU 等明确无队列的协议可用 DirectExecution；缺队列证据使用 UnresolvedQueue，
  不能把 unknown 写成 NoQueue 或为所有 CPU 动作捏造 stream。具体资源访问仍接
  准确 requirement/当前 state；queued profile 不能省略实际 queue binding。
- 一个 host call 可提交零个、一个或多个 work；host NORMAL/RAISE 不是上述 enum。
  真实 RAISE 前可能已提交部分工作，必须保留 ticket 及实际部分后态。没有观察到
  完成不伪造 Failed/Cancelled，也不把超时当终结。
- submission 在 opaque call 内部可早于 host 完成，WithinOperation 仅表达归属及
  具体提交依据，不强行把提交移到该 call 的 BEFORE/AFTER/最终 EDGE，也不从多个
  ticket 的记录顺序推出设备顺序。物理子事件未对应 core 时保留 ExternalWorkSource。
- core INVOKE 禁止普通 StateAccess/results。其状态输入引用原 invoke_arguments 中
  的准确 Use，post 必须接实际 NORMAL/RAISE CompletionResult→landing formal；未
  完成或证据截断时用 UnresolvedPost，不造普通 access、虚假 NORMAL 或新 producer。
  InvokeBoundaryStateEffect 是边界关联而非 read/write/footprint 证明；未知效果仍
  为 UNKNOWN，物理工作与该粗粒度状态的精确匹配另列义务。
- effect_frontier 只指原 Access/Use/结果及相应物化匹配，不重写 StateAccess，
  不把 enqueue after 的 SSA producer 移到 wait。host after 与数据物理可读是
  独立关系；可有尚未 ready 的 tensor/reference。
- 部分失败/取消不抹去写入。Cancelled 不普遍保证已经 quiescent 或无输出，
  error-reporting 的 host 操作也不自动是导致错误的工作；两者关联须有依据。
  COMPLETED 只表该 ticket 的协议终结；例如正常部分 write 的实际长度仍取原
  protocol_result/effect frontier，不能据标签认定整个请求区域或逻辑输出已产生。
- pending work 可借用源/目的 allocation、handle 或其他资源，retention 关联沿原
  Use/effect/物化指向同一 target；保持到对应 quiescence/borrow-release 依据或明确
  unknown end。host 局部变量离开、ticket outcome 标签或 Ready 均不自动结束借用。
  这是一条资源实现关系，不重建资源状态余额；未恢复 retention coverage 不默认为空。
- access/物化匹配未知时保留 opaque boundary 的准确输入、共享状态、资源和
  completion frontier；不制造空 access set 宣称工作无效果。

## 5. 有序可用、完成与消费者 visibility

```text
EventRecord(event_instance: ResourceInstanceID, record: EventRecordID,
            recorder: ExecutionPoint, captured_work/frontier, rule/evidence)
OrderEdge(before: work/event-record/queue-prefix,
          after: work/precise consumer queue-prefix,
          establishing: ExecutionPoint, rule/evidence)

ObservationRoot(id: ObservationRootID, contract: scoped existing ContractID,
                endpoint: ResourceTarget, content/selector: canonical refs or Unresolved,
                observation_point: ExecutionPoint,
                protocol_requirement: exact versioned condition ref, evidence)
ConsumerTarget = CoreUse(UseOccurrence) | CoreAccess(AccessOccurrence)
               | ExternalObservation(ObservationRootID)
               | UnresolvedObservation(exact known endpoint/point, obligation)
Placement = StorageBacked(MaterializationID)   # region/allocation 从原 ValueGraph 派生
          | EndpointBacked(MaterializationID, exact resource endpoint,
                           canonical selector/state support, placement evidence)
          | UnresolvedPlacement(MaterializationID, obligation)
ReadyRequirement(consumer: ConsumerTarget,
                 content: original logical ValueVersionID,
                 placement: Placement,
                 required_contributions, visibility_domain)
ContributionSupport = CompletedVisibility(outcome refs, visibility establishment)
                    | OrderedVisibility(order chain, exact consuming queue/prefix)
ReadyEvidence(required content/materialization/allocation,
              covered_contributions, visibility_domain,
              support: per-contribution ContributionSupport alternatives,
              validity/coverage, rule/evidence)
```

1. EventRecordID 是一次 record 代次，ResourceInstanceID 是 event 的生命期；不同
   record 不覆盖为同一个 key。wait 绑定调用时捕获的确切 record，不回头改成该
   event 后来记录的工作。query 一个从未 record 的空 event 返回完成，也不能证明
   任意工作已完成。queue prefix 由准确工作/提交范围界定，不用名字或时间戳排序。
2. **同队列顺序或精确跨队列 wait 可使未来设备消费有序**，不要求 CPU 已观察
   ResourceOutcome.COMPLETED。OrderedVisibility 只适用相应 consumer queue/prefix；
   不能因此授 host read、别的 queue、flush 或 persistence。单纯 completed 也
   不自动满足所有 visibility domain。
3. 多个工作贡献一个区域时，required_contributions 是 AND，coverage 必须覆盖
   consumer 所需 footprint；不能只拿一个 writer 的完成给整个 Tensor ready。
   每个贡献可有多个替代合法 support（OR），各贡献可分别采用 CompletedVisibility
   或 OrderedVisibility，再对全部必要贡献合取（AND）。不能强迫所有贡献走同一种
   basis，也不能将不同 work 集合与 consumer 集合分别 union 后交叉授予可见性。
4. ReadyEvidence 可被多个合法 consumer 使用，不是一次性 permit。匹配必须核对
   同 content version、materialization、StorageRegion/allocation lifetime、visibility
   和 scope。新内容写入/分配生命周期结束/未知 alias 写会使旧支持不再满足新要求；
   不能按 Tensor `_version`、pointer 或 event 字符串跳过这些检查。
   已知 FAILED/CANCELLED 且贡献不足时，正确的 order chain 也不能凭空补出完整
   content；有足够依据的部分 footprint 只满足相应部分要求。尚无 outcome 不误判
   失败，Ordered 支持仍带原协议成功/异常传播与内容产生条件，不凭顺序证明数值正确。
5. 没有 consumer/Use→logical content 的可靠 denotation 时，requirement 保留
   unresolved obligation，不能从相同 shape 或前几个值填入同一 logical version。
   原 storage/view 几何可以复用；UNKNOWN selector 不按 disjoint 处理。
6. query 返回原端口、支持/反证/具体缺口及条件范围，不返回无条件 ready=True。
   声明接口内的结构满足、运行协议适用和变换授权分别报告；未知 native/evidence
   覆盖不升级为无副作用或保证 free。free 还要所有 pending access/ownership 义务，
   不以一个 output ready 证明整个 allocation 可以回收。

visibility_domain 是判别联合：HostVisibility(Process/HostThreadInstance, address-space
支持)、QueueVisibility(准确 queue/context 与 consumer prefix)、EndpointVisibility
（准确 resource endpoint、观察/flush/persistence 协议的 ProviderFactReference）或
UnresolvedVisibility。host thread 和 address-space 取规范身份，不取 device 名。
没有一个全局线性 READY 等级；不同域不默认互相包含。外部输出/持久化要求引用 Q
的真实观察根（准确 scoped ContractID、typed root、endpoint/version 与协议要求），
不伪造代码 consumer。旧 ContractDefinition 的 EXTERNAL facet 或最后一条 close
不是这个根的完整对应；缺失时保留 UnresolvedObservation。ObservationRoot 是本合同
要求的新 Q 关联接口，不冒称旧 ContractDefinition 已有它；外部合同可明确声明根，
来源/采集对应另验，不凭一个输出字符串自动补出端点或持久化要求。

ValueGraph 的 region=None 不能自动判成文件/NVMe；有显式 EndpointPlacement 才
使用 EndpointBacked，其他情况保留 UnresolvedPlacement。后者不为端点捏造内存
allocation，也不改原 materialization producer/content。不同 backing 不证明无 alias，
mmap 等共享来源另有关系；未知 selector/state/denotation 继续列明确义务。

## 6. 复用、迁移与拒绝的设计

- 复用 core v14 原 IDs/Use/StateAccess/actual completion，ValueGraph 的 logical /
  allocation/region/materialization、严格 record_codec 和 ProviderArtifact/FactReference。
  不为 execution 数据升级静态 core schema；新增 execution bundle 自己版本化。
- v2 EvidenceGraph/CorrespondenceGraph 可继续读取，显式 scoped link 接 core。
  原 EvidenceClaim 的 EvidenceKind 与 ProofStatus 两轴保留，但字符串 scope/
  confidence 本身不满足新代次、顺序和身份外键。
- 旧 `Materialization.ready_event` / provenance `mark_ready` 保留旧含义和接口；
  新查询不据它们补造 WorkTicket/record generation/consumer visibility。迁移不升级
  旧声明为新的 ready 证明。具体 legacy→new 对应失败要给原因。
- **Rejected：**把动态实例/ready 布尔塞进 ProgramGraph；复用静态 ResourceID 作
  实例；复制 allocation 身份；把每次 host 返回当 work completion；同一个 event
  名称自动覆盖代次；只按唯一 writer、单一时间线或单一 ReadyState 枚举判可用。
- **Proposed/下一门：**按计划 R1→R2→R3 实现具体 exact records/wire 与验收；
  必须遵守本合同的身份、关系、端口和反例。若需调整关系，先说明原因并复审，
  不能为符合现代码删去必要依赖。本合同与见证不冒充产品已存在。

## 7. 依据与有限覆盖

本机六个带断言见证覆盖 dup/open/close、fd 再用、同路径 replace、buffer/flush/
fsync 返回、submit→部分写后异常、queued cancellation。全部通过；只证明所测
stdlib/OS 行为，不是 SCAR 图结构、GPU、power-loss durability 或优化证明。

协议依据为 [POSIX dup](https://pubs.opengroup.org/onlinepubs/9799919799/functions/dup.html)、
[Python os.fsync](https://docs.python.org/3.14/library/os.html#os.fsync)、
[Future completion/cancellation](https://docs.python.org/3.14/library/concurrent.futures.html#future-objects)。
event record/stream wait 的代次与前缀依据
[CUDA 13.2.1 Event API](https://docs.nvidia.com/cuda/archive/13.2.1/cuda-runtime-api/group__CUDART__EVENT.html)
及本机 NVIDIA `cuda_runtime_api.h`（CUDART_VERSION=13020）；PyTorch wait/query/synchronize
以本机 torch 2.13.0+cu132 的 `torch/cuda/streams.py` 为版本锚。
[线上 stable Event 页面](https://docs.pytorch.org/docs/stable/generated/torch.cuda.Event.html)
当前标 2.14，只作交叉参考，不宣称等于本机版本。来源、访问失败和文件 SHA 随
R0 归档，既有文档不能替代后续 M4 runtime/source 对应。
