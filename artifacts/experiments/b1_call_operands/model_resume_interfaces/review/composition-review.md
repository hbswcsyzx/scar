# C2 挂起/恢复：canonical IR 组合审查

2026-10-17，基线 `0ea05e6b57a03a6d717c5be5008d0541aa3f4975`。
**Proposed，只读设计；没有 C2 实现/测试/采集结果。** 依据 whole-model §3/5.3、
控制协议 §7，以及当前 model/validation/queries/environment/control/cleanup/frame。
本轮只写此 artifact，不修改产品、测试、共享文档，不运行 full/LeWM/GPU。

## 1. 判断：C2 是持续 activation 的边界，不是额外 Yield 标签

必须分开：代码定义、一次可恢复对象生命周期、其持续 body activation、某次驱动
请求/host 调用、某次 suspension generation。OperationID/RegionID/ControlScopeID
都不是动态实例键；同一 site 循环执行多次、同一函数创建两个对象均需区分。
对象 handle 可被合法 alias，不能用“引用 ValueID 仅一个 consumer”证明一次恢复。

规范顺序应为：

```text
call preparation/binding → Create(bound refs + environment) → handle, current state
handle + request + CURRENT shared state → acquire/validate instance lifecycle
    → initial body entry OR restore saved private frame → execute body
    → Suspend(payload, frame, next generation, post-state)
    | CompleteReturn(evaluated reference, post-state)
    | CompleteRaise(packet, post-state)
body outcome → versioned boundary adapter → this driver's Host Returned/Threw
```

创建时正常返回对象不执行 generator body，也不是 body 的 Return/FrameExit。
恢复时不重新绑定原 Python actuals、执行 defaults 或重新创建函数环境。
Yield 的 exported reference、send expression result、最终 Return、await scheduler
payload、await 最终结果必须是不同 canonical 端点，不能共用一个 payload 字段。

## 2. 当前代码有五处硬约束，不能靠旁注跨过

| 现代码 | C2 必须处理的缺口 |
| --- | --- |
| model.ExitKind/INVOKE 只允许 NORMAL/RAISE，固定两个 private completion 目标 | body 的 Suspend 是第三类语言 outcome；普通 host INVOKE 仍可二分，但须有显式 body-outcome/driver adapter，不能让普通 RETURN 代替 Suspend。 |
| validation 的单入口、entry 无前驱、全 block 可达与普通 CFG dominance | resume 不是一条无声明的“跨时间 jump”；所有恢复入口/实际端点必须参与 canonical CFG/接口校验。不能另存一张 resume CFG 后继续用旧 dominators。 |
| FunctionEntryLayout 完整分区 non-state/non-env entry 为 Reference Python formals | request/frame/handle 是协议入口，不是 Python 新形参。应有明确 resumable-entry profile；不能把 protocol 端口塞入既有 formal tuple。 |
| C1 entry 栈固定空、SAVED_HANDLED_CONTEXT 不得跨入口/出口，copy 只认逐边 forwarding | yield-in-finally 要合法封装/恢复 active frame；只加新 protocol enum 会直接违反这些约束。 |
| FrameModel 是一 Region 一 Enter，FrameExit 绑定完成；ExitPort 还不接 LocalBindingType | 持续 frame 不能每次 host 返回都销毁；局部 binding/unbound 保存须经 typed private frame，不把 LocalBindingValue 或 saved context 暴露为用户返回值。 |

推荐保留现同步能力的严格规则，通过新 capability 引入 typed 边界；旧 wire/普通
INVOKE/FunctionEntryLayout 不静默放宽。query 当前只索引 Return/Raise site，C2 须
扩实际 outcome 查询，不能把 Suspend 算作完成或把未声明 continuation 当空 frame。

## 3. 两种组织方案与取舍（收到 root 的 temporal-edge 提案后复审）

