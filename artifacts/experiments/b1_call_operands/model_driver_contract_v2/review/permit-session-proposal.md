# D0 v2：窄 final-gate corridor 与普通 session state

2026-10-18；按任务基线 `499d708` 只读设计。读当前 `docs/M1_DRIVER_INTERFACES.md`、
已冻结 `claim-lifecycle-review.md` 及 core 的 Use/completion/current-state 约束。
本报告是可实施的候选字段与算法，未实施、未运行探针/测试，未执行 git；未改产品、
tests、docs 或旧证据。已与 core reviewer 对齐 canonical completion/Use 接线。

## 1. 决定：取消可跨 CFG 的 permit Value

采用 **final admission INVOKE → 私有 NORMAL landing → 唯一 BodyDrive**。
不增加 DRIVE_PERMIT/CLAIM ProtocolValue、通用 affine 分析或持久 lease token。
许可只存在于这条 canonical NORMAL 边的结构合同，不在用户 CFG 中传递。

不能直接把 admission 藏进一个不可见的 BodyDrive 前奏：mark RUNNING 的后态必须有
真实 producer，body 必须读该后态。现 `model.py:598`–603 的普通 INVOKE 已有
CompletionResult → landing BlockArgument；用它生产 admission 后状态，BodyDrive
再把这些当前状态接入 body。无需新建中间 world、before/after 表或 producer。

这是 final body gate：NORMAL 必须直接进入 body。closed/exhausted、Created-close、
delegate-only item、request-only 等 accepted-no-body 路径在它之前或之外由 typed
普通 helper 表示，不强行通过这个 NORMAL，不制造 body Return。

## 2. exact records：只引用现 canonical 端口

下列新记录均 frozen/slots，enum/record exact；索引为非负 exact int，拒 bool。
现 DriverRule 继续是 implementation/version/method/source 的有出处规则，非 verified 位。
方法/family 的实际 callable 对应仍需来源/guard；同名用户方法不自动取得合同。

```text
ReceiverKind = BODY | ASYNC_REQUEST
RequestKind = NEXT | SEND | THROW | CLOSE

DriverInterface(region: RegionID, body: RegionID,
                receiver_kind: ReceiverKind,
                receiver: EntryPortRef, scheduler_request: EntryPortRef,
                lifecycle: tuple[LocationID, ...], rule: DriverRule)

RawRequestDefinition(value: ValueID, kind: RequestKind,
                     operands: tuple[UseID, ...])

RequestGate(operation: OperationID, receiver_argument: int,
            scheduler_argument: int, rule: DriverRule)

RequestAssociationRead(operation: OperationID, receiver_argument: int,
                       body_result: int, latent_result: int, rule: DriverRule)

FinalBodyGate(operation: OperationID, drive: OperationID,
              body_argument: int, scheduler_argument: int,
              session_argument: int | None,
              delivery_arguments: tuple[int, ...], rule: DriverRule)
```

- 每个 driver Region 恰一 DriverInterface；body 必为已声明 ResumableBody。receiver 是
  当前外部方法调用的固定入口对象 Reference：BODY 模式为 B，ASYNC_REQUEST 为 R；
  scheduler_request 是本次 next/send/throw/close 原始请求 S 的真实入口协议参数。
  此 fixed role 不表示静态 ValueID 等于动态对象 ID；同 driver 可服务不同动态实例。
- lifecycle 是该 adapter 使用的 request/body 生命周期域的非空去重 tuple；允许二者
  共用 coarse world。它不声明域内只有一个对象，也不把 LocationID 当 owner。
  三种操作从 owning interface 取这些域，不在每行复制 locations/before/after。
- 三个操作字段中的 argument 均索引自身 Operation.invoke_arguments；故都是现 INVOKE
  的真实 owned Use。结果索引仅指 NORMAL CompletionSignature 的结果槽。
