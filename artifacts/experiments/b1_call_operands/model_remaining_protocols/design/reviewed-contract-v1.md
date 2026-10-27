# P4 原端口连接合同 v1：审查稿

2026-10-18，基线`d507a16`。本稿收敛[P4计划](M1_REMAINING_PROTOCOL_PLAN.md)的
P4-1字段决定，等待最后反对性复审；**不是P4产品验收**。P1冻结合同不修改。
三路初稿与取舍保存在`model_remaining_protocols/design/`，不得覆盖原稿。

## 1. 规范事实与独立义务

操作、值、有序Use、结果、state SSA、CFG及动态occurrence仍是唯一规范事实。
以下附件只说“哪个原端口应来自哪个原来源”，不另存actual/producer/post。
actual反向追到了某producer，不足以把它挑作expected自证。源/native适用、
静态原图连接、动态身份和变换权限分别报告。

输入解析共享ProgramIndex、ProtocolFlow及一个预算；原caller/CFG选择必须
联合，不能对每个参数独立ANY匹配或拼不同上下文。来源可以不确定，已知错接
不能降为缺口。prepared/validation/external/detach成本单列。

## 2. 共用精确引用

```python
ProtocolOperationRef(scope, clause, operation, slot)
RawOperandSource(raw: OwnedUse, ordinal: int)
```

前者是现ProtocolOperation的完整自然键，不是新ID，必须恰好命中一行。
后者是原RAW pack的准确ordinal投影，只在expected位置使用；不在实际callee
签名中加RAW。源查询已先完成[中间检查点](M1_PROTOCOL_HELPER_INPUTS.md)，
不接收RAW的helper仍可沿实际Reference参数与同caller上下文追溯。

新字段的`ExpectedSourcePort`复用现ProtocolSourcePort，并可引用现有
`model.BlockArgument(block,index)`；它指原formal，不造producer。只扩新字段的
union，旧PacketConstruction等字段的旧union不静默扩大。原formal仍需逐incoming
operand核规则来源，指向一个合流formal本身不证明它来自正确lookup。

## 3. 调用输入：一个自然键、一组相关角色

```python
ProtocolCallInputs(site: ProtocolOperationRef,
                   cases: tuple[ProtocolCallInputCase, ...])
ProtocolCallInputCase(guard: ControlEdgeReference | None,
                      receiver: ExpectedSourcePort,
                      arguments: tuple[ExpectedSourcePort | RawOperandSource, ...],
                      trigger: CallTrigger | None)
RawRequestTrigger(raw: OwnedUse)
InjectedPacketTrigger(packet: ExpectedSourcePort)
InitialAdvance(iterator: ContractResult)
CallTrigger = RawRequestTrigger | InjectedPacketTrigger | InitialAdvance | StaticProtocolGap
```

ProgramGraph新薄表`protocol_call_inputs`，自然键site；实际receiver/arguments
只读原ProtocolCall的UseIDs。case非空，参数数量和顺序精确匹配，所有nested
记录严格重验；一个site不能重复输入附件。

- 简单路线仅一无guard case。有多case时guard非空、唯一，绑定该consumer
  输入tuple的同一个准确原merge块的predecessor edge；merge可为consumer块，
  也可经原ordinary copy/JUMP到达consumer的上游合流块，必须证明相关角色
  的原formal/copy路线确实经过该merge，并在同merge/context上联合核对。
  不要求lookup合流后必须立即call，也不接受无关早期branch作为任意条件。每个
  known applicable incoming edge都核整组receiver/arguments/trigger；缺case仍
  缺义务，一个好case不能洗掉其他已知错接。guard只是原路径条件，不是可跨
  callback保活的许可。
- 已有准确原formal合流时优先引用canonical formal，避免枚举路径或笛卡尔积。
  必须同时核每条原incoming来源及相关角色的同context；无法收敛完整覆盖就
  保精确缺口，预算截断不得给完整结论。
- AWAIT_CALL/WRAPPER_CALL的receiver独立选准确lookup ContractResult；多个
  同型lookup不能随actual选择。lookup/getiter的根输入来自准确原source site
  端口；atomic边界的source适用仍是条件，不能把根输入声明当source已证明。
- NEXT/SEND/THROW/CLOSE需要原trigger；lookup/getiter等无需请求的固定规则
  才允许None。NEXT可来自NEXT、SEND(None)或该site初次advance；SEND/THROW
  按同一raw锚的准确有序ordinal，THROW保1–3原参数，不先无条件规范化。
