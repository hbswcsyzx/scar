# C2/D3：协议操作与持续执行的联合合同

2026-10-18，实施基线 `f9a568182e1672541261020bb9f919609179bb05`。
状态：**P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN**。独立复审 PASS_WITH_SCOPE；
只冻结本设计的字段、原端口与义务，尚非新增产品能力，P2–P5仍待实施。
父计划为 [M1_PROTOCOL_FAMILY_PLAN.md](M1_PROTOCOL_FAMILY_PLAN.md)，原始审计见
[M1_PROTOCOL_FAMILY_AUDIT.md](M1_PROTOCOL_FAMILY_AUDIT.md)。

## 1. 本门对整体模型负责什么

Operation、Value、StateLocation、Region、Resource 仍是规范实体。控制、使用、
结果和状态关系各自保留原身份；显示的“操作节点、数据边”是这些记录的投影。
本门补的是原图之间可校验的连接，不增加一种业务节点，也不替代整体模型。

```text
Program：原输入/状态 → 协议操作 → 原 gate/BodyDrive 或无用户入口路径
                                  → 原 body 首出口 → host adapter
                         │ 精确原端口；来源适用条件独立
Execution：本次 Drive → 持续 body activation → 本次入口/执行片段/实际首出口
                         │ 原 uses / results / transfers / denotations
Evidence：来源、捕获、身份、路径缺口；不补造事件或相等事实
```

这直接约束未来子图化简：如果输入来自另一次恢复、某个 callback 的后态被漏掉，
或者 host 结果接错，不能仅因两个节点同类型或同代码就判定可替换。条件声明
可表达、机械连线可拒错、实际来源可验证和允许变换，是不同的结论。

固定验收分母继续为 F01–F24/X25–X28，共28个义务组，见父计划完整表；它们
不是28个测试，也不是28个已实现协议。省略附件或关系只产生具体缺口，不减少
原协议的义务。113构造/196字段的 M2 清单另行验收。

## 2. 唯一事实来源和版本边界

- 原 Program 的 operation/ordered Use/producer/CFG/状态版本是规范事实；附件只
  指向这些端口，不另存 actuals、state、phase、permit、generation 或 def-use 图。
- 静态端口只能引用静态记录；运行中的 EvidencePoint/Unresolved 不进入 Program。
  静态缺绑定保留 reason 和义务；动态缺采集使用现有 Unresolved/FactSource。
- BodyDrive 结果必须由 **DriveOutcomeRef(drive, source)+index** 定位；只有
  drive+index 会混淆不同 body 出口。INVOKE 结果必须包含准确控制边和对应
  CompletionResult，NORMAL 与 RAISE 都保留；NormalResultPort 不能通用替代。
- 新 O 能力使用 **Execution schema8**；旧v1–v7字段、标签和字节保持原范围，
  不容新字段偷渡。O 不要求 Program 新增 producer。F 的静态扩展单独版本化。
- 旧 generic D1 图不自动取得完整 Python 协议范围。合同来源引用沿现有 scoped
  provider/environment 接口；方法名、FactRef字符串或源码行号不构成适用证明。

## 3. O：本次 Drive 与持续 body 的精确 records

```text
BodyDriveExecution(
    drive: OperationOccurrenceID,
    activation: RegionActivationID,
    entry: BlockVisitID | Unresolved,
    outcome: OperationOccurrenceID | Unresolved,
    source: FactSource)

BodyActivationOrigin(
    activation: RegionActivationID,
    creation: OperationOccurrenceID | Unresolved,
    source: FactSource)

ExecutionModel.body_drive_executions: tuple[BodyDriveExecution, ...] = ()
ExecutionModel.body_activation_origins: tuple[BodyActivationOrigin, ...] = ()
```

两表分别以 drive、activation 为自然键，不制造 association ID。原 registry 的
显式 ID 表不改；新键索引和按 activation/segment/creation 的索引是派生索引。
一个 activation 可被多次 Drive；一次 Create 可不被驱动。无用户入口、前置拒绝、
delegate-only 路径没有父 BodyDrive，使用 F 的真实 host/helper/adapter 操作。

### 3.1 多重性、作用域和缺端点