**root 已选择 A 为待实施规范：单 entry 逻辑 body + typed temporal successors。** SuspendTerminator
分别绑定本次 host handoff/outcome 和未来 resume successor；后者是显式“跨驱动”
边，绝不是同步 JUMP。private Uses 直接绑定 resume 参数，ResumeInput 提供本次
request/current-state/边界上下文结果。每个恢复点使用专用 landing；所有 shared
StateVersion 参数都由 ResumeInput 新提供，不能由保存旧 state 的 Use 充数。
CFG/forward/fresh 使用这些唯一规范连接，
不再建立外置 resume 图或在恢复时重建一套 cleanup 锚。

A 比 dispatcher/segment 更少改变 C1 的逐边锚保持：逻辑 cleanup 栈沿 temporal
边保留，前一 Enter 仍在逻辑路径上；fresh-before-yield 不因新 drive 而失效。
但普通 dominance 不再等于跨时间可用性，必须实现下述 cut-availability。物理调用/
测量投影不得把 temporal successor 当成 body 立即继续，漏掉 caller/scheduler 执行。

**B：后续 segment lowering/执行投影，不作为第二套规范图。** 初次/恢复分支从 dispatcher 进入
startup/restore landing，也可以保持单 entry；但原 Enter 不支配 resume 路径，需
额外已认证的 stack/anchor restore 初始化和 freshness 延续。再切独立 segment
Region 还增加跨 Region scope/environment 映射。若以后采用此执行投影，须由 A
派生并维持对应关系；不能成为独立 actuals/状态来源。未实现 resume 桥时尤其
容易把恢复误作新 Enter。

选择 A 的前提：typed temporal 边纳入 core 的参数类型/来源、所有 predecessor、
状态输入与逻辑栈分析；明确 initial-entry/驱动适配及每个 ResumeInput 的生产合同。
若只加 successor、借普通 dominance 偷用未保存值，A 不能通过。两方案均需动态
instance/generation 对应，不要求重写 compiler/native graph/pytree。

## 4. 最少必需的接口信息：只引用现有 producer/Use/端口

下表为所需关系，不要求每行扩成一组新 class；具体记录名/ID 待冻结。

| 关系 | 最少字段与 canonical 连接 |
| --- | --- |
| resumable 定义/创建 | creation OperationID、body RegionID/code definition、协议版本/家族、已绑定参数/环境的既有 UseID 路线、handle ReferenceValue result、lifecycle/frame 所在规范 location。创建→body 是 deferred definition 关系，不是假 callee 执行。 |
| private-frame layout | owner body、site（既有 suspension OperationID 足以定位）、有序 slot（binding/temp/evaluation-stack/protocol 各有角色）及真实 resume 目标参数位置；类型从既有 Value 推导，不重复 type/actual 表。保留 unbound binding token。 |
| capture/restore | A 直接用 Suspend 的 owned private UseID→temporal successor 参数作为 save/restore 接线；layout 只索引这些真实位置，不能另存一份 actuals。需要独立 frame-pack 时也只能引用 canonical producer/Use。恢复必须产生新的参数 ValueID，不给旧 ID 第二 producer。 |
| continuation handle | 指向 body/site/layout 的规范载荷、实例引用与 generation 的实际来源，以及 lifecycle acquire/update StateAccess。静态声明能约束来源，实际 ObjectID/lifetime/run 属证据桥接；不得将 site 字符串当动态键。 |
| request | request 构造 Operation/value、协议 variant、既有 payload Uses：Next 无载荷、Send 引用、Throw packet、Close 的具体注入/关闭规则；scheduler/async 请求亦有明确 adapter。缺参、None 引用、异常 packet 不互换。 |
| Suspend/drive | typed Suspend 分开 exported payload/current post-state handoff 与 private temporal arguments；ResumeInput 是有 signature/slot 的本次恢复输入，不能当任意“新 world”。driver handle/request/current-state actuals 及 body outcome→host completion 路线均明确；普通 INVOKE 保留二分。 |
| boundary adapter | 原 body outcome port、该 driver 的 host completion port、具体协议规则/条件与 payload 转换、state/exception 路线。yield→next Returned、body Return→exhaustion、body Raise→Threw/PEP转换分别描述。 |

