# C2D：driver 连接合同第二稿

2026-10-18；审查基线 `499d708`。**D1设计已收敛；其后实施见[组件验收](M1_DRIVER_ACCEPTANCE.md)。**
本文收敛 [先前复审](M1_DRIVER_INTERFACES.md) 的具体连接方式，不更改五类核心实体，
不增加 detector/backend，不宣布完整 C2 或第一阶段完成。

## 1. 选择及其理由

采用一个逻辑 body，加上真实 driver CFG。最终 admission 使用现有 `INVOKE`；
其 NORMAL 私有 landing **只有一个操作，即配对 BodyDrive terminator**。
RAISE 是 admission 自身失败，不是 body Raise。更早的 normalize、delegate、
request 更新和用户回调保留为普通操作，并向 admission 提供最新状态。

```text
raw request / receiver / current state
  → 真实 lookup、normalize、delegate、request helpers
      ├→ no-body 路线：真实状态/host adapter
      └→ final admission INVOKE
             ├ RAISE → 拒绝/失败的当前后态 → host adapter
             └ NORMAL → post-admission state + 原引用的显式转发
                            → BodyDrive（landing 唯一操作）
                               → 本次首 Suspend / Return / Raise
                                  → commit → 实际 release/session/host adapter
```

**不引入可传递的 permit Value。** gate→drive 的资格由唯一控制边和精确端口关系表示，
不是能保存在 frame、对象、循环或下一次请求中的数据。也不把 admission 隐藏在一个
没有中间 producer 的调用里：RUNNING 等更新的后态由真实 NORMAL CompletionResult
和 landing BlockArgument 定义，随后 body 才消费它。

这仍是可递归展开的操作/区域模型。native opaque 调用与展开 CFG 是同一次调用的
不同表示，不是额外再执行一次 gate、release 或状态更新。

## 2. 规范事实归属

| 事实 | 唯一规范记录 | 本合同附加的关系 |
| --- | --- | --- |
| 操作的实际输入/结果 | Operation.uses/results、invoke_arguments、BlockArgument | 只引用 UseID/ValueID，不存另一份实际值。 |
| 当前可变内容 | StateVersion、StateAccess、completion 后态 | lifecycle 域也使用这些记录；LocationID 不等于 owner。 |
| 私有保存/恢复 | 原 Suspend.saved、ResumeSuccessor、SavedInput/ResumeInput | Drive 不再复制 saved frame、pending 或 local 列表。 |
| 函数形参/环境 | FunctionEntryLayout、EnvironmentInterface | Create 连接已绑定的 Reference，不猜默认参数或 globals。 |
| 本次 body 出口 | 现 `body_outcomes(body,start)` | driver 边引用确切源 OperationID，签名只从该源派生。 |
| 实现适用条件 | 版本化 rule、source/provider 与后续运行证据 | 没有可写 verified/authorized 位；同方法名不授合同。 |

OperationID 是静态 site，Reference ValueID 是静态引用端口。一次动态创建、实际对象、
持续 body activation、suspension generation 与本次 driver invocation 保持不同身份。

## 3. 拟实施的字段

本节是 D1 wire/validator 的设计合同，**不是当前 Python API**。第4节的 D2 候选字段
另行审查，不因本节通过而冻结。字段名可在实施时作机械
调整，但事实的来源、顺序、唯一性和拒绝条件不能变更。`int` 均为非负 exact int；
所有 tuple/enum/ID 使用 exact 类型，拒绝 bool 索引及任意 label 分派。