每个已知 entry visit、selected segment、outcome occurrence 不能被两次 Drive
同时认领；这是实际发生的唯一性，不是静态 site 唯一性。在固定 native
frame-create/no-reset 合同下，同一具体 Create occurrence 的 NORMAL handle
只能对应一个持续 activation；外部或缺采集的 creation 不参加这个反向唯一键。

已知端点逐个检查 FK、canonical BodyDrive、body/region、run/process/thread；
不能因 entry 未知就跳过已知 outcome 的错线程或错来源。creation 可以发生于
另一历史线程；同一 body 的不同执行片段也可分次换线程。本次 Drive 与选中的
片段核对已知线程，不能套同步 CallActivation 的一 caller/全历史同线程规则。

segment 从 entry visit 派生；entry 缺采时也可从已知 outcome 派生并校验；两端
已知必须同片段。两端都未知保留原静态输入/出口分母与各自 gap。未观测 outcome
不能区分运行中、发散或截断，不产生假 NORMAL 或假“实际发散”。

### 3.2 Start、Resume 与实际首出口

Start 对应 body.entry 的原 InitialEntry 实际 visit，不能用循环回访或 resume
landing。Resume 对应 BodyResume(suspend, successor) 的准确 landing，且必须
沿原 ResumeIngress 和实际 temporal ControlTransfer 回到**确切的旧 Suspend
occurrence**、同一持续 activation 和新的 segment。saved 输入由该旧发生的
原 saved Uses 派生；current state/sent 则来自本次 Drive，不能混用历史状态。
CaptureIngress 只声明前段未捕获；保留准确缺口，不能把它改写成匹配的
InitialEntry/ResumeIngress，或补造 temporal transfer。

实际 outcome 必须位于该片段，属于该静态 target 的 first frontier。沿真实
transfer 检查入口到首出口：断采保 gap，已捕获的相反路径或更早 outcome 是
矛盾。同一 selected segment 内两个已捕获 body 首出口也是矛盾，不能因 entry
未知而豁免；同步 helper 子 activation 的出口不算 body 首出口。
实际 Drive 所选 BodyDriveSuccessor.source 必须等于实际 body outcome
的原 OperationID。缺 Drive transfer 时保留 body outputs 和原候选出口，不
补造 caller landing/formal。空静态 frontier 合法，不制造 completion。

### 3.3 instance、creation 与所有端口的对应

owner 由本次 Drive.instance 的原 UseOccurrence/ValueOccurrence 派生。
Origin 的 known creation 必为准确 ResumableCreate occurrence，并按原 NORMAL
edge/handle_result.index 和真实 transfer 定位 handle；RAISE 来源矛盾，缺正常
边或值为 gap。Start captures 由该 occurrence 的 CreationCapture/formal/Use
逐一派生；缺来源保留 InstanceCaptureInput(ownerUseSite, formal) recipe，
不猜同 Region 的唯一 Create，也不把 body formal 自己当已观察 capture。

owner 对照包括本次 Drive.instance 与 Origin 的真实 Create NORMAL handle，
以及同一 activation 各次 Drive 的 owner。原 copy 路线准确指向另一 Create，
或同 scope ObjectID 已知冲突，必须拒绝；缺路线/身份逐 pair 保 gap，不能只
验证每个 Drive 内部的局部连线而漏掉持续实例的不一致。

**每个** owner/capture/saved/delivered/output/forward binding 都要核已知矛盾：

- Reference：同 exact artifact scope 内不同 ObjectID 是矛盾；相同 ObjectID
  仅为相容声明。scope 沿现 `(sha256,schema,size_bytes)`，URI只是 locator。
  跨 artifact 无已支持桥时保 gap，不推对象相同或不同。
- Data：同 exact scoped VersionRef 可记 DECLARED 同逻辑版本，但不授实际
  等值/变换证明。不同 VersionRef，即使同 lineage 不同 revision，也不推数值
  不等；逐 binding 保 data_correspondence_unproved。仍保留原 copy 义务。
- State：核原 Location/slot/当前 SSA/实际 visit 路线，不比较两个 occurrence ID
  是否相同来判断内容，也不再造一份跨 activation 的 world identity。