source-call/create Region 保持既有 EnvironmentInterface 与 FunctionEntryLayout。
A 的原 body entry 可保留原始 formals/environment/state 入口，首次驱动的适配协议
绑定创建时已保存的引用和当时 CURRENT state；后续请求只走 temporal 参数，不
重新走 Python formal entry。若增加 driver Region，其协议入口另分区。globals/
cell/对象内容每次消费恢复时 CURRENT state，不能直接跨 Region 偷用旧 ValueID。

**A 的新增硬门：cut-availability。** temporal 边后只允许已保存 actual Use 对应
的新参数、ResumeInput 新参数及 literal；普通 dominance 不能让其他旧 nonliteral
Value（包括 LocalBindingValue、entry environment/reference）跨界直接使用。用同一
typed CFG 推导 must-available：普通边保留已可用定义，temporal 边切断继承并重新
以其参数/本次 produced inputs 建立可用集，汇合取所有前驱约束；block 内逐操作
加入新结果。根化固定点不得让无种子循环自证可用。非挂起路径与恢复路径合流时
也必须显式 phi，不能因为旧 producer 在原图支配合流就跳过捕获。

ResumeInput 至少定位所属 resume signature/typed slot/目标参数，区分送入引用、
注入 packet、逐 location 当前状态和本次 driver-context-return token。其生产合同
连接“本次驱动的 current state 经 context-install 后态”，不能只是一个可任意
填写的 Data/Protocol 枚举。静态可验端口/条件结构，实际 driver occurrence↔实例/
generation↔这些输入的对应另需运行证据，不凭参数名字宣称已验证。

**创建/Start/恢复的接线必须单独冻结。** Create 的输入与后态属于创建这个 host
调用，不能把它的 world 保存为稍后首次执行 body 的 StateVersion。Start adapter
从实际首次驱动 current-state 捕获 caller context、安装 initial body context，再
将 post-install state 传到原 body entry；绑定的引用/环境来自 creation 的 canonical
保存路线。resume landing 的 request/frame/context 是协议端口，不扩充 Python
FunctionEntryLayout.parameters。若 body 原 entry 保持原函数 entry 形状，Start 必须
明确如何填满该 entry 的 env/formal/state 分区，而不是假造一次新的 Python 调用。

**body 与 host outcome 是两层接口。** body Suspend 经 yield/await 适配可成为本次
host NORMAL（exported reference）；body Return 经 exhaustion/完成规则可成为 NORMAL
或 RAISE；body Raise 经传播/PEP 转换成为相应 host completion。映射按协议声明，
不能按同名 NORMAL/RETURN 直接等同。驱动前拒绝请求的 RAISE 只有 host 路线，不得
有 body temporal edge、Consume/ResumeInput 或虚构 body state。cancel-requested、
adapter 接受取消和确实向暂停位置注入异常是三个不同事实；前者不产生 body Raise。

## 5. private frame 与当前 shared state 的分界

- 捕获局部 binding token、活引用、未完成求值栈及内部协议状态；恢复对象引用不
  回滚对象内容。即使 local 名字未变，Tensor/容器/cell 的内容仍可由 caller 修改。
- shared StateVersionValue 不进入私有 snapshot；所有域在 suspension 向 host 传
  post-state，后续 drive 从实际 caller 当前 state 重新输入。若需保存真正私有状态，
  必须先建立 owner/escape/覆盖合同；不能从 location.label 或 INTERNAL 标记猜私有。
- lifecycle/frame-location 的读写仍用 StateAccess 和每个 outcome 的后态；挂起、释放
  引用、异常、取消、finalizer 的部分效果不能恢复为旧 world。未知作用域用 coarse
  fallback；未知 effects 并不允许省略非 context 域后态。
- close/resume 请求需按实例当前状态原子 acquire/拒绝 reentry，再驱动当前 generation。
  SSA 当前状态接线可以校验结构，但不能单凭静态 use 数证明并发排他或 stale handle
  从未重用；这些是 intrinsic 适用条件/运行 guard 与证据，不新增 writable verified。

## 6. yield-in-finally：C1 相容的必要扩展