- InitialAdvance引用本site准确GetIterator/lookup自身结果；还须核该求值后、
  本次首advance之前的原路径，不是一个“initial=true”许可，也不要求全局新
  iterator或父body的BodyStart。loopback/已advance路线不能借该marker再算首次。
- CLOSE可由raw CLOSE、raw THROW(GeneratorExit)的准确分支，或当前注入packet
  触发。InjectedPacket必须来自当前parent landing/本raw处理结果等准确源；
  旧同型packet不可替代。GeneratorExit类别/原判别边适用未证时明确保条件，
  trigger类型不自证异常类别，不把close正常None当新packet。
- 每个匹配保原call/edge/source支持，跨region先逐段原调用/输入输出对应；
  local reaches=False不是全局不可能。没有桥保具体缺口，不造调度边。

## 4. parent resume和结果消费者

```python
ResumeSourceBinding(source: ExpectedSourcePort)
ProtocolResultConsumers(site: ProtocolOperationRef,
                        targets: tuple[OwnedUse | HostTerminal | NativeExit | StaticProtocolGap, ...])
```

ResumeSourceBinding是ProtocolOperation新contract变体，只用于BODY_INGRESS；
row.operation必须为原BodyResume Drive，row.slot为准确非STATE resume slot。
实际Use、BodyResumeInput、目标Suspend/successor全从原core派生；每个原slot
先有义务，再查row，删除row仍MISSING。不得用Start造不存在的resume payload，
不由AWAIT flavor武断决定SENT/DELEGATE槽的层级。

`protocol_result_consumers`为第二张薄表，自然键site；source继续是该row自己的
result或OutcomeAdapter.output。targets只选原消费者并按固定rule限角色；
output已是准确HostTerminal/NativeExit时不强迫再声明相同target。普通结果到
父表达式、原Suspend.export或host的关系不能只靠“可达某个终结”替代。
parent Resume已有独立slot义务，不重复维护一套parent映射。

消费者分母必须先由该准确输出port、原ordered Uses/CFG、对应site/native端口
及固定rule派生，形成独立target ledger，再与targets核对。每个已知必需target
都要有检查项，删除附件或漏一target仍MISSING。不能让一个合法targets子集
定义自己的覆盖分母；site/native target库存无法穷尽时保精确inventory gap及
未查cursor，不把“所列全部通过”写成consumer完整。原消费者的opaque转变或
escape也不视为不存在。

## 5. async request与session

```python
RequestAssociation(request_use: UseID,
                   body: AssociationPort, latent: AssociationPort,
                   state_sites: tuple[ExistingAccess | InvokeStateOperand, ...])
AssociationPort = OperationResult | InvokeLiteralResult | OwnedUse | StaticProtocolGap
RequestStateCondition(request_use: UseID, state_sites: tuple[ExistingAccess, ...],
                      rule: IS_INITIAL_STEP | IS_COMPLETE)
AsyncSessionOutcome(scope, update: OperationID, source: DriveOutcomeRef | ContractResult)
```

RequestAssociation是ASYNC_REQUEST_ASSOCIATE的新contract；实际独立read优先从
既有RequestAssociationRead派生同一view，不要求复制附件，若两者均给则一致。
独立read的B/L须本op准确NORMAL结果；combined helper/gate只引用自己真实owned
inputs/results，无L端口保缺口，不添假RAW，不拿本次scheduler S冒latent L。

expected R来自固定DriverInterface.receiver；从其独立create/read语义投影得到
B/L，再与actual gate/Drive的B/S/session/delivery比较。同B不同R、branch两Create
均保整组context；不能先从actual B找到唯一Create再自证。R首步不等于B Created。

RequestStateCondition扩展AdmissionPredicate.subject，仅指真实R和原只读state→
自己的bool→准确branch。不虚加B/L/S参数，不新增request phase。body谓词仍指
B；coroutine/generator-coroutine的相关只读规则也必须显式纳入新能力检查。

AsyncSessionOutcome只附原SessionUpdate，键(scope,update,source)，允许共享
update多incoming，逐来源检查；来源分母从原outcomes/helper selected edge派生，
删除relation仍缺义务。AWAIT→当前session HOLD，ASYNC_YIELD→本R COMPLETE而B
暂停；terminal、preentry拒绝、aclose失败各依准确路径。post和state不在附件
复制；callback杀旧P，原真实update的after/NORMAL可重建，RAISE保partial state。
scope仅允许ASYNC_GENERATOR_BODY_V1且对应update的准确原driver；不能拿另一
driver的同型update填补本义务。

