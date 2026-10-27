# P4-1 async request、session、terminal、cancel：接口建议

2026-10-18；父代理报告基线 `d507a16`。本文件为 **Proposed，未冻结、未实施、非验收**。
范围：F16–F19/F24/X26，并保留X25/X27/X28组合义务。只读现有源码与旧证据；本轮没有执行Python、测试、探针、工作负载。只新增本报告，不改P3归档。

## 1. Observed：当前事实与精确缺口

1. `drivers.py:130–179` / `driver_validation.py:160–179` 已核真正的 AsyncRequestCreate 输入 B/L、NORMAL request结果，和 RequestAssociationRead 输入 R、NORMAL B/L 两结果。它们不是四种async方法的完整实现。`known_bodies` (:181起)只沿原 ResumableCreate结果传播，没有给R的存储字段建立独立恢复语义。
2. FinalBodyGate 已核固定interface receiver/scheduler、实际参数成员资格、独立forward Use→formal→Drive、每N/R的真实current states (`driver_validation.py:307–368`)。ASYNC_REQUEST固定receiver是R，gate/Drive的instance是B，scheduler是S；当前没有完整的R→B/L→本次delivery连接。
3. `CHECK_INITIAL_ASEND`已有规则，但不在 `protocol_validation._RAW_KINDS` (:28–37)；当前处理器检查不足以确定本次是request首步还是从body AWAIT继续，也不能把latent L与scheduler S互换。现 `AdmissionPredicate`仅允许GENERATOR_BODY_V1 RAW_ADMISSION (`protocol_rules.py:233`)。
4. `resumption_validation.py:154–161`实际限制asyncgen只有AWAIT/ASYNC_YIELD。async item adapter已核准确DriveResult、slot0及ASYNC_YIELD (:426–462)，不是全无检查；但 `connection_errors` 的item consumer只特判普通YIELD (:612–619)，adapter最后一段consumer规则 (:650–665)不含ASYNCGEN_YIELD_TO_REQUEST_ITEM。
5. SessionUpdate已有真实R/B owned Uses、AFTER或真实helper NORMAL状态支持 (`session_release_validation.py:76–105`)；session_flow按callback/未知写杀P、只在真正NORMAL种P (:115–134)。它未根据具体AWAIT/item/terminal来源选择post。COMPLETE隐含ABANDON是当前谓词关系，不是另一个phase机 (:52–54)。
6. F只由真实Return/Raise publication、既有合法no-body来源等建立，Suspend不种F (`lifecycle_flow.py:150–167`)。窄TerminalFrameRelease不是free/耗尽/无callback证明；两次真实release不因同owner自动非法。
7. TASK_CANCEL_EXTERNAL_V1四个clause已固定；后两项 `CANCEL_HANDLER_OR_TERMINAL` / `TASK_STATUS_ROUTE` 当前没有allowed contract或派生实现。TASK_CANCEL_CALL只核实际调用；CANCEL_PACKET_FROM_DELIVERY没有像THROW normalization那样的特定前驱检查 (`protocol_validation.py:371–419`)。
8. 当前本地ProtocolOperation被严格约束在scope的Region内 (:326–329)；ProtocolFlow.forwards跨Region返回None (:292–293)，reaches跨Region返回False (:310–311)。不能把后者误作跨call/跨body实际不可能，也不能偷偷放宽旧本地合同来装下整个Task取消路径。
9. 旧 `model_driver_lifecycle_design/review/lifecycle_probe.json` 的CPython3.14.7观测：request创建不推进body，request完成与body暂停分开；一次aclose非法yield后，再次aclose报StopAsyncIteration而sensor仍AGEN_SUSPENDED。它是既有有界观测，不是本轮新测，也不是所有native字段或所有版本的断言。

## 2. Inferred：必须保持的独立分母