1. Suspend 不调用 CleanupResume/Replace、不 pop active cleanup，也不执行 FrameExit。
   snapshot 包含从真实 C1 transfer 推导的 stack、每层原 pending/context 锚及当前
   handler/frame 上下文。manifest 必须与 site 的推导结果一致，不能信任自报 scope 集合。
2. restore 是该逻辑 activation 的继续，不重新运行原 Enter。A 的 canonical resume
   参数经 temporal actual Use 对应保持 anchor；不能让旧 ValueID 有两份 producer。
   C1 私有 context 的逃逸只增加精确 capture/restore 例外，不一般性允许 call/exit 外传。
3. A 将 temporal forwarding 纳入同一 copy/fresh 固定点，栈沿逻辑边保持；同时由
   cut-availability 禁止缺失捕获。B 则要额外认证 frame restore/初始栈，不能直接
   放行旧 C1 的私有边界限制。无 C2 能力的同步图仍按 C1 原规则验证。
4. freshness 相对 CleanupEnter 的持续 activation，而非最近一次 drive：C Enter后、
   yield前构造的 replacement 在恢复后仍可能 fresh。反之旧 visit/另实例的相同
   static constructor 不 fresh；不能在每次 restore 无条件重置为新锚或新来源。
5. 至少区分三种 context 接口：每层 C1 SAVED_HANDLED_CONTEXT、挂起 body 的
   context 模式/owned context/相对链接、**本次 drive** 的 caller-context-return token。
   body 必须区分 INHERIT（本次 caller ambient）与其自己持有的 handled context；
   不能把上次继承的 exception 值永久保存成 body owned context。前两者属于持续
   frame，可经 private temporal slots 保持其协议含义；第三者必须来自本次
   boundary capture/ResumeInput，不能保存为下次仍有效的 caller token。Suspend/
   最终完成先保存/移出 body context、归还本次 caller context；下次驱动重新保存
   caller ambient 并安装 body context。安装/归还操作各用当前 StateAccess 后态，
   与 ResumeInput 的 post-install state 绑定，绝不能是旧共享 world 快照。相对
   caller 的链接/ambient fallback 规则仍需版本化见证，不能由新 protocol tag 证明。
   本目录 language-exception-context-probe.json 的 CPython 3.14.7 实测已支持这一
   区分：无 owned handler 时每 drive 继承当次 caller；自己的 KeyError handler 跨
   yield 保持同一异常；handler 结束后恢复继承；pending Return 的 finally 也可能
   看见 caller exception。此为该探针范围的语言证据，不是 C2 接线已经实现的证据。
6. Throw/Close 在暂停位置产生新的控制转移，可先被 frame 内 handler 捕获；只有真正
   离开对应 cleanup 才 Replace。handler 保存/恢复接口尚未完整，不能靠保存一个
   EXCEPTION_PACKET 就声称 handler stack/异常属性全部恢复。

## 7. 协议覆盖不能缩成只有 yield 数值

控制分册 §7 的版本合同均应进入 adapter 分母：

- Created/Running/Suspended/Closed 各请求不同。首次非 None send/reentry 校验失败
  不伪造 body entry；未启动 close 不执行 body finally；Closed 不重放旧 Return payload。
- Throw/Close 不是 Send 的别名；Close 后仍 yield 可失败并保留 Suspended，不能所有
  异常出口都标 Closed。完成/关闭时的引用释放仍有未知效果和可能不完成。
- 正常 generator Return、body 主动抛出的 StopIteration 与 adapter 自造 exhaustion
  不同；同步/异步生成器、coroutine 的完成协议不互换，3.13+ close 返回规则亦需版本。
- async generator 的 anext/asend/athrow/aclose 先创建 request awaitable，await/drive
  才推进 body；这个请求对象也有自己的生命周期，不等同 generator instance。
- await 可零次 Suspend；中间 scheduler payload 不是 await 最终结果，取消可被捕获。
  yield-from/await 的 delegate、父 continuation、send/throw/close 调用与 StopIteration
  解包都接实际边界；嵌套 continuation 可复用同一机制，不按词法树猜动态调用。
- scheduler/CPU suspend 不证明 GPU/文件 Ready 或资源已经取消/关闭。