outputs 只取本次实际 outcome 的原 body Uses，映射到实际所选 source 的
BodyDriveResult；额外 driver state 使用它自己的 forward Use。INVOKE 与
BodyDrive 后态在真实 EDGE 上，不能建立一个共用 AFTER 或回滚 RAISE 部分写。
原 producer/Use/ValueOccurrence ID 均保留，不因映射而合并。

### 3.4 公开面与实施位置

```text
execution/resumables.py             # 两张 record；不含派生视图
execution/resumable_flow.py         # 原端口及实际发生的共享 resolver
execution/resumable_validation.py   # 结构与已知对应矛盾
execution/resumable_query.py        # detached query views

ExecutionIndex.drive_execution(drive_occurrence, *, budget=4096)
ExecutionIndex.body_activation_origin(activation, *, budget=4096)
```

validator/query 共用 resolver 和原 program.driver_flow/resumption_flow 规则，不
在每次 Drive 内再构造整图 ProgramIndex。内容查询复用现 ExternalSnapshots 和
fresh content context；不信任 Index 构造后可能变动的外部可变图缓存。

查询分母来自**所有已捕获 canonical BodyDrive occurrences**。删 relation row
仍返回原 target/input/output 分母及 missing，不返回“没有该项”。结果只记
DECLARED/MISSING/PARTIAL/CONFLICT 与原证据、具体 gaps、预算 cursor；不记 VERIFIED。

## 4. P3 必须一并接入 conditional host order

继续使用 execution/host_order.py 的派生路径，不新建时钟或资源完成图。

1. Drive BEFORE→本次 entry 第一已捕获 op BEFORE：核该端点已知 scope/target/
   segment/真实入口/同当前线程；outcome 未知不删除已知 entry 桥。
2. 实际 body outcome AFTER→本 Drive 实际 EDGE：核准确 outcome/片段/静态
   首出口、真实 Drive transfer/source 与本次已知同线程。entry/path 断采时可保
   **conditional completion 配对桥**，support 必须保留缺入口/路径，不称完整
   captured path。已知 entry/path 矛盾则拒绝且不产生桥。
3. 该端点的首 op/outcome/transfer/thread 缺失，就保该桥的 gap，不猜边；一个
   桥缺失不抹掉另一桥的已知证据。这里不授权 GPU completion/visibility/ready。
4. 原 CALL 桥、O 桥和 actual local CFG 合并后检查真实 occurrence 因果 cycle。
   不对 activation 强制 DAG：持续 body 多次恢复本来就会重复关联。有限端点
   adjacency 加 local-chain 压缩后做拓扑/可达检查；禁止每 Drive 扫全模型或
   枚举所有 endpoint pairs。所有推导共用预算；截断不能记成“已证无环”。

## 5. 当前证据与实施验收边界

| 状态 | 本门准确含义 |
| --- | --- |
| Observed | 一次既有 IR 蓝图的原端口映射；不是外部程序运行采集。 |
| Inferred | 持续 activation 不能套同步调用的一 caller/全历史同线程约束。 |
| Proposed | 本文新静态合同、两张 O 关系及 schema 扩展；实施仍待 P2–P5。 |
| Implemented | 旧 C2B/D1/D2 及603文件产品基线；本门未新增产品能力。 |
| Verified | 旧冻结实现的5,294项回归；本门只核设计证据与范围。 |
| Rejected | 初稿自由 relation、静态引用动态端口、无 source 的 Drive 结果，以及内层 RAISE 即终结的推断。 |

原端口蓝图 `model_protocol_contract/port-blueprint-attempt001.json` 连接两个
DriverInterface 的 Start/Resume 到同一声明 body activation 的两个执行片段，8/5
inputs 和各3 outputs 都按原端口派生。现有 ExecutionIndex 没有结构 issues，
但 Start 保留6个未解 capture recipes，来源/身份未证。蓝图只是既有 IR 与
拟议 FK rows 的设计可实例化观察，**不是新 O validator 或 O01–O16 通过**。
其 generic body Return→driver Return 也不构成 Python host adapter 的协议验证。

O01–O16 详见归档 design/o-execution.md，映射原 F02/X27 及交叉组；关键验收
包括 known Create/外部实例、同 code 多实例、两次驱动/分次换线程、错代次/
旧状态、两端缺一仍检查矛盾、N/R/source 错接、逐 binding identity、空 frontier、
预算截断、旧 wire 严格隔离与 host 因果 cycle。不能缩成成功 yield 一次。