- RequestGate 仅用于 ASYNC_REQUEST；检查当前 R/S 并做该次 request-step 的真实状态
  更新，NORMAL 表示本次调用经过 request admission，不产生 body 许可或私有结果。
  RAISE 是该 helper 的拒绝/失败及其完整当前后态。它不是 final body admission。
- RequestAssociationRead 的 receiver 必从固定 R 复制；NORMAL 两槽是关联 body
  Reference 与 latent RawRequest。关联读取/存储及其状态访问须是真实 helper 操作；
  opaque native 也保留这些 typed actual/results 和完整失败，不按同 code 配对。
- NEXT/CLOSE operands=0、SEND=1、THROW=1..3 Reference；omitted 与显式 None 有别。
  pack 不做参数语义校验或异常构造。body 的 THROWN_PACKET 仍为 EXCEPTION_PACKET。
- FinalBodyGate.body_argument 是 B；BODY 模式要求从固定入口 B 复制，session=None。
  ASYNC_REQUEST 模式 session 是固定入口 R，B 来自针对该 R 的 AssociationRead；
  gate 在当前 state 上再次检查 R 当前关联 B、request phase 和 body/session 占用。
- scheduler_argument 必从固定 S 复制。latent_request L 与 S 独立；L 只用于真正的
  request 协议/归一化路径，不能按同类型替换 S。L 是否不可变由版本规则/实际 state
  操作说明，不能由一次旧 lookup 自动推出；final gate 重查当前 request 资格。
- delivery_arguments 按配对 Drive 的非 state 动态输入槽顺序列出 gate 输入索引。
  不产生另一份 actual 列表；它只连接已存在的 Uses。每个角色用独立 owned UseID，
  即使多个角色当前指同 Value 也不合并端口。

## 3. final corridor 的规范接线与不可省略拒绝项

BodyDrive 仍需专用 canonical terminator；普通 INVOKE 的 NORMAL/RAISE 不能表示 body
Suspend 或精确 resume landing。此处只冻结其与 gate 相关的 ports：

```text
BodyDrive.target = BodyStart(body) | BodyResume(suspend, successor)
BodyDrive.owner: UseID
BodyDrive.scheduler_request: UseID
BodyDrive.session: UseID | None
Operation.invoke_arguments = 唯一 body 动态输入 actual 列表
```

owner/S/session 是该 Drive 的独立 owned Uses，非第二份 body actuals。Start 的私有
captures/Resume 的 saved slots 由实例及现 C2B 机制关联，不复制为普通 driver actual。
目标/输入 signature/首 outcomes 复用 canonical target 与现 frontier，不能另存结果图。

对每行 FinalBodyGate(g,d) 机械检查：

1. g 是本 driver Region 的现 INVOKE；NORMAL 与 RAISE 是真实不同 completion 边。
   d 是同 Region 唯一配对 BodyDrive；每个 BodyDrive 恰被一个 g 配对，不准自行 ingress。
2. NORMAL target h 有且仅有这条真实 incoming；h.operations 恰为 `(d,)`。不是“无效果
   操作可插入”，而是零操作间隙。禁止 branch、普通 call、callback、state 写、循环、
   release、normalize、Attach 或其他 protocol op 插在 g 与 d 间。Attach 属于 body。
3. g 正常 completion 的非 state identity 不用 CompletionResult 生产。对 d 的每个
   owner/S/session/delivery Use，令其 Value 为 h 的 formal f；从真实 NORMAL edge
   找 f 的 actual u，u 必是 g 的 owned forwarding Use，并满足
   `value(u) == value(g.invoke_arguments[对应角色索引])`。逐槽核验，不能比较 origins 集合。
   角色槽分别保留；delivery 顺序由 target signature 确定，不按 Value/type 猜配对。
4. g 的 invoke input UseID 与 NORMAL forwarding UseID 必须不同；两者可指同 Value。
   RAISE forwarding 也用自己的 UseID。现 `validation.py:219`–234 已要求所有控制输入
   槽的 Use 精确独占，重用一个 UseID 会被拒绝。