```text
DriverRuleProfile = PYTHON_RESUMPTION_V1
DriverRule(profile: DriverRuleProfile, implementation: ProviderFactReference)
NormalResultPort(index: int)
RawRequestKind = NEXT | SEND | THROW | CLOSE
RawRequestDefinition(value: ValueID, kind: RawRequestKind,
                     operands: tuple[UseID, ...])

CreationCapture(formal: ValueID, source: UseID)
ResumableCreate(operation: OperationID, body: RegionID,
                function_object: UseID, captures: tuple[CreationCapture, ...],
                handle_result: NormalResultPort, rule: DriverRule)
AsyncRequestCreate(operation: OperationID, body: UseID, latent: UseID,
                   request_result: NormalResultPort, rule: DriverRule)
RequestAssociationRead(operation: OperationID, request: UseID,
                       body_result: NormalResultPort,
                       latent_result: NormalResultPort, rule: DriverRule)

DriverInterface(region: RegionID, body: RegionID,
                receiver_kind: BODY | ASYNC_REQUEST,
                receiver: ValueID, scheduler_request: ValueID,
                lifecycle: tuple[LocationID, ...], rule: DriverRule)

BodyStart(body: RegionID)
BodyResume(suspend: OperationID, successor: int)
BodyStateInput(location: LocationID, source: UseID)
BodyResumeInput(slot: int, source: UseID)
FinalBodyGate(operation: OperationID, drive: OperationID,
              body_argument: int, scheduler_argument: int,
              session_argument: int | None, delivery_arguments: tuple[int, ...])
BodyDrive(operation: OperationID, instance: UseID, scheduler_request: UseID,
          session: UseID | None, target: BodyStart | BodyResume,
          state_inputs: tuple[BodyStateInput, ...],
          resume_inputs: tuple[BodyResumeInput, ...])
BodyDriveResult(index: int)
BodyDriveSuccessor(source: OperationID, block: BlockID,
                   arguments: tuple[UseID | BodyDriveResult, ...])
BodyDriveTerminator(successors: tuple[BodyDriveSuccessor, ...])
```

`NormalResultPort(index)` 只定位 owning record 的 INVOKE NORMAL signature 槽，并从
真实 NORMAL edge 找到其唯一 landing formal。不是另造 Value 或 claim 某个 dominating
Reference 是结果。DriverRule profile 是已知的封闭合同键；implementation 指向有哈希/
版本的 provider artifact，不执行任意字符串规则，也不证明实际 callable 对应。其
NO_FRAME_INTERPOSITION 等适用条件仍未证明。首版 Create/association 使用 INVOKE，保留 allocation/lookup 的
RAISE/部分后态；不同时增加无异常普通操作版本。RawRequest pack 则从所定义
ProtocolValue 的 OperationResult 反查 producer，接口 pack 本身不代表另一个物理分配。

### 3.1 Create、raw request、association

- raw 使用新增的 `RAW_DRIVER_REQUEST` ProtocolValue 类型；NEXT/CLOSE 为零个原参数，
  SEND 为一个，THROW 为一至三个有序 Reference Uses。omitted 不等于显式 None。
  async family 和 request 对象角色由 interface/Create 表达，不再造 ASEND 等重复 kind。
  raw→exception packet 是独立真实工作；delegate 可以直接使用 raw 参数。
- captures 精确覆盖 body entry 的非 state Reference 分区，包括全部形参及环境成员。
  来源是 Create 的真实 owned Reference Uses；形参 occurrence 各有 Use，允许同一
  Python 引用出现在多个位置。`function_object` 引用环境 FUNCTION_OBJECT 的同一
  capture source，不额外算一次 operand。所有这些 sources 是 owning Create 的真实
  invoke_arguments；不扩大控制输入的漏记例外。参数绑定/default/pack/cell lookup 必须先有 producer。
- 此处 Create 是**已完成参数绑定后的抽象 frame-create primitive**，不是源 Python CALL。
  原 CALL 的显式参数、展开、默认值读取、环境读取/绑定错误分别保留真实操作及顺序；
  它们产生的已绑定引用才作为 Create primitive 输入。合成 INVOKE 不表示新增一次
  Python 调用或一次物理 dispatch，源 CALL 与该分解的对应以后单独验证。
- 一个 `ResumableCreate` 的 NORMAL handle 关联自己的 capture recipe，创建不执行 body，
  也不保存当时共享 world。`AsyncRequestCreate` 创建 request 引用及 latent raw 请求，
  同样不运行 body。request 当前 scheduler 输入与 latent 输入始终是两个端口。
- association 读当前 request 与当前状态，NORMAL 返回 body 引用和 latent 请求。
  已知 Create 时检查声明一致；未知内部来源仍保留完整 typed 边界，不用方法名、同 code
  或同 LocationID 推出当前 owner。真实对象关联与后续写入由 guard/来源证据另证。

### 3.2 gate→drive 的逐端口规则

每个 driver Region 恰有一个 DriverInterface；receiver/scheduler 是真实 entry 参数，
lifecycle 是非空去重的已有状态域集合。body 必须是声明的 ResumableBody。rule 的
实现/版本条件只有一处；操作从 owning interface 取它，不重复保存 before/after world。
receiver 为 Reference，scheduler 为 RAW_DRIVER_REQUEST；合成 driver 区域不是另一个
Python 函数，不给它伪造 FunctionEntryLayout 或一次额外物理调用。
令 D 为 core 从该 Region entry 的 StateVersion 参数派生的全部状态域，L 为 lifecycle，
必须检查 `∅≠L⊆D`。下文 gate 的“全部域”始终是 D，不是仅 L；body 所需域为 D 的
子集。driver 可有非 lifecycle 域，不强制 `L=D`，也不重复维护另一份 D 表。