本门没有新 pytest/full、LeWM profiling 或性能测量；注册603源码和78 fixtures
保持既有指纹，5,294项全仓结果仍归属冻结实现 `4bc55eb`。M0–M2 完整验收后
按用户要求先停下来讲解模型。此前不增加 detector/backend 或 LeWM 特殊规则。

## 6. F：固定协议合同，连接原生产者与消费者

详细规则表冻结在
[F-final 附录F](../artifacts/experiments/b1_call_operands/model_protocol_contract/design/f-static.md)，
SHA256 `986d2e6276ece7fec5c83d502a27a634d1121dfd3501e68d58185159eae2cbd7`。
该报告保留初稿及其撤回历史；实施只采用 final 附录及本节。附录F.7/F.8收敛
前表的来源、slot、名称及端口包装；以下为整理后的规范形状，没有两套可选 API。

### 6.1 精确 records、原端口与自然键

```text
DriverSubject(interface_region: RegionID)
OperationSiteSubject(region: RegionID, operation: OperationID)
StaticProtocolGap(reason: StaticGapReason)

ProtocolScope(
    id: ProtocolScopeID,
    profile: ProtocolProfile,
    subject: DriverSubject | OperationSiteSubject,
    source: ProviderFactReference | StaticProtocolGap)

ProtocolOperation(
    scope: ProtocolScopeID,
    clause: ProtocolClause,
    operation: OperationID,
    slot: int,
    contract: RequestProcessing | ProtocolCall | PacketConstruction |
              OutcomeAdapter | NoEntryOutcome,
    source: ProviderFactReference | StaticProtocolGap)
```

Scope 主键为准确 ProtocolScopeID；operation row 自然键为
`(scope,clause,operation,slot)`。slot 是准确非 bool 非负 int，由原 operation/
successor 和固定 scope/site 分母派生，不能由 rows 自己定义需要多少槽。
DriverSubject 引用原 DriverInterface；OperationSiteSubject 只需原 operation
属于该 region，普通 wrapper/helper 也合法，不要求它自身是 ResumableBody。

结果端口复用 **program.model.OperationResult** 和 **InvokeLiteralResult**：
后者的 edge/result 已定位 owner、NORMAL/RAISE signature 和 CompletionResult。
不另存 InvokeCompletionPort、重复 operation、normal_port 或新 result 身份。
虽然旧类名含 Literal，F 只复用其端口形状；不能调用旧 literal_site 解析器来
限制 F 为 NORMAL/Data/Reference，也不放宽旧 literal 的既有检查。

```text
ProtocolResultPort = OperationResult | InvokeLiteralResult | StaticProtocolGap
DriveResult(outcome: DriveOutcomeRef, index: int)
ContractResult(scope, clause, operation, slot, result_port)
AdapterInputPort = DriveResult | ContractResult
NoEntryInputPort = ProtocolResultPort | ContractResult
```

ContractResult 必须指向固定分母内 required row 的**自身准确结果**，不能自指、
以无源循环互证，或换成同一 operation 的另一个结果。协议行之间的引用只是
对原端口的约束，不产生额外 dataflow producer。HostTerminal 指原 RETURN/
RAISE operation，payload Uses 从原操作派生；NativeExit 指已存在的准确
native ExitPort，native/source 对应仍为独立条件。

五种 contract 的精确字段如下；UseID 都属于 outer.operation，源引用则允许
沿准确原路由指向其他操作。共享 Value 不要求共享 UseID。