5. g 传入 driver 当前所有 state 域 D，NORMAL 每域恰一个 CompletionResult → h formal；
   不以转发旧 Use 冒充 admission 后 state。RAISE 也完整保留当前各域后态和真实异常
   packet，不能推定失败无 effects 或把它标成 body Raise。
6. d 的 body state actual 按 LocationID 从上述 NORMAL formals 精确取得；body 需要的域
   必须是 D 的子集，缺失拒绝。D 中 body 不用的域按每条 outcome 的独立 Use 转发，
   不能产生假的 body state result。目标可不含 driver 独有域，不要求两者域数量相同。
7. d 的 Resume payload 在 g 之前已实际构造；g 的正常路径不得归一化用户异常、调用
   delegate、释放引用或再次切换 continuation。g 成功标 RUNNING/登记本次进入，状态
   producer 为 NORMAL formal，body Initial/Attach 或 landing Attach 随后读它。
8. gate 的 RAISE target 不是 d，不能把该拒绝边标为 d 的已执行 outcome；后续普通
   host adapter 可以再失败或正常返回，不构成 body 完成。no-body helper 也不能借用 g。

## 4. 哪些是 intrinsic，哪些必须保留实际 helper

**只有 final gate 的成功检查/mark RUNNING 是小型无用户回调 intrinsic 合同。**
它只读真实 owner/request/delivery 与当前状态，执行版本化 admission 判断并更新
lifecycle，再直接 NORMAL 给 d。不能在“已 mark RUNNING、尚未进 body”的窗口回调。
若用 opaque native 实现，须带同一条件语义；若展开，真实 StateAccess/RETURN 生产
该状态，展开不能另算一次 native 执行。静态 validator 不从 effects_complete=True
或写出一个新 state 推出无 callback/原子性；该 intrinsic 的实际实现对应需单独证据。

拒绝 packet 构造可在 gate helper 的真实失败路径，但有用户可见 hook/回调/失败就
必须按实际普通操作/INVOKE保留，输出最新各域；不能用“失败不执行 body”删这些效果。
这里保证的是拒绝不走本配对 d；独立回调里的嵌套 driver 不受这个结论禁止。

RequestGate、AssociationRead、raw→packet normalization、delegate lookup/call、引用
retain/release、request/session 更新、host exception adapter 皆为真实普通 helper/
INVOKE 或已展开 StateAccess。确实只有无回调状态 store 时可用普通小操作；有 drop、
lookup、错误构造或 callback 则必须保留其 normal/raise/不返回路径。它们不携带 permit。

## 5. 全 CFG 算法：有限父阶段 + 当前状态，不造 affine 系统

先复用 core 的完整结构、def-use、dominance、当前 state、C0/C1/C2B 检查。以下只在
一个真实 driver invocation 的 ordinary/completion CFG 上运行，不走 body temporal
边，也不把 caller 的下一次方法调用并到本 invocation。

### 5.1 固定入口角色的 must-copy

分别以 receiver 与 scheduler_request 两个 entry Value 为 anchor。仅沿真实
Use→BlockArgument actual 复制；其他 entry args/OperationResult/CompletionResult 不当
copy。先做 anchor OR-LFP，再将其外固定 False 做 AND-GFP 闭合，所有 incoming 参与；
拒无种子环和反选 phi。可复用 `cleanup_forward.py:30`–58 的算法，但不复用 C1 scope
语义。driver entry 本身只由当前 invocation 定义；不接受来自普通回边重置入口锚。

RequestGate/AssociationRead 的 R/S、FinalBodyGate 的 session/S 必须满足各自固定
角色。BODY 模式的 B 同样检 receiver anchor；ASYNC_REQUEST 的 B 沿 AssociationRead
结果和真实 copies 到 final gate，各个来源的 read 都必须消费同固定 R。不同 read
site 合流可以接受，但“这些 lookup 都消费 R”只说明声明来源，不证明旧读取仍是当前
关联；final gate 必须重新核验当前关联。这避免把 constructor/site 集合相等当配对。