1. FinalBodyGate.operation 是同 Region 的 INVOKE，drive 是其唯一配对 BodyDrive。
   NORMAL landing 有且仅有这条真实 incoming，operations 恰为 `(drive,)`。
   每个 Drive 恰被一个 gate 配对；不能普通 CALL/INVOKE 直接 callee=body。
2. gate 各 argument 索引只指自己的 `invoke_arguments`。BodyDrive 角色和输入均是
   自己的 owned Uses；不借用另一个操作的 UseID。不存在一般 permit actual。
   scheduler 必须从 interface.scheduler_request 沿每条真实 incoming must-copy；
   BODY 模式 body 参数必须 copy interface.receiver 且 session=None；ASYNC_REQUEST
   模式 session 必须非 None 并 copy interface.receiver。不能把 latent raw 请求替换 S。
   copy 只沿真实 edge Use→formal，其他producer不算；全部 incoming 参与、拒无种子环。
   body/scheduler/非空session/每个delivery 的 gate 角色索引互异；对应 NORMAL 转发槽
   及 Drive 实际端口各有独立 UseID。允许这些不同 occurrence 的 Value 有意相同。
3. 对 owner、scheduler、session 和每个 delivered input，沿真实 NORMAL edge 逐槽核对：
   gate 实际输入 Use → **另一个独立 edge Use**（同 Value）→ landing formal → Drive Use。
   这些原引用/协议值不能用 CompletionResult 重新生产；不能只比较 origin 集合。
   这里禁止的是把新结果冒充同一已输入角色；真实 AssociationRead 产生 body 引用
   属于此前的真实 producer，不受此禁令误伤。delivery_arguments 与非STATE resume
   inputs 按目标 slot 顺序一一对应；Start 的两个 delivered 列表均为空。
4. gate 消费本点当前所有 driver state 域，NORMAL/RAISE 都产生每域的实际后态。
   第一版统一使用 CompletionResult，不用旧 state 转发冒充准入后态；这是保守的
   状态接口，不表示 Tensor 内容改变或发生物理复制。
5. gate 的成功语义是无用户回调的最终检查/标记，然后直接进入 body。body 和 request
   的当前关联、当前 request phase/session、选中 continuation 与 payload 在此核验。
   它不是“某次早先请求已获准”的历史 token。normalization、lookup、delegate、release
   及 callback 都在 corridor 外；再次进 body 必经过新的动态 gate 发生。
6. 拒绝路径的错误构造及其回调/失败保持真实后态；该 gate 的 RAISE **不表示本配对
   Drive 已执行**，也不禁止错误构造中另一个嵌套 driver 发生。

实现可以先有独立 request admission，也可以合并当前资格检查。通用 core 不强制一个
名为 RequestGate 的额外操作或父 permit。若版本协议确有更早的 acquire/store/失败，
它们必须作为真实普通 helper/state 出现在 CFG，不能从 final gate 反推其已发生。
具体协议的 phase/order 义务留在版本规则和 M2 source 对应，不把某一种实现形状
当作所有 Python driver 的类型。final gate 的当前检查始终保留。静态 body/continuation
目标与实际对象不匹配，是该图/规则适用性未成立；不能把它擅自变成一个新的 Python
异常分支来声称与原程序等价。真实动态目标选择要保留实际 dispatch/来源对应。

### 3.3 body 输入及其来源

- Start 按 `BodyStart(body)` 选代码接口，不绑定一个静态 Create site。state_inputs 按
  LocationID 精确覆盖 body 所需域，取 gate NORMAL 当前参数，不能按列表位置 zip。
  body entry 的 Reference 绑定是 **当前 instance frame 的 capture 接口投影**：已知
  Create 时连接它的 CreationCapture；外部实例/多 Create 合流也可声明同一接口。
  不猜唯一 producer 或动态 occurrence，不复制 capture 列表到每个 Drive。
- Resume 指向该 body 的确切 Suspend 和 successor；新 delivered 槽由 resume_inputs
  精确覆盖全部非 STATE ResumeSlot，类型按现 resume_slot_type；state 按 LocationID。
  SavedInput 继续从那个 Suspend.saved→landing 参数派生，不由 driver 重新打包。
