# C2D.0 claim / lifecycle 独立审查

2026-10-18；只读产品基线 `012db08`，工作树初始 clean。读了已归档 `driver-field-contract.md`、`driver-root-review.md`、主 resumption 合同及现 C2B/core/C1 实现。本报告 API 为待冻结修正，不是已实现 validator。
只新增本前缀报告、stdlib 探针和日志；未改产品/tests/docs，未跑 full、应用 LeWM、GPU、采集或安装，未 spawn。

## 1. 阻塞项与选择

现提案**尚不能冻结**。至少须闭合四项：原始 THROW 被过早归一化；step permit 混合持续 session 及 body generation；gate 接受结果缺明确 admission/cursor 条件；提交/release 缺同一次 permit 的操作点 outcome 与 no-body-close 后置关系。

建议采用：**一个短命 permit 至多授权一次直接 BodyDrive；每次新的 ingress 重新 gate；跨 host/await 的 session/lease 只保存在对象当前 lifecycle state。** 不新增可跨 host 保存/返回的私有 lease ProtocolValue，也不让旧 permit 自动续代。多个子 gate 可以发生在一个外部方法调用内；这不等于修改该方法的外部语义。
一个 persistent request session 可跨多个 scheduler `.send/.throw` 调用及多个 body generations；每次调用/子步获得新 permit。body 的某代 continuation、一次 gate 接受的 epoch、request session、外部 host method call 必须分开。
若未来允许同一个 permit 授权多个 BodyDrive，必须增加**规范 successor-permit/cursor 结果**及其到上一实际 outcome 的精确 lineage；仅增加 `multi_use`、owner/site 或次数声明不够。当前无此需要，优先采用新 gate 方案。

## 2. 三个真实最小观测

探针 `claim-lifecycle-probe.py` 使用 conda `lewm` 的 CPython **3.14.7**，只用 stdlib，无事件采集器。首跑 exit 0，原始输出保存在 `claim-lifecycle-probe.initial.log`；追加 raw-throw 个案后第二次 exit 0，输出另存 `claim-lifecycle-probe.raw-throw.log`，未覆盖首跑。

1. **外层 `.throw(ExceptionSubclass)` 内两次 body ingress**：异常类构造器先 `next(instance)`，得到第二个 yield；外层 throw 随后在新暂停点注入，body 再次运行并 yield `caught`。外层调用内记录到两次 ingress。故“1/外部 host call”不成立；嵌套 normalization callback 是另一个 driver epoch，不能因外层方法尚未返回而禁止它。
2. **asyncgen request 跨内层 await**：第一次 `asend(None).send(None)` 返回 scheduler token，`ag_running=True`，frame 存在；另一 asend 被 RuntimeError 拒绝。原 request 再驱动后以 StopIteration(`ready`) 完成该 item 请求，`ag_running=False`，但 body frame 仍存在。结束一个 step、完成 request、关闭 body 是三个不同事件。
3. **delegate.throw 收到 raw 三参**：Exception class、value marker、非法 traceback object 原样送达自定义 delegate.throw；delegate 直接返回 item，异常构造器未执行，也未触发 traceback TypeError，仅出现三参形式的 DeprecationWarning。外部 THROW 不可先做 packet/traceback normalization。

官方实现依据：`_gen_throw` 先找 delegate.throw 并按原参数调用，fallback 才检查 traceback/归一化，见 [genobject.c:476–547](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L476)。asyncgen asend 在内层 await 返回时维持运行所有权，用户 async-yield/终结另处理，见 [genobject.c:1621–1711](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L1621)。这些是版本依据及小例观测，不是所有协议路径的实测。

## 3. 最小 exact 字段修正

实际数据仍只放 canonical Operation.uses/results、invoke_arguments、CompletionResult、BlockArgument 和 StateAccess。以下索引只引用这些端点，不复制 Value 或另存 producer/CFG。

### 3.1 raw request 与 body delivery

```text
DriveRequestDefinition(value: ValueID, kind: RequestKind,
                       operands: tuple[UseID, ...])
```