窄 corridor 内另做 §3 的逐槽精确等式；即使左右两支给出相同 origin 集合、却把 B1/
B2 或 S/L 反选，也不能绕过入口 role 与 gate→d 端口对应。无需推导“当前 permit”。

### 5.2 request gate 的 parent 关系

ASYNC_REQUEST 用最小操作点 MAY 固定点，entry 为 `{U}`。阶段只有 U（本 invocation
尚未成功 request-admit）与 A（曾成功 admit 固定 R/S）。RequestGate NORMAL→`{A}`，
RAISE→`{U}`；普通操作/真实 callback completion 保留该历史阶段。合流是集合并集，
从 entry 做 LFP；final body gate 要求所有进入事实均为 A。不同合法 request-gate
site 可合流，不要求相同静态 producer；固定 R/S 的 must-copy 独立保证身份角色。
BODY 模式不需要 A，也不伪造 RequestGate。无需 parent token 或 parent OperationID。

A **不是当前状态仍合格的证明**，不能免除 final gate 的当前关联/占用复查。
callback 可以关闭 R、推进/关闭 B；A 作为“本次调用走过父阶段”的历史仍真，随后
final gate 可拒绝。再次 RequestGate 会按其真实 completion 重设阶段，不产生续代
许可。退出 Region 就结束该历史事实；不得存入 state 或传给下一次 host invocation。

### 5.3 状态 epoch 完全使用现 SSA，而非静态计数

维护 core 已有的 `current[LocationID]`：StateAccess READ/RW 消费当前 before；写后
取 OperationResult；普通 INVOKE 各 completion 更新为其实际新 formals，未知 effects
保留各域部分后态。普通边 actual→formal 按既有规则转发；合流由真实 phi 接当前值。
final g 只取当点 current；g.NORMAL 生产 post-admission current；d 立即消费它。
所谓 drive epoch 只是这次 g completion→d 的动态解释，不新增整数、ID 或 token。

有 callback 或任意 state 写只能在 corridor 外；之后重新执行 final g，不能拿之前
的成功边当资格。循环 d→outcome→callback→g→d 合法；d→旧 h 或绕过 g 回 d 因 h
独占 incoming/唯一 pairing 被拒。静态同一 g 在 loop 重访不证明唯一动态发生，但
每次解释都执行当前 admission，绝无旧 permit 可复用。无限路径不强迫虚造 ingress。

## 6. 持久 session 的完整接口边界

普通对象 state 中的 body life、request life、session association 是不同字段/规则。
例如 body 暂停在 AWAIT 时可仍由 R 持有；ASYNC_YIELD 可结束 item request 而 body 仍
暂停。这里只规定有字段的条件接口，不把某个 CPython 标志直接等同全部逻辑状态。

与 outcome reviewer 对齐：

```text
SessionUpdate(operation: OperationID, request: UseID, body: UseID,
              source: ControlEdgeReference,
              post: HOLD | COMPLETE | ABANDON, rule: DriverRule)
```

request/body 是该普通 op 或 INVOKE 的真实 owned args，R 须来自本 interface receiver，
B 与实际 source/gate 的 owner 路径一致。lifecycle 域从 interface 派生；before/after
只取 StateAccess 或 canonical completion。source 是本路径真实 body outcome 或
明示 typed no-body helper completion，不能从 host Return/Raise 名字推出。
普通 op 成功或 INVOKE NORMAL 才承诺 post；RAISE 只承诺实际部分后态。HOLD 不保存
permit；下一次方法调用重新 RequestGate/AssociationRead/final gate 读 current state。
COMPLETE/ABANDON 结束 request 关系，不自动关闭 body/授权 frame release。