| 变体 | 字段与固定约束 |
| --- | --- |
| RequestProcessing | raw_use；operand_bindings: tuple[RequestOperandBinding(request_ordinal,operation_use),...]；result: ProtocolResultPort；state_sites；rule。raw-only 合法，expanded operands 才逐 ordinal 核来源，不强迫 helper 与 pack op 共用 UseID。 |
| ProtocolCall | receiver_use；argument_uses 有序 tuple；result: ProtocolResultPort；state_sites；rule。真实 CALL/INVOKE 的自身结果和 N/R；没有 RAISE 出口不能消除所需异常义务。 |
| PacketConstruction | packet: ValueID；exception_source；traceback_source；rule。目标必须是原 ExceptionPacketDefinition，输入角色由规则选定的前置 normalizer/constructor/raw ordinal/已有 packet 决定；不能用目标自己输入作来源自证。 |
| OutcomeAdapter | input: AdapterInputPort；input_use；output: ProtocolResultPort或HostTerminal或NativeExit；rule。源由规则确定为准确 body source/result 或准确 helper result；delegate-only 无父 Drive。 |
| NoEntryOutcome | instance_use；effective_request_use；selected_input: NoEntryInputPort；state_sites；selected_edge: ControlEdgeReference或None；terminal: HostTerminal或NativeExit。outer.operation 就是真 transition，不再重复 scope/clause/slot/transition/source/disposition。不能从 DriveResult 取输入；可用本 helper/transition 的原结果或前置 ContractResult。 |

state_sites 只使用 `ExistingAccess(operation,index)` /
`InvokeStateOperand(operation,state_use)`；ordinary before/after 和 INVOKE 各
选中 N/R post 均从原记录派生。known endpoint 矛盾是 Issue；missing 才是 gap。
ProtocolSourcePort 可引用原 owned Use、以上准确结果、DriveResult/ContractResult，
但规则必须确定其实际角色；任意同型 exception/packet 不能补位。

### 6.2 闭合 profile 与 clause 分母

| ProtocolProfile | 原主体/家族 | 固定义务 |
| --- | --- | --- |
| GENERATOR_BODY_V1 | Driver；GENERATOR/BODY | RAW_ADMISSION、REQUEST_PROCESSING、BODY_INGRESS、BODY_SUSPENSION、BODY_TERMINAL、HOST_ADAPTER、CLOSE_ROUTE |
| COROUTINE_BODY_V1 | Driver；COROUTINE/BODY | RAW_ADMISSION、REQUEST_PROCESSING、BODY_INGRESS、BODY_SUSPENSION、BODY_TERMINAL、AWAIT_COMPLETION_ADAPTER、CLOSE_ROUTE |
| GENERATOR_COROUTINE_BODY_V1 | Driver；GENERATOR_COROUTINE/BODY | RAW_ADMISSION、REQUEST_PROCESSING、BODY_INGRESS、BODY_SUSPENSION、BODY_TERMINAL、DIRECT_HOST_ADAPTER、AWAIT_COMPLETION_ADAPTER、CLOSE_ROUTE |
| ASYNC_GENERATOR_BODY_V1 | Driver；ASYNC_GENERATOR/ASYNC_REQUEST | ASYNC_REQUEST_SOURCE、ASYNC_REQUEST_ASSOCIATE、ASYNC_REQUEST_DELIVERY、BODY_INGRESS、BODY_SUSPENSION、ASYNC_ITEM_ADAPTER、BODY_TERMINAL、CLOSE_ROUTE |
| AWAIT_SITE_V1 | 原 await site；body/helper均可 | AWAIT_LOOKUP、AWAIT_CALL、AWAIT_RESULT_ADAPTER |
| DELEGATION_SITE_V1 | 原 DELEGATION site | DELEGATE_ITER_LOOKUP、DELEGATE_ADVANCE、DELEGATE_THROW、DELEGATE_CLOSE、DELEGATE_PARENT_OR_HOST_RESULT |
| COROUTINE_AWAIT_WRAPPER_V1 | 原 wrapper lookup/call site | WRAPPER_LOOKUP、WRAPPER_CALL、WRAPPER_RESULT_ROUTE |
| CREATED_THROW_V1 | 原 created throw/处理 site | RAW_ADMISSION、THROW_NORMALIZATION、源路径要求的全部 PREENTRY_REJECT/INITIAL_THROW_DELIVERED/INITIAL_THROW_CONSTRUCTOR_FAILURE、HOST_TERMINAL |
| CREATED_CLOSE_V1 | 原 created close site | CREATED_CLOSE_BRANCH；复用准确 CreatedCloseTest true/false 和 NoBodyFinish |
| SUSPENDED_CLOSE_V1 | 原 suspended close site | CLOSE_INJECTION、BODY_INGRESS、BODY_TERMINAL、CLOSE_HOST_ADAPTER |
| TASK_CANCEL_EXTERNAL_V1 | 原 Task 请求 site | TASK_CANCEL_REQUEST、CANCEL_DELIVERY、CANCEL_HANDLER_OR_TERMINAL、TASK_STATUS_ROUTE |