封闭 arity：NEXT/CLOSE=0，SEND=1，THROW=1..3；所有 operands 是 pack 的独立 owned Reference Uses，顺序原样保存。缺省参数与显式 None 引用不同；不得在 pack 时按 Reference 类型判异常类/实例、合法 traceback 或自然 exhaustion。
这替换草案 `driver-field-contract.md:60,69–73` 的 THROW→EXCEPTION_PACKET。async request 的 latent 原始请求也用此类型；driver entry 的**本次 scheduler/request-object drive 请求**是另一实际端口，不能拿 latent request 代替后续送达值。
body 的 `ResumeInput(THROWN_PACKET/DELEGATE_PACKET)` 保持现 C2B 类型。raw→normalized packet 的工作使用真实普通/INVOKE helper、完整 normal/raise 与当前状态；可加 `RequestNormalization(operation, raw_argument: int, packet_result: int, rule)` 元数据定位其 canonical 输入/结果，不声明 pack 本身完成归一化/chaining。
不要冻结全局“gate→normalize→delegate”或“normalize→gate”顺序。CPython throw fallback 的 normalization callback 可在 body 执行保护前重入；delegate 方法查找也在其调用保护前。每条版本化 CFG 路径必须记录真实步骤/效果，再在 body ingress 前用其**最新**后态 gate/输入。已有 packet 不证明 mutable traceback/context 写已完成。

### 3.2 association 与当前 session state

```text
AssociationRead(operation: OperationID, request_argument: int,
                body_result: int, latent_request_result: int,
                lifecycle: LocationID, rule: DriverRule)
```

这是普通 lookup/INVOKE 的类型合同：request_argument 指当前 request-owner Reference；两个 NORMAL result 槽分别为 body Reference 和 raw request ProtocolValue；其余当前域、失败/部分状态继续既有 completion。展开 helper 用真实 StateAccess；opaque native 也保留这几个 typed 端口和当前全域后态，不靠 body/site 名称补关联。
`AsyncRequestCreate` 保留实际 body-instance/latent-request 参数和 request-object NORMAL 结果；AssociationRead 的出处必须是该请求对象当前内容的规则，不是两个对象同属一个 body 就可相互替换。
session/lease 状态保存在 request/body 当前域；不存可跨 host 的私有 permit。每次重新进入读取当前关联并 gate。一个 coarse LocationID 可以装多个对象，**相同 LocationID 不证明同 owner、相同 request 或独占**。

### 3.3 gate 与短命 permit

```text
DriveGate(operation, owner: GateOwner, owner_argument: int,
          request_argument: int, lifecycle: LocationID,
          permit_result: int, admission: BodyAdmission | RequestAdmission,
          session_request_argument: int | None)

BodyAdmission = StartAt(creation: OperationID)
              | ResumeAt(suspend: OperationID)
              | NoBody(disposition: NoBodyDisposition)
RequestAdmission = START_REQUEST | CONTINUE_REQUEST | CLOSED_REQUEST
NoBodyDisposition = PRESERVE_CURRENT | CLOSE_WITHOUT_BODY
```

这里将含混的 instance_argument 改为 **owner_argument**。BODY gate 的 owner 是 body Reference，ASYNC_REQUEST gate 的 owner 是 request-object Reference；后者 permit 不直接用于 BodyDrive。permit 只由登记 gate NORMAL 的规范 completion slot 产生，RAISE 不产生；不得从普通未知 Operation、入口或任意 helper completion 伪造。
BODY gate 的 session_request_argument 在 async-request 驱动时必须连接对应 request Reference；owner 必须沿 AssociationRead 的 body-result/must-copy 路径而来。gate 当前状态合同明确检查“该 request 当前关联并持有该 body”，不能只比较 Reference 类型/Region/site。普通同步 body driver 则该参数为 None。
ResumeAt 固定当前暂停 **site**；BodyDrive 只能进入该 Suspend 的真实 case，case/送达 payload 由后续显式协议路径确定。StartAt 只授权相应 creation；NoBody 禁止 ingress。这样 gate 的声明许可范围有精确字段，动态实例/代次匹配仍是实际 guard 的义务。
若 driver 先委托再决定是否入 body，其 NoBody 路径可终止当前 step；入 body 的路径仍必须有适配该当前暂停点及最新状态的许可。新 gate 是校验/子步，不必伪造一次新的外部方法调用或重新执行 Python 参数绑定。
permit 只在当前 driver activation 普通 CFG 中逐边复制；不进 body saved slots、对象 state、ordinary call actual、普通 host exit、closure 或 persistent session。登记 gate 的专用私有结果边界是唯一例外；若展开成 helper，须有精确 GateHelper producer/port 映射，不能顺势解禁一般 helper 私有返回值。

### 3.4 提交：分开 step、body 和 request 的后置关系