这些是需要落实的规范要求，非本轮运行观察；不能只列名字就验收已覆盖。

## 8. 最小实施 gates 与实质通用 fixtures

| Gate | 本门关闭内容 | 必需正反例 |
| --- | --- | --- |
| C2.0 合同冻结 | 入口/outcome、instance/generation、frame/current-state、request/adapter 分区；比较两方案后冻结一条 canonical 接线 | 创建正常返回 handle 而未进入 body；首次失败请求无 body；creation 环境非恢复新形参。 |
| C2.1 类型/wire | exact typed endpoint/layout、现有 Uses/results/ports 连接、新 capability；旧 schema 不夹带请求/frame/Suspend；复用显式 record_tags | 同形 record 不靠 union 顺序猜；错 owner/site/layout、缺槽/重复槽/错类型拒绝。 |
| C2.2 私有 frame/状态 | SavedUse→temporal formal 槽位、专用 landing、cut-availability 与其 roots、每域 ResumeInput CURRENT shared-state、lifecycle acquire 的条件结构 | yield 后 caller 修改 global/cell/NumPy alias；恢复引用相同但内容读新状态；旧 state/跨实例或旧 generation、未保存旧局部直接跨 cut 均拒绝。 |
| C2.3 持续 C1 activation | active stack/handler/private context、pending/context/freshness 跨 suspension；全 CFG/outcome 部分后态 | pending Return 在 finally 中 yield 后仍 Resume；Throw/Close 可 Replace；fresh-before-yield仍 fresh；错栈/重Enter/恢复上次 caller context 拒绝。 |
| C2.4 完成与委托 | Next/Send/Throw/Close 各状态、yield-from、await及async-generator 双层请求/驱动与异常 adapter | send 表达式引用、throw 被捕后再yield、close 非法yield保持后态、closed不重放、PEP转换、await零次/多次挂起、delegate失败。 |
| C2.5 公开验收 | query/codec/CLI、独立反例、冻结 fixture/hash 与单次全仓；所有 source/runtime/排他/transform 权限仍未证明 | 手工图不计自动 source 恢复；同一静态 site 多 visit 与两个对象实例不能混锚；非 total 路径不虚造完成。 |

能静态检查：记录/端口类型、精确槽位、每个 outcome 的 state 流、显式 layout 守恒、
声明的状态机/栈规则、跨边界锚保持的条件结构。不能据此证明真实运行实例、内存内容
未被外部写、实际 Python context、任意反射/handler/库调用已完整展开、并发原子性、
资源 ready 或 totality。C2 总门必须等待上述家族和组合关闭；早期子门可独立交付，
但不能把一个 generator-yield fixture 当整个挂起/恢复模型完成。

## 9. 仍待冻结的字段清单（不是实现状态）

1. creation→body/Start 的定义关系、bound reference/environment 的唯一实际路线、
   instance lifecycle location 与 body 协议 family/version；不复制原 call actuals。
2. Suspend 的 host outcome 与 temporal successors 两组端点；每个 successor 的
   request variant/条件、专用 landing、逐位置 SavedUse 或 typed ResumeInput 来源。
3. ResumeInput 所属 drive/site/slot、current-state location、post-context-install
   合同和 context-return token 的归还端点；不能用字面“fresh”自授当前状态。
4. 私有 frame layout 的精确 Value/Use→formal 位置、unbound/localbinding 与协议
   payload 类型；共享 state 不在捕获分区；cut roots 与全部 CFG edge 的投影规则。
5. 持续 body activation/instance/generation 的声明关系，C1 stack/anchor/freshness
   沿 temporal edge 的转移，以及 INHERIT/owned context 的保存/安装/归还关系。
6. 每类 request 的合法/拒绝/body 注入分支及其部分后态、每个 body outcome→host
   completion 的 payload/exception/state 映射；取消请求与注入分别连接。

这些字段及构造/图级验收还没有 C2 产品实现，本报告不授予 source/runtime/transform
能力，也不将设计选择计为 C2 gate 已通过。后续只按 A 落一套 canonical 连接。