- **R**：DriverInterface.receiver的request角色；**B**：关联body实例；**L**：该request保存的latent NEXT/SEND/THROW/CLOSE；**S**：本次驱动request-awaitable的scheduler raw。R可以强引用B；R完成不表示B完成。一次R可因AWAIT被多次drive，B也可先后被不同R驱动。
- expected来源独立于actual消费者。先固定scope的R/S，以及R语义投影的B/L，再读gate实际B/S/session/delivery。不能先追实际B到某个Create，再把该Create当正确目标自证。
- 分支两Create、同B不同L、同代码不同B/多实例，保留成带同一call-context和CFG选择的整组recipe；禁止分别union R/B/L再笛卡尔配对。同ValueID、None内容、FactRef或URI相等都不代替该join。
- 局部copy用ProtocolFlow的evaluation-relative must-copy；跨call用prepared input origins/paired_input_origins/request_input_binding，跨body用原DriveInputBinding/DriveOutcomeRef；动态实例与本次entry/outcome继续由P3 O检查。静态recipe不合并ValueOccurrence身份。
- 原始S和L都可能有THROW，但一个是scheduler对等待中request的输入，另一个是request首次承诺的操作；不能仅按RawRequestKind选一条。首次实际开始与后续AWAIT恢复需要可定位的原分支/原helper合同。
- 未知callback后的当前P失效与已经发生的terminal F是两回事；本次gate按当前状态重检。早期bool只能解释其read snapshot，不能授跨callback永久资格。

## 3. Proposed：共享解析接口，不建第二套事实图

共享一个按query建立的ProtocolFlow/ProgramIndex prepared上下文和ValidityBudget，统一解析：

```text
bind(expected: ProtocolSourcePort,
     actual: OwnedUse,
     contextual_recipe: 原call/CFG/body输入输出recipe)
    -> {expected, actual, routes, compatibility: True|False|None,
        original_states, conditions, gaps}
```

这是派生view，不是ProgramGraph新producer/Use/状态表；函数名留root统一。局部True只表示原copy；跨域必须逐段保原actual/formal/selected edge。None不当False，预算未查不当True。known FK/slot/role/旧evaluation/不相容已知call-context为Issue；外部实例、缺lookup/缺采、opaque变换、native适用未知为具体gap。

R的successful Create来源仅从**固定R端口**的独立recipe求得，用其原body/latent输入解释expected投影；不是从实际gate.instance倒推。若R来源不唯一，逐context保整组；若没有该桥，不能挑唯一可见Create。read输出虽可按固定接口声明为R的投影，但不会把fresh result伪成ordinary copy，也不产生运行身份证明。

## 4. Proposed：最小async附件与字段

### 4.1 RequestAssociation：既有ProtocolOperation的新closed contract

```text
RequestAssociation(
    request_use: UseID,
    body: OperationResult | InvokeLiteralResult | OwnedUse | StaticProtocolGap,
    latent: OperationResult | InvokeLiteralResult | OwnedUse | StaticProtocolGap,
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...])
```

自然键沿既有 `(scope, ASYNC_REQUEST_ASSOCIATE, operation, slot)`；不新增ID。

- request_use必须是真正outer.operation输入Reference，且以固定interface R为expected。独立read形状中，B/L必须本操作准确结果，INVOKE只取同一真实NORMAL边、不同逻辑结果槽；B为Reference、L为RAW。存在旧RequestAssociationRead时从旧row直接派生相同view，不要求重复附件；若另给附件须逐字段一致。
- 内联helper/gate形状只指真正owned actual/result，不虚加RAW/latent参数。combined gate中R必须其实际session角色，B必须其实际body角色；L没有暴露端口就保RAW_OPERAND_PROJECTION_UNRESOLVED，不造结果、不把S冒L。
- 本附件声明“该原接口在适用条件下投影R的B/L”；不是任意同型值等价。query分别保 `expected_projection` 与 `actual_gate_roles`，及每条copy/call绑定。把别的read结果、另一个R的latent或旧evaluation接进gate应拒；真正外部R则保具体来源条件。
- state_sites只列原读/原invoke state operands，before/after/N/R均原记录派生。读取后未知写可以使其当前关联失效；最终gate检查当前R/B/占用，不能按旧read永久放行。
- 本contract无单一“自身结果”；ContractResult不能指向整条association；消费者直接引用body/latent各自原port，不加第二个多结果wrapper。

### 4.2 request首步/已结束的只读谓词

把现AdmissionPredicate.subject显式扩展为下列有限变体，而不是复用BodyStateCondition去读R：

```text
RequestStateRule = IS_INITIAL_STEP | IS_COMPLETE
RequestStateCondition(request_use: UseID,
                      state_sites: tuple[ExistingAccess, ...],
                      rule: RequestStateRule)
```

它只能附着原callback-free READ→自己的bool OperationResult→指定真实BRANCH；只消费真实R和state。不得为它虚加B/L/S参数，也不写request phase。