- frame context、pending/local/binding、saved reference 与本次 current shared state
  不混用。外部 frame interposition 的适用条件仍单独列明，声明 recipe 不证明运行时
  frame 未被反射修改，更不因对象引用相同证明其 Tensor 内容不变。
- 此投影的规范 producer 仍是原 body BlockArgument。Create/Suspend/instance 的连边
  是跨区域来源 recipe，不另造同名 Value。尚无 occurrence 对应时只报告声明来源，
  不把候选 Create 集合当作实际实例证据。

### 3.4 body outcome 与 driver 后态

由 target 确定 entry/真实 landing，复用已验收的 first frontier。每个 Successor.source
恰为该 frontier 一个源 operation，必须完整且不重复；各 outcome landing 彼此不同，
有且仅有对应的这条真实 incoming，不能先合流再猜源。签名当场从源 Uses 派生：
Suspend 只含 exported+handoff，Return/Raise 只含真实 terminal values。saved 不公开。
BodyDriveResult(index) 只投影 **本条 source 边** 的结果，不另存第二份签名或结果图。

BodyDrive 不定义普通 results/accesses/callee/call_arguments/completions/invoke_arguments；
唯一 body actual 及角色在其 typed 字段引用 owned Uses。driver 的其余状态域逐条用独立
edge Use 转发；body 返回的 state 从该 source 的真实结果按 LocationID 对应。
body 声明之外的域不受影响只是接口的 effect-scope 声明，仍需来源证明，不能因此优化。

空 frontier 允许，含无限循环的路径不产生 completion。完整列出所有有限出口不证明
must-return，也不需要捏造“发散结果”。body CFG 本身保留循环；不跨下一次 Suspend。
同一源能被多个不同 Drive 引用，但每次 driver outcome 用 `(drive, source)` 区分。

## 4. 完成、session 与真实引用放弃

**D2候选，未冻结。**本节给出下一步必须满足的关系，不能按下列草图直接发布字段。
尚需落实 typed no-body helper 的成功合同、逐边完成锚、窄 FrameRules 与真 raise wrapper
的区别、phase/current-owner 转发及重复终态引用放弃的语义。D1先提供真实源边与端口。

postcondition 必须来自实际私有 outcome corridor 或 typed no-body 成功边；host Return/
Raise、normal helper、请求对象完成都不能替代 body 终结。操作的后态继续由实际
StateAccess 或 INVOKE completion 产生，不由下列元数据额外创造。

```text
DriveOutcomeRef(drive: OperationID, source: OperationID)
ControlEdgeReference(operation: OperationID, successor_index: int)
NormalEdgeRef(operation: OperationID)
BodyOutcomeCommit(operation: OperationID, outcome: DriveOutcomeRef,
                  instance: UseID, session: UseID | None)
NoBodyFinish(operation: OperationID, instance: UseID,
             witness: NormalEdgeRef, rule: NoBodyFinishRule)
SessionUpdate(operation: OperationID, request: UseID, body: UseID,
              source: DriveOutcomeRef | ControlEdgeReference,
              post: HOLD | COMPLETE | ABANDON)
TerminalFrameRelease(operation: OperationID, owner: UseID,
                     completion: BodyOutcomeCommitRef | NoBodyFinishRef)
```

BodyOutcomeCommit 是对应私有 outcome landing 的首操作，无 callback，仅发布那次
结果要求的 lifecycle/continuation 后态。各域由 DriverInterface 派生。NoBodyFinish
只承认有明确版本规则的成功 guarded 路径，如 Created-close；不能伪造 body Return。
ControlEdgeReference 指某操作的实际 successor（含 NORMAL/RAISE）；NormalEdgeRef
仅定位 INVOKE 的真实 NORMAL 边，不复制目标或结果。Commit/Finish 的引用定位对应
canonical metadata operation；NoBodyFinishRule 的封闭语义与 witness 条件仍待 D2。
session helper 若确会向外 raise，使用真实 INVOKE；NORMAL 才给出规定的 post，RAISE
保留真实部分后态。失败边也能触发 request 清理，不能只允许成功来源。

窄的 frame reference-drop 若采用既有 FrameRules，普通 finalizer 异常走 unraisable，
条件适用且完成时保留 pending，不因为可能 callback 就捏造可传播 RAISE。外层若含
真正可 raise 的 lookup/close/分配/adapter，则拆开或整体保持普通 INVOKE；不能套窄
规则吞掉真实异常。TerminalFrameRelease 的规则字段与覆盖域在 D2 冻结前必须补全。