## 6. cancel跨site：精确目标，不实现Task框架

保持旧ProtocolOperation局部region所有权；取消远端关系放闭合薄表，不把远端
op冒作request scope内的本地producer。

```python
TaskCreatedTarget(task_result, body_use: OwnedUse, interface)
TaskTargetRead(task: OwnedUse, target, state_sites,
               role: OWN_CONTINUATION | CURRENT_AWAITED, interface)
TaskTargetSource = TaskCreatedTarget | TaskTargetRead | StaticProtocolGap

CancelDelivery(scope, expected_target: TaskTargetSource,
                packet_source: ExpectedSourcePort, consumer: OwnedUse)
CancelDeliveryRef(scope, expected_target: TaskTargetSource,
                   packet_source: ExpectedSourcePort, consumer: OwnedUse)
CancelHandling(delivery: CancelDeliveryRef, handler_packet: OwnedUse,
                context_sites, continuation: ControlEdgeReference | StaticProtocolGap)
TaskStatusRead(scope, task: OwnedUse, result, state_sites,
                rule: IS_DONE | IS_CANCELLED,
                consumer: OwnedUse | StaticProtocolGap)
```

`task_result/target/result`均准确OperationResult或InvokeLiteralResult；interface为
ProviderFactReference或StaticProtocolGap；state/context_sites为原ExistingAccess或
InvokeStateOperand。Created必须同一真实create的实际body输入与成功Task结果；
Read必须真实task输入、准确NORMAL Reference结果和当前状态，interface须明确
存入/投影语义，不能凭FactRef相等或任意同型port证明。status只取本op准确bool。

- 固定request Task先独立对应到Created/Read的task端，expected target才与
  实际drive/call receiver核对；禁止直接填actual Drive.instance自证。
- OWN_CONTINUATION与CURRENT_AWAITED不混：当前waiter可能是另一个Future/Task，
  不能直接当父coroutine；中间原请求转发/回调/恢复链逐段保留，缺桥保缺口。
  creation归属不授永久current waiter，读后callback须重证当前关系。
- Delivery键为全部四字段；完整Ref精确命中一项。Handling键(deliveryRef,
  handler_packet)，不能仅靠同consumer从多packet/target候选中挑一项；未被选
  的其他已知来源仍保义务。两同坐标路径由原caller/CFG recipe分别保留。
- packet必须从实际注入源到准确THROWN_PACKET或原throw实参，不能用cancel
  bool代替；完整packet与exception Reference按原PacketDefinition区分。
- handler/context/cleanup、抑制后再await或终结沿原C1/CFG派生；不造“handled”
  bool。status键(scope,result)，只读真实Task状态，IS_DONE不等于IS_CANCELLED；
  请求成功、包类别、body某次RAISE均不替代最终status。无实际Task接口锚保
  TASK_IDENTITY_UNMODELED/TERMINAL_ROUTE_UNRESOLVED。

第三张表`protocol_bindings`的闭合union仅容AsyncSessionOutcome、CancelDelivery、
CancelHandling、TaskStatusRead；不接受任意RouteLink或可编程约束。各字段严格
FK/type/state/selected-edge/context检查，source/native适用继续条件化。
Cancel*及TaskStatusRead的scope只允许TASK_CANCEL_EXTERNAL_V1，Handling从完整
deliveryRef继承scope。全部state_sites/context_sites须精确tuple并逐项重验；
CURRENT_AWAITED缺可核当前支持时保specific gap，不能用空tuple得到current=True。

## 7. 版本、分母与验收

新能力拟用Program19，Execution仍8。三张新表默认空；原Program1–18字段、tag、
family和字节保留。新contract/subject/trigger及旧shape在新profile上的语义扩展
均须进入capability检测；旧reader不能因为已有tag就接受新规则。独立旧v18
oracle由冻结旧encoder生成，禁止从新encoder伪造。
历史17/18已经合法的仅声明async/coroutine scope不属于新能力，不得一概升级19。

原F12–F24/X25–X27共16组保持；X28公共面仍属P5。义务从固定profiles及原
sites/ports/gates/outcomes/updates派生后再查可选附件，缺row不删除分母，删除
scope仍有全局库存缺口。部分接口与正例不授自动source恢复、native/runtime、
值身份或变换权限。原113构造/196字段和完整M0–M2总验收仍在后续。

实施按原P4计划：分组必要定向→统一组件→干净提交→一次冻结全仓→只读归档/
版本管理。共享helper目前仅中间22项定向通过，不拿它关闭上述任何完整家族。