- IS_INITIAL_STEP的真假分别定位“本次使用L”和“本次续接S”的实际控制路径；必须接到准确gate或真实reject helper。它不自动表示B处于Created。
- IS_COMPLETE定位request复用拒绝；并发/occupancy仍由实际B/R状态读取或最后gate/helper表达，不从此bool推出全局互斥。
- 若native combined helper没有暴露bool/branch，不补假节点：其准确N/R合同与来源条件保留，query将首步/复用分支明确标未解析。它不能冒充已验收的显式谓词正例。
- 新subject的receiver规则必须取R，不沿当前admission_errors的BODY-only owner检查；body自身Created/Running/Suspended/Closed仍取B，二者不可混。

### 4.3 session来源的薄关系

```text
AsyncSessionOutcome(scope: ProtocolScopeID,
                    update: OperationID,
                    source: DriveOutcomeRef | ContractResult)
```

自然键 `(scope, update, source)`。建议归新的closed protocol-binding能力；不改SessionUpdate本身，不存post/actual/state副本。多来源共享同update合法，必须覆盖真实incoming来源；不是强制单corridor。

- update必须命名既有SessionUpdate；R/B由原update Uses、interface和关联投影派生。Drive source须为准确本driver outcome；helper source须为固定clause自身准确selected结果，不能用任意同型result。
- 从canonical CFG派生到update的来源分母，再核声明，不能拿传入sources当许可。删掉一条binding仍留下 `session_outcome_binding_missing`。混合来源共享update时，逐incoming核其期望post；不能ANY来源匹配便通过所有分支。
- 接受AFTER_OPERATION与NORMAL_COMPLETION原shape；宽helper只有实际NORMAL可重建P，RAISE只有真实partial states。原provider若保证callback之后重建post，可保该native条件；不新增preserves_post布尔。
- 从source到update允许真实callback/写，它们杀旧P；新SessionUpdate在其实际after/NORMAL重建P，不假称source旧state一直current。若只是读取旧支持而未真实重建，不授P。

## 5. Proposed：async消费者/post矩阵

| 准确来源 | 必需consumer链 | session/body后果 |
| --- | --- | --- |
| request初次启动 | 固定R/S；scheduler首次输入检查→L的原kind/ordinal→本次Start或Resume/gate | B初入与R首步分别判断；NEXT/显式SEND(None)/非None拒绝不互换 |
| body AWAIT | 本DriveResult→实际scheduler handoff；同R后续S→准确SENT/THROWN或delegate slot；不重播首次L | 当前R/B HOLD；不F、不request item完成 |
| body ASYNC_YIELD | slot0→本adapter自身结果→request iterator本次完成/异常端口→await表达式item | 本次R COMPLETE，B仍暂停；不可用state槽当item，不以host正常/异常表面种F |
| body RETURN | 准确body source→自然结束adapter→当前request真实StopAsyncIteration/host消费者 | R结束与B终结分别发布；原无callbackBodyOutcomeCommit种F，session关系核COMPLETE |
| body RAISE | 当前packet原整体转发或固定显式转换→本次host异常消费者 | 准确terminal publication可F；request的COMPLETE/失败post须真实update，不能由packet类型推 |
| pre-entry/request-only拒绝 | 该helper自己的selected N/R→最新state→host | 不新建BodyDrive，不新F；R后果按该固定native版本合同，不能统一所有失败为COMPLETE |
| aclose非法ASYNC_YIELD/adapter新异常 | 当前违法source→准确错误adapter结果→本次host；后续真实路径仍保留 | 不从请求异常/host exhaustion/native closed bit推出B continuation消失 |

request iterator的StopIteration(item)、await表达式item、body自身自然结束的StopAsyncIteration是不同层级，不能强迫三个host端口都是RETURN或拿旧body payload补位。已有adapter记录足够定位原端口；补固定rule-derived consumer checks，无需新值/producer。

F18源级nonempty return非法只能由真实source/code分类证据覆盖；DataValue/ReferenceValue类型本身不能证明Python语法合法。若无compiler/source锚，保精确source-classification条件。主动StopIteration/StopAsyncIteration与自然RETURN的转换另列固定rule和原exception/packet来源，不按类名字符串判定。

## 6. Proposed：cancel跨site关系，不造scheduler