原 `END_NO_BODY/PUBLISH_SUSPEND/FINISH_BODY/FINISH_REQUEST`（草案 `159–174`）不足以区分所有三层。建议将一次 commit 的后置效果用封闭组合表示，字段仍只引用当前 Uses/access 和精确 outcome edge：

```text
StepCommit(operation, permit: UseID, owner: UseID, access: int,
           outcome: ControlEdgeReference | None,
           effect: EndNoBody | PublishBody | FinishBody)
EndNoBody(disposition: PRESERVE_CURRENT | CLOSE_WITHOUT_BODY,
          witness: ControlEdgeReference | None)
PublishBody / FinishBody: outcome 必须来自本 permit 的实际 BodyDrive edge

RequestSessionUpdate(operation, request_argument: int, body_argument: int,
                     source: ControlEdgeReference,
                     effect: HOLD | COMPLETE | ABANDON, rule)
```

StepCommit 可以是无回调状态 intrinsic；真实 retain/release/lookup 仍独立操作。RequestSessionUpdate 引用真实当前状态操作/helper及其后态，不产生跨调用 token；若 helper 会回调/失败，使用普通 INVOKE 并分别保存结果后态/规则，不能把它改装成纯 metadata 后隐去失败。
PublishBody 结束本 permit，但不自动 COMPLETE session；asyncgen AWAIT 通常 HOLD，ASYNC_YIELD 通常完成当前 item request 而 body 仍暂停。具体 method/family 的成功/失败后置表必须版本化，不把这些“通常”直接当通用默认规则。
EndNoBody(PRESERVE_CURRENT) 意味着本步不另消费 body continuation，不是把 generation 倒回外层方法调用前：之前 normalization/delegate callbacks 已有的推进继续存在。CLOSE_WITHOUT_BODY 只接受明示 Created-close 等成功 witness，可以授权无 body 的终结/release；不能由任意 helper NORMAL/host RETURN 推出。
FrameRelease.owner 必须是实际 body owner；其 completed witness 与本 permit 的 FinishBody，或 CLOSE_WITHOUT_BODY commit 精确同路。request-object 的引用释放应另标 subject，不能以 request 完成直接授权释放尚暂停的 body frame。所有真实释放后继续当前全域后态，失败/不返回也不恢复旧 snapshot，不承诺物理全部释放。

## 4. 可机械检查的 CFG 固定点

不能仅复用 C1 的 must-copy 结果就宣布 permit 未消费。现 `cleanup_forward.py:30–58` 证明的是“各 incoming 均来自锚”，不证明同一锚曾否已用于一次 BodyDrive。

建议在每个 driver Region 的真实 ordinary/BodyDrive completion 边上做**操作点状态**工作队列；不用 body temporal 边把下一次 host 调用混进本次 permit。状态同时包含当前 permit 的规范 Value（或 block formal）、owner role/实际关联、阶段和最后实际 outcome edge：

```text
NONE --gate NORMAL--> READY(admission, active permit)
READY --BodyDrive--> OBSERVED(exact completion edge)   # 每条 outcome 边各自更新
READY --EndNoBody--> STEP_DONE
OBSERVED(Suspend) --PublishBody(same edge)--> STEP_DONE
OBSERVED(Return/Raise) --FinishBody(same edge)--> STEP_DONE
STEP_DONE --new gate NORMAL--> READY(new permit)
```

1. 每个实际 incoming 参与；MAY 状态集合从 entry 的 NONE 做最小固定点，循环直到不变。某操作的前置条件须对**所有**进入状态成立；不以一次文本 Use/constructor 集合证明合法。
2. 有 permit 的 block 声明唯一当前 permit formal；每条普通边的 actual 必须是该点的当前 permit Value，传到目标 formal。分支不同合法 gate 可各传自己的当前 permit；不能通过集合相等混过反选。gate 重新接受是唯一 READY 重置点，回边绕过 gate 不重置。
3. Claim 来源另做 seeded must-copy：普通 Use→formal 传播，外部边/其他 producer 为 False；先 OR-LFP 限定有种子区域，再 AND-GFP 闭合，拒无种子环。若按单 gate 做锚，切断重新进入其 NORMAL landing，防上一 visit 静态同 ID 冒充；多 gate 合流要保留逐边“当前 permit”关系，不能要求所有合法分支只有一个 constructor。
4. BodyDrive 消费 READY，即使旧 permit Value 在 SSA 上仍 dominate 后续，也不能第二次 ingress。Publish/Finish 必须消费当前 OBSERVED 的**同一实际边**；只在字段里引用一个现存 source site 不够。需要在合流后提交时保留来源关系，或先在各私有 completion corridor 提交，再合流。
5. step 内每个实际 host exit 必须满足已完成适当 commit、没有可用 permit；reject 路径无该 gate 的 permit/BodyDrive。可能发散的路径不被强迫虚造 commit/exit；循环再次 gate 需要先结束旧步。
6. request-step permit 与 body permit 使用不同 owner role/参数槽，不能交叉授权。session 的 HOLD/COMPLETE 等声明沿 request/body 当前关联传播，跨 host 后由 AssociationRead/gate 重新建立，不把上次 permit 当入口参数。
7. 普通 state SSA 独立检查 gate/helper/ingress/commit/release 的 current versions；body Attach/Detach、C1 activation/fresh 和 availability cuts 继续现规则。不能为了 claim 分析删除真实失败边，或沿 body temporal edge恢复旧 driver state。