上述 clause 名的闭合集合就是初版 ProtocolClause；不得任意添加字符串 clause。
body/ingress/outcome/association/created-close 等已有原 marker 的 clause 直接派生
原门/出口义务，不强迫再制造 ProtocolOperation。normalizer/lookup/constructor/
adapter 等需要合同锚的 clause 才由对应变体绑定。source 的适用路线确定 N/A，
不能由作者任选一个 CreatedThrow 分支来删掉其他分支。

Async request 的 SOURCE 可以是实际 local create，也可以外部或缺采集；
association 可以在 combined helper/gate 内联，不要求独立 RequestAssociationRead。
四个 body/request/latent/scheduler 角色和当前交付仍逐端口核对。native coroutine
的 __await__ wrapper 不是异步生成器 request，也不另加 receiver 枚举或复制 CFG。

固定规则枚举及允许的 profile/clause/input/output 组合采用 F-final 附录F.3/
F.5/F.7；它们不是可编程的 relation 语言。规范化只接受自己的 raw/处理结果，
PacketConstruction 只接受该规则指定的 component 来源，adapter 只接受该规则
指定的 body/helper 出口。转发沿原 CFG argument/formal 同时改名后 must 合流；
不按来源集合 union、类型、名字、内容相等或逐路径枚举来代替。

该附录F.5的“normalizer NORMAL packet”与F.7的“exception component”不得混型：
原 helper 结果若是 EXCEPTION_PACKET，就直接按准确整体 packet 端口转发；若是
exception Reference，才以该准确引用及规定 traceback 来源组原 PacketDefinition。
两形状按原 signature/结果类型选择，不强拆原操作，不把 packet 当 exception
引用。本条收敛归档报告该处的简称，优先于其未区分结果类型的表述。

StaticGapReason 的有限成员为 SOURCE_SCOPE_INVENTORY_UNRESOLVED、
SITE_INVENTORY_UNRESOLVED、EXTERNAL_RAW_UNAVAILABLE、
RAW_OPERAND_PROJECTION_UNRESOLVED、PORT_UNCAPTURED、STATE_POST_UNCAPTURED、
CALLBACK_BEHAVIOR_UNPROVEN、NATIVE_APPLICABILITY_UNPROVEN、TASK_IDENTITY_UNMODELED、
TERMINAL_ROUTE_UNRESOLVED、UNSUPPORTED_PROFILE。这里 UNCAPTURED 指 supplied
Program 缺端口，不带执行 run，也不表示一定曾发生。

### 6.3 必须检查消费者与无入口终结，不能只列生产者

BODY_INGRESS 从 driver raw/effective request 和被选中处理结果派生：

```text
原有序 raw / 选中的 normalizer 自身结果
    → FinalBodyGate.delivery_arguments
    → 本 BodyDrive.resume_inputs
    → 准确 ResumeSlotKind / 原 body landing
```

初始 NEXT/SEND(None) 走 BodyStart，无 resume slot；None 必须来自准确原 ordinal/
规则来源。暂停后 SEND 的 ordinal0/准确处理结果到 SENT_VALUE；THROW/CLOSE 的
选中 packet 到 THROWN_PACKET。完整 packet 的 helper 结果可以直接交付；只有
显式 pack 时才核其 component construction，不能强迫 opaque helper 内有一个
虚构 PacketConstruction。async handoff 还须核当前 request，创建不是交付。

HOST_ADAPTER 也含不需要新 operation-contract 的原 exact-copy 路线：普通
generator YIELD 的准确 export→本 DriveResult→host RETURN item，直接从原
Use/edge 派生，不能借 delegate/async adapter 规则来填。Closed next/send/throw/
close 路线没有新 Drive：由固定 Closed+raw 分支中 RequestProcessing 自身的准确
N/R 结果和最新 state，沿原 CFG 到 host terminal。必须核该分支的 current Closed
来源、请求与准确结果，不重放上次 return payload，不制造 INITIAL_THROW/no-entry
transition 或新的 F seed；原 terminal history 的保持另按既有生命周期核对。
相同的派生拒绝路线也适用于 RAW_ADMISSION 的前置失败和 Running 重入拒绝：
从该分支自己的处理结果/当前后态接 host terminal，不制造 BodyDrive 或终结 seed。