**容器决定建议**：保旧ProtocolOperation局部Region所有权；新增一个closed `protocol_bindings` union能力，容纳AsyncSessionOutcome及以下三种关系，不复用一个任意RouteLink。所有字段是原引用；无ID、计数器、phase或新producer。scope均指原TASK_CANCEL_EXTERNAL_V1的request site，source沿scope/原合同ProviderFactReference或StaticProtocolGap，不授真实适用。具体Program新schema由root统一；旧Program18及Execution8不偷渡新字段/tag。

```text
CancelDelivery(
    scope: ProtocolScopeID,
    expected_target: ProtocolSourcePort,
    packet_source: ProtocolSourcePort,
    consumer: OwnedUse)

CancelHandling(
    scope: ProtocolScopeID,
    delivery: OwnedUse,
    handler_packet: OwnedUse,
    context_sites: tuple[ExistingAccess | InvokeStateOperand, ...],
    continuation: ControlEdgeReference | StaticProtocolGap)

TaskStatusRead(
    scope: ProtocolScopeID,
    task: OwnedUse,
    result: OperationResult | InvokeLiteralResult,
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...],
    rule: TaskStatusRule,
    consumer: OwnedUse | StaticProtocolGap)
TaskStatusRule = IS_DONE | IS_CANCELLED
```

这里ProtocolSourcePort含已有StaticProtocolGap；不是None/NONE。自然键分别 `(scope,consumer)`、`(scope,delivery,handler_packet)`、`(scope,result)`。同一个request site可有多个实际候选delivery/handler/status；不要求串成唯一corridor，不因此推出它们都发生。

### 6.1 Request与delivery

- TASK_CANCEL_CALL继续引用真实CALL/INVOKE的task receiver/有序实参/自己的N/R result和current state；cancel()的bool仅为本调用结果，不是许可或已注入事实。请求被拒/尚未交付也保固定四clause分母。
- expected_target必须独立来自request task的真实association/lookup原port及该接口来源声明，或TASK_IDENTITY_UNMODELED。禁止把consumer所属Drive.instance直接填expected来证明自身，也不以相同code或唯一Task/body猜关联。若原图根本没有task→body/awaitable关系，保gap，不造Task内部读取/Use。
- consumer必须为原BodyDrive准确THROWN_PACKET输入，或已绑定的await/delegate实际throw/call参数；后一种保持原异常Reference/packet角色，不强迫改造成父BodyDrive。实际receiver由该原操作角色派生，和expected_target逐原copy/call/O对应核。
- packet_source必须为先前真实注入helper结果/入口来源，或显式缺口；不能是同consumer自证，也不能用TASK_CANCEL_CALL返回bool替代。完整packet直接转发；Reference exception按原PacketDefinition组件组成。CANCEL_PACKET_FROM_DELIVERY必须指向这条精确delivery来源，不能任意正常constructor冒充取消。
- producer的selected N/R来自原ProtocolResultPort，注入current states来自原consumer/gate；不添commonAfter。别的scope/旧packet/known错误target/known错误current state为Issue。跨artifact或未建实例对应保持gap，不强判对象不等。

### 6.2 Handler/cleanup

- delivery指精确已登记consumer，不按exception类型或“可达任一handler”找；handler_packet必须经本次Drive输入→body formal，或实际call RAISE→landing route接到该包。packet被原adapter转换时需保转换来源，不能要求所有新包等于旧包。
- context_sites只引用处理本次packet的真实原state接口：ordinary真正READ_WRITE→after，或原INVOKE选中completion所带的context后态；不能为隐式native行为造一个假context-install操作。实际install/source对应仍是明确条件；缺原context锚不宣称handler完整。
- continuation是handler之后真实CFG边，不是手填“suppressed/propagated”phase。沿原packet/CFG/C1派生：捕获继续、重新raise、生成新异常、CleanupEnter/Resume/Replace、再AWAIT等。若走C1 Replace，必须新pending与originalEnter锚及当前context/state；active pending/context/frame跨cut用原SavedSlot，不保存caller token。
- 原普通精确packet传播到终结可由canonical出口派生，无需为“未捕获”制造handler。删CancelHandling仍保原delivery后的handler/terminal义务和未绑定gap；不因它缺失缩掉body/cleanup frontier。

### 6.3 最终status