BodyOutcomeCommit、NoBodyFinish、release 的精确当前 source/outcome 对应由另一份
生命周期提案细化；本方案不为它们增加 claim 参数，也不把 final gate RAISE 充当来源。

## 7. 最小正反路径与实际可证明范围

| 路径 | 本方案结果 |
| --- | --- |
| normalize THROW 的异常构造器调用 nested next，推进 B 后返回；外层按最新 target/state gate→d | 允许。nested driver 有自己的 invocation/门；外层没有旧 permit。需真实 target dispatch/guard 对应，不能继续读旧 state。 |
| raw 三参直接给 delegate.throw 并返回 item | 普通 no-body 路径，保留原参，不要求 packet 或 final body gate。 |
| async R gate→lookup R→B/L→body gate→AWAIT→HOLD→host 返回；下一次调用继续 R | 允许；第二次重新读取状态，另一 R2 的 gate/current association 检查拒绝竞争。 |
| 同 host invocation 内 outcome 后继续另一个 final gate→d | 允许；不是一 hostcall 只准一次 ingress；每个窄 pair 自行 admission。 |
| gate mark RUNNING 后 normalize/callback/branch 再 d | 拒绝 corridor 结构；把真实工作移到 gate 前并用最新 state。 |
| gate NORMAL 用 CompletionResult 重新“产生”B/R，或 invoke actual 与 edge 共用 UseID | 前者拒绝身份端口接线；后者由 core control_binding 拒绝。 |
| phi 把 S 与 latent L 反选；gate 验 B1 却 d 用 B2 | 固定角色 must-copy/逐槽等式拒绝，origin 集合相同无帮助。 |
| 最初 op 前态或 gate 前态直接送 body | 拒绝：body state 必取 gate NORMAL 后 formals。 |
| final gate RAISE→host Raise→FINISH_BODY/release | 拒绝来源：没有本配对 d 的 body Return/Raise。 |
| close 时 body Suspend、host RuntimeError；因此把 body/session 一起 Closed | BodyOutcomeCommit 必仍按 Suspend；host Raise 不证明 body 完成，session 按实际版本 post 单独处理。 |
| created-close 无 body，typed helper 成功后 release | 不走 final body gate；需真实 TERMINATE_BEFORE_ENTRY witness，不伪造 body outcome。 |

可机械证明：record/arity/type、入口 roles、每条真实 incoming 的 copies、parent U/A
阶段、gate→d 唯一邻接、身份/交付逐端口对应、admission 后 state producer 与消费、
真实 outcome/no-body source 以及 private C2B 不逃逸。所有结论针对声明图。
仍需来源/运行证据：实际 receiver/callable/version；R 当前确实关联 B；guard 原子性/
无 callback 正常语义；动态 create/activation/generation 与静态 target 对应；session
字段真实实现、正常/异常 post 完整表及并发排他。不能从新 state、类型、同 LocationID、
静态 site、U/A 阶段或 use 次数授这些证明。真实目标派发若尚未绑定，明确该关联待证，
不能把旧暂停点 mismatch 随意变成 Python 外部错误来宣称 source 等价。

## 8. 冻结建议与依据

建议采用窄 pair 方案进入 root 统一合同；不再实施旧跨 CFG permit 字段。scope 不要求
完整 Python 前端，不新增 backend/detector，也不以此关闭整体 C2D/第一阶段。

主要源码依据：`model.py:427`–474 的真实 successor/completion；`:598`–608 的
INVOKE 约束；`validation.py:219`–280 的独立 owned Use 与 actual/formal；`:474`–497
的 completion 当前域规则；`resumption_flow.py:17`–60 的首 outcome 派生。三组语言
观测仅复用冻结 `model_driver_interfaces/review/claim-lifecycle-review.md:14`–22，未新增
实测或扩张语言证明范围。当前主规格相关限制见 `docs/M1_DRIVER_INTERFACES.md:35`–73、
`:100`–126、`:148`–163。