NoEntryOutcome 的 selected_edge 对 INVOKE 必填且属于 transition；ordinary
update 后若真实 branch 选择路线，则引用该 block 准确 terminator edge。
只有唯一 straight-line continuation 才可无 edge。slot 等准确 successor_index；
沿选中边到 host terminal 逐步核 payload/packet 及**最新**原状态，而非只核可达。

PREENTRY_REJECT 不产生 finished-body 事实。INITIAL_THROW_DELIVERED /
INITIAL_THROW_CONSTRUCTOR_FAILURE 仅在固定 source clause、真实 transition/
后态与最终路线均相连时，提供有条件的 no-entry terminal 来源；内层 factory
RAISE 被 catch/pack 的情形继续保留。**lifecycle_flow 当前按 operation 无条件
seed 的实现不能直接加一行复用**：P2 必须按这条精确 EDGE 种 F/T，session 的
body-only 更新也按同一来源，不能污染另一 N/R 分支或绕过 must-meet/current owner。
release 继续消费原生命周期事实，不新增 phase/finished boolean/许可。

scope/source site inventory 未证明穷尽时，不能从现有 rows 推覆盖完整。已知
canonical marker 和固定 clause 的缺 row 保 MISSING；删除 scope/未知 site 范围
保 global inventory gap。M1 不为此实现任意源码解析器或完整调度器，但也不把
来源适用未知写成“机械连线无需检查”。

## 7. 实施切分、公共面、预算与本门停止条件

F 首次产品扩展采用 **Program schema17**，保旧v1–v16字段/tag/bytes范围；
`ProgramGraph.protocol_scopes/protocol_operations` 默认空。新增模块为
program/protocols.py、protocol_rules.py（固定表）、protocol_flow.py、
protocol_validation.py、protocol_query.py；公开
`ProgramIndex.protocol_obligations(scope=None, *, budget=4096)`。
scope=None 返回 supplied-model inventory 和 global 未证范围，不能当全源码已扫。
后续 P4 若确需扩字段，应另作显式 capability 迁移，不偷渡进旧版本。

| 后续门 | 必须达到的具体结果 |
| --- | --- |
| P2 | 同步 generator Created/Running/Suspended/Closed × Next-Send/Throw/Close 全表；原 raw→处理→gate/body或无入口→首出口→host；错同型 packet、原 raw ordinal、错误 N/R seed、返回/异常适配、close 非法 yield/重试逐项正反核对。其他家族未实施保持原分母 OPEN。 |
| P3 | 两次 Drive/同持续实例、Create/capture与外部来源、Resume精确旧发生、逐 binding已知矛盾、片段线程、部分缺采；两条 conditional host bridges 和联合 occurrence cycle 同门验收。 |
| P4 | 余下 coroutine/generator-coroutine、async requests、delegate/await/cancel 与 C1/session/release 组合；固定 clause 不能只有 label，没有原端口义务。 |
| P5 | 公共 wire/query/CLI、完整28组ledger、预算/缺口/旧case与fixture守恒；独立复审与一次冻结全仓归档。之后仍须原113构造/196字段和完整M0–M2总验收。 |

所有源对齐、copy、must/path、端口和 identity joins 共用原预算，不每 formal/
Drive 重置。预建原 owned Uses、operation/visit、activation/segment、creation
索引；有限 worklist 求固定点，不枚举控制路径/动态轮次。HB endpoint 局部排序
至多 O(N log N)，其余邻接扫描 O(N+E)；不允许每 Drive 重扫整图或全 pair。
准备/校验/外部快照/detach成本单列，截断返回具体 cursor/gap，不授 complete。

有产品改动才按父计划做定向→组件→干净实现提交→一次冻结全仓→只读归档。
本 P1 只在字段/原端口/固定规则/能力边界的独立复审无实质阻断后冻结，复用旧
源回归证据。P1 通过不代表 F/O 已实施、全协议通过、自动建图或可化简。