- task是实际status操作的owned receiver，必须以request scope固定task为expected，同原call-context核对；result必须该status操作本次自己的bool结果，consumer必须用它的准确copy。rule解释真实只读接口的语义，不把bool写回任何Task状态图。
- state_sites属于该status操作；其support只覆盖实际read snapshot/selected completion，未知callback后不声称仍current。INVOKE保N/R partial state，异常读取不能补一个normal bool。
- IS_DONE不等于IS_CANCELLED；cancel请求返回true、交付CancelledError、body某次RAISE，均不能代替最终status读取。catch/suppress后RETURN、cleanup覆盖成别的异常、继续await均保各自实际结果与状态。
- status读取与真正Task完成adapter之间若没有原接口锚，不从body Return/Raise推Task最终值；保TASK_IDENTITY_UNMODELED/TERMINAL_ROUTE_UNRESOLVED。该缺口不能由enum或相同FactRef消除。
- 这些关系只连接现有某个Task实现的原接口，实际asyncio/框架适用由source/version合同证明；不实现通用调度、取消计数、uncancel解释器。

## 7. 机器校验顺序与公共面

1. 先旧core FK/SSA/operation ownership/current state，再旧driver/C1/C2/lifecycle本地shape。建一次scope、association、gate、update、source→consumer索引。
2. 派生固定分母：每ASYNC_REQUEST interface与其所有原gate/outcome、原AsyncRequestCreate/RequestAssociationRead、SessionUpdate、TASK_CANCEL scope四clause。由原marker生成expected obligations后再查bindings；删除binding不删除义务。未知source/site库存保全局gap。
3. 按R/call-context求request projection；逐actual gate/delivery/post核独立expected。共享flow/budget，不按formal/request重建或清零，不枚举完整路径。语义投影保明确native条件，不加入ordinary-copy事实闭包。
4. 按准确source种类核adapter/host/session期望；派生current support与每条N/R，不把partial RAISE回滚。历史F/P/T继续原实现，不由新family标签种F。
5. cancel按scope request→expected target来源→实际delivery→原handler/terminal→原status consumer逐段核；跨Region的local reaches=False不直接作全局错误。无call/O/真实外部桥时条件缺口，不“帮忙”补scheduler边。
6. 最终公开view保 `expected_roles, actual_roles, association_routes, request_step, deliveries, outcome_consumers, session_sources, cancellation_routes, status_reads, obligations, gaps, cursor, budget`。每binding留原records/ports/edges/state support；DECLARED只表示结构声明对应，native/source/runtime/identity/transformation始终各自False/UNKNOWN。
7. 预算截断后固定counts/未查游标仍在，not checked不当mismatch或闭合。新字段/newvariant触发显式Program能力；旧无该能力图保持合法，但P4义务MISSING/UNKNOWN而非自动升级。

## 8. 最小正反验收矩阵（固定分母，不是已通过列表）

| 组 | 正图/必要变体 | 同类型负例、缺失与预期 |
| --- | --- | --- |
| A16.1 | NEXT/SEND/THROW/CLOSE四L真实request create→copy/call→association→gate；创建本身无body | R1关联接R2 body/latent、S/L互换、错ordinal：原来源已知则Issue；外部R缺source为gap |
| A16.2 | 同B两request/同代码不同B；branch两Create保成对context | 独立R/B/L union错误配对拒；删association仍ASSOCIATE义务；不选唯一Create |
| A16.3 | R首步scheduler检查、latent首次交付；bodyCreated的None与非None不同路线；之后真实retry | 错None leaf、旧bool、wrongcall context拒或准确currentness gap；不为谓词添raw/B实参 |
| A16.4 | 同R AWAIT后续驱动；已完成R复用拒绝；另R竞争当前B | 用L重播S、拿bodyphase当requestphase、旧占用支持；callback后gate需重检 |
| A17.1 | AWAIT→scheduler→同R准确slot再恢复，HOLD | AWAIT当item/COMPLETE、另一R session或旧states；Suspend不F |
| A17.2 | ASYNC_YIELD slot0→request iterator完成→await表达式item，COMPLETE而B暂停 | state槽、另一Drive item、错adapter N/R、host结果错来源；不可因request完成release B |
| A18.1 | body自然RETURN→当前StopAsyncIteration路线；source合法空return | 旧payload/无adapter/active exception冒自然RETURN；缺source分类保gap |
| A18.2 | 主动StopIteration与StopAsyncIteration的真实转换/packet/cause/current state | 任意同型packet、自然完成规则吞主动异常；源级非空return按真正compile证据拒，不伪运行body |
| A19.1 | closed/athrow/aclose版本限定真实no-body或失败后continuation路径 | native bit/request完成/host exhaustion误当F，错误NoBodyFinish/释放；无合法来源不给F |
| A19.2 | aclose非法yield→本次错误→后续retry/当前状态，adapter异常单独保存 | 伪bodyterminal、旧packet、RAISE状态退回、吞宽wrapper异常 |
| C24.1 | cancel call返回及尚未交付路径完整；实际注入另有准确producer/consumer | bool当packet、错task/body/旧注入；删delivery关系仍固定义务 |
| C24.2 | 注入→捕获/抑制→再await，原context RW/after与saved anchors | 旧packet/context/pending、假纯Compute handler、caller token跨cut |
| C24.3 | 未捕获传播、cleanup新异常覆盖、正常返回各接真实Task结果/status读 | 请求成功/包类型当cancelled；不同Task status/旧snapshot/异常读补normal拒或具体gap |
| X26.1 | 两session binding、actual partial RAISE、callback杀P后真update重建；共享合流多来源 | source删项仍分母、wrongpost、原owner混接、unknown callback后旧P不能借F恢复 |
| X26.2 | 真terminal publication→窄release；宽raising wrapper独立、traceback保活 | ASYNC_YIELD/AWAIT/request结束种F或重复算free；不是“重复tag就非法” |
| X27/X28 | P3同B多Drive/current ingress/outcome、部分缺采；小budget完整未查库存 | 错实例/代次/线程/selected source；删除scope/关系不空成功；旧wire不能偷带新variant |