这验证静态声明的执行顺序与来源，不证明实际 helper 原子 acquire、对象别名归属、动态 visit 唯一或硬件并发互斥。

## 5. 反例 → 最小规则

| 具体错误/合法路径 | 最小规则 |
| --- | --- |
| gate→BodyDrive→Suspend publish→普通回边再次用旧 permit；静态 Use 只有一处 | READY 被首次 ingress 消费；不经新 gate 回边不能重置，拒第二 ingress。 |
| 左支当前 permit=A 却转发旧 B，右支当前=B 却转发旧 A；两支 constructor 集合相同 | ordinary edge actual 与当前 permit 逐点相等；来源集合不代替 current token 关系。 |
| BodyDrive Return/Suspend 两边合流后，一律引用 Return edge 做 FINISH/release | last-outcome 随真实 completion edge 传播；所有入路都匹配，Suspend 路径不得 FinishBody/release。 |
| async request 内部 await 后释放 session；另一 request 趁 body 暂停进入 | 本 step publish 与 session HOLD 分开；BODY gate 检查 request/body 当前关联及 lease。探针已观察竞争请求应拒绝。 |
| ASYNC_YIELD 令请求完成，从而把 body 标 Closed/释放 frame | Request COMPLETE 与 Body SUSPEND 独立；body completion 必须真实 Return/Raise 或 no-body-close witness。 |
| close 时 body 再 yield，host 报 RuntimeError，于是一律 FINISH_BODY | 先 PublishBody，再 host error；host RAISE 不能作为 body 完成证据。 |
| Created-close 无 body，却只能用 END_NO_BODY，随后无法合法 release；或伪造 Return | 明示 CLOSE_WITHOUT_BODY 成功 witness/后置关系；不要求 Attach/Detach 或假 body outcome。 |
| 外部 throw 统一 packet 化，delegate 无法收到原参数；normalize 前 acquire 又阻止合法 callback 重入 | raw request 与 normalized body payload 分层，按实际路径阶段排序；探针已反驳统一顺序与1/host-call。 |
| request R1 与 body B2 共享 code/world，拿 R1 的 permit 驱动 B2 | owner_argument 与 session_request_argument 分工，AssociationRead→must-copy→gate 当前关联；Location/site 相等不构成证明。 |
| release 回调写全局/重入后却交还旧 gate/body world | 完整 normal/raise 当前后态；后续 ingress/host exit 只用 release/helper 后态。 |

## 6. 验收与外部证据边界

声明级可验：exact 类型/arity/slot/owner-role；canonical actual 来源；正常接受锚；每路 permit 相位；精确 outcome/commit/release 关系；当前状态；no-body、request-only、body 路径分离。可保守覆盖所有实际 body outcome sites，不伪造 C1 未发生的 ExitPort site。
仍需单独证据：raw方法到真实调用参数对应；实际对象与动态 creation/activation/generation 对应；native gate/session 状态与规则一致；原子排他；callback/finalizer真实顺序；完整 request×状态族与 actual guard 效果。静态 permit、类型/site、同 LocationID 或 use 数均不授这些证明。
本报告选择有字段/后置关系的声明合同，不用空 UNKNOWN 补接口，也不要求完整 Python 前端。可先实现有限人工 IR/typed opaque boundary；未知实现保留完整效果/失败和待证对应，不提升为已执行 body 或合法 runtime。
结论：上述四项进入共同冻结稿后可再做有限字段复审；当前 C2D.0 不通过，产品 C2B 与整体第一阶段的既有状态不因本报告改变。