| 真实来源 | 续体的结构事实 | request/session、host 及 release |
| --- | --- | --- |
| YIELD/DELEGATION Suspend | 暂停，仍有续体；本次 step 结束 | 不能终结 frame；delegate-only 没进入父 body 时不造这个来源。 |
| AWAIT Suspend | 暂停，仍有续体 | asyncgen request 可保持 HOLD；不能因 host 返回就解占用。具体 family 用版本表。 |
| ASYNC_YIELD Suspend | 暂停，仍有续体 | item request 可以 COMPLETE；不因此关闭 body。 |
| body Return/Raise | 续体 FINISHED | Closed 提交先于可重入的 terminal frame-release；session 与 host adapter 分开。 |
| typed Created-close 成功 | 无 body 入口而终结 | 可接终态引用放弃；不需要 Attach/Detach 或假 body outcome。 |
| reject/closed reply/delegate-only | 没有本次父 body outcome | 真实 callbacks/当前状态保留；不从 host 结果推导 frame 终结。 |
| close 后 body 又 Suspend | 仍有续体 | host 可以 RuntimeError；不能据此改写成 body Raise/Finished。 |

native 标志如 asyncgen closed 不等于“续体已不存在”；其字段是普通 state，不能拿
一个位代替本表。终态 release 只承诺放弃/转移 owner 引用及当前 effects，不保证
对象 free、最终化完成或资源 ready。body 内 rebind/DEL 在 Attached/RUNNING 执行，
不套 terminal-release 规则。traceback/外部引用可以继续保活；后续放弃单独建模。
unraisable channel、显式 close/adapter 新异常和可能不返回均保留。payload/pending
需要跨 release 时用本地显式 edge Uses 保存，不把它们传给任意未知 helper。

## 5. 实施和自验收

1. **D0 共同复核：**核对字段归属、实例接口、gate 当前状态和 outcome/release 关系。
   架构决策通过不代表新代码、全 family 规则或完整 C2 通过。
2. **D1 规范连接：**新 records/RAW/typed BodyDrive、原 core CFG/state/Uses 校验；
   codec **schema v11** capability 全探测和v1–v10拒绝；公开查询仅返回规范端口。首先完成
   Create→Start→Suspend 及 Resume→Return/Raise 的整条声明图，不交孤立表。
3. **D2 lifecycle 组合：**按真实私有 source 边检查 commit，普通 helper 最新后态、
   request/session 的不同结束时点、created-close/release、C1/context 与反例。
4. **D3 family 对照：**复用控制协议分册的 generator/coroutine/asyncgen/request、
   delegation/await/close/cancellation 全分母；源/运行时对应另门验证。

必拒反例：缺 capture/环境输入；新结果冒充 owner；S 与 latent 反选；旧 world；
准入到 drive 间插操作；拒绝边冒充 body；跳过 gate 的回边；错误 resume 槽/源 body；
跨 Suspend 读取远期 outcome；交换 state location；Suspend 当 Finish；request 完成当
frame 可释放；release 后返回旧状态。合法多 Create、额外 driver 域、空/混合发散
frontier、nested callback 和 no-body 路径也必须纳入，不为方便校验删掉它们。

当前设计证据目录：`artifacts/experiments/b1_call_operands/model_driver_contract_v2/`。
旧 permit/session 方案保留为 Rejected 的历史，不改写其原报告。小 corridor 探针
只检查现 core 和拟议 shape：初稿 enum 拼写错误已保留，修正后六项设计检查通过；
其中 opaque 第二次 INVOKE 不是 BodyDrive 产品。没有重跑旧全仓或 LeWM/GPU。

## 6. 共同复核状态

**D1连接字段/实施范围已审查收敛，可进入产品实施。不是D1产品验收。**
core、gate和lifecycle的独立原意见、补充及逐项修正见本批证据目录。
root在终审明确 L⊆D：不采纳core报告将lifecycle等同全部driver域的建议；gate仍消费
并产生全部D，不能漏掉非lifecycle域。这保持额外driver域的合法表示，实施矩阵纳入
L≠D正例。仅这处字段域含义被澄清，原报告保持不改写。

D2失败边session清理、NoBodyFinish规则、窄FrameRules/真实raise wrapper与逐边相位
检查尚未冻结。在本字段冻结时产品源码为 `9f3d7e7`；其后D1实现状态按组件验收文档
更新，不改写原审查证据。完整 D0/C2D/第一阶段开放。