这些是16个验收组，组内四request/原边/状态变体不能缩成16个测试；也不是整个P4的16组（父P4尚含await/coroutine/delegation）。未知native适用不撤销已知结构矛盾；结构正例不算自动建图或真实async/cancel运行证明。

## 9. 实施建议与本轮停止点

先共享port/context resolver→request association与首步/完成predicate→精确async adapter/session来源→cancel跨site/handler/status→C1/P3/release组合→统一wire/ledger预算验收。归属应按这些模块清晰分工，不能三个agent各建一套flow。取消新closed bindings与session来源属于必须新增的连接；原body producer、request RAW enum、StateVersion/CallActivation/O occurrence模型均保留。

本轮只提交接口建议，root冻结字段/容器/能力后再实施。没有声称native family、自动恢复、M0–M2或P4已完成。

## 阅读时源码SHA256

- docs/M1_REMAINING_PROTOCOL_PLAN.md `87a5c029e4a1666b4f8fc73bf7d3886329c64ce8e8f707f76314f35f16676317`
- docs/M1_PROTOCOL_CONTRACT.md `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac`
- docs/M1_DRIVER_LIFECYCLE_CONTRACT.md `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`
- program/protocols.py `a51bd800af0b767e8477b95a07aa77ff0a47a0de3222c2804818c295b215fc03`
- program/protocol_rules.py `be4b601e16401f677b4cbf4e7ba4d2b2d895f4364ce4d1f90d68ed778f92dbe1`
- program/protocol_flow.py `a3518f4fa83ceba2d748d0b7e5d44fbc1ac7c0f629e103d8aad3c0c852ba87a7`
- program/protocol_validation.py `963e352d3b88ff6d4dcdd220542130fe873859d3f0610af8ab7c44e07a45b049`
- program/protocol_query.py `1b17e1e55128d0af2a1080c6e85a3d00f8582e7b5ae7597fdb7f28f3ca9e64ba`
- program/drivers.py `d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd`
- program/driver_validation.py `cdd8439fb1cd63c3ecd52c42f796a4c0cf15ec53591b0859f25137bee2f0e4d6`
- program/resumption_validation.py `3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a`
- program/lifecycle.py `326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7`
- program/session_release_validation.py `b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc`
- program/session_flow.py `13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387`
- program/lifecycle_flow.py `9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7`
- program/input_origins.py `6212a9aeb8a170387f102ba02be4ae480d641075e52232ded09ac5fca4866631`
- program/request_inputs.py `2c93d60c50f786d7e603e5a38314c77fbfb48f4d1a38f4385e05ea42da865415`
- program/cleanup.py `79b5888885bf8c4ad50df77e8f6dc7ffff4e5aa8956aca9010a98a055cbd372c`
- program/queries.py `2a222943035c912ee71d7eb14ac2386a8df9b5e30631f78d72a8093b6cdfddc7`
