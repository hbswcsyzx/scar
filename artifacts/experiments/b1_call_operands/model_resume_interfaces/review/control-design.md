# C2 resumption：独立静态控制设计审查

基线：`0ea05e6`；2026-10-17。只读源码、冻结文档与官方资料；没有运行测试、采集或实现。
本文字段是待冻结的候选合同，不是现有 API。审查期间 root 已决定 A 为规范逻辑 body；B 仅保留为未来 lowering 投影，不得成为独立 producer/静态 activation 模型。没有实现 C2。

## 1. 有界结论与当前差距

- 可复用五类实体及 canonical Operation.uses/results、CFG actual→formal、StateAccess、environment、C0 pending/packet 与 C1 cleanup。continuation 是协议 Value/接口，不需要第六类基础实体、第二份 producer 图或 scheduler execution 图。
- 最小 C2 必须同时声明：暂停位置、保留的私有值、每次恢复的当前状态/请求、上下文切换、body outcome 与 host adapter、实例状态协议。缺任一项都会接受错误图；动态 instance/generation 对应仍不能由静态声明证明。
- 选定的 A 保持单一 body Region/cleanup 归属，但要实改边语义、值可用性、当前 state 与协议校验。B 曾有保留段内 core 的优势，但跨段 C0/C1/逻辑激活合同更大；后续只能从 A 派生。
- 当前 core 能表达普通不透明 driver 调用及其保守 normal/raise 状态效果；不能据此证明调用进入了指定 body、保存了指定 frame 或消费了某代 continuation。
- 本轮只应冻结类型、组合与有限人工 IR 例；不把完整 Python lowerer、调度器、backend 或 detector 变成 C2 前提。第一阶段完成后按 `docs/FIRST_STAGE_COMPLETION_MATRIX.md:43–51` 停下说明边界。

依据：`docs/WHOLE_PROGRAM_MODEL.md:225–283` 已区分 Complete/Suspend、私有 frame/当前共享状态与动态代次；`docs/FIRST_STAGE_COMPLETION_MATRIX.md:26` 明确 resumption 核心尚缺。
现 `ExitKind` 只有 NORMAL/RAISE，terminator 没有 Suspend，Region 单入口（`scar/ir/program/model.py:391–418,645–671`）；新协议尚非已实现能力。

## 2. 最少独立事实来源：接口引用已有端口

| 候选记录/类型 | 必需字段和强关系 | 唯一事实归属 |
| --- | --- | --- |
| ResumableInterface | 独立 ID、body owner、GENERATOR/COROUTINE/ASYNC_GENERATOR、environment ID、版本化 adapter 规则 | body 与对象种类/协议归属；不是实际函数对象绑定证明 |
| SuspensionSite | 独立 ID、所属 interface、canonical operation/edge 引用、USER_YIELD/AWAIT_SUSPENSION、capture layout、accepted request cases | 静态暂停点；同一点可以动态暂停多次 |
| CaptureLayout | 有序 slot role/type、其 canonical operand/edge argument 的索引、对应恢复 formal role | 私有保留布局；不再存一套 Value actual→formal 对 |
| ResumeCase | site、封闭 request variant、canonical successor/boundary 引用、该次输入签名 | 允许的恢复形状；没有相应真实边/边界就不能产生 predecessor |
| ResumeInput | 绑定 site/case/slot 的边结果标记，类似 CompletionResult；类型由签名决定 | 当前 request、当前共享 state、新 caller token；不是旧值 Use 或独立 producer 表 |
| Context switch action | canonical operation、所属 interface/drive、caller token 输入/结果 role、frame context 输入/输出 role | 每次 drive 的安装/卸载；每个 token 恰有一个 canonical 来源，不能冒充 C1 Enter |
| Adapter interface | 方法/版本/生命周期状态、typed request 输入、body outcome→host outcome cases、current control-state 域 | NEXT/SEND/THROW/CLOSE、async request 驱动及 host 映射；不另存实际调用参数 |

全部 ID/enum/records 使用 exact 类型和 immutable tuple；Value/Use/Block/Operation/Region 仍引用已有强类型 ID。
请求视图为封闭 union：`Next | Send(value: UseID) | Throw(packet: UseID) | Close`；这些 UseID 必须属于对应 canonical request/drive Operation。Send 指向 ReferenceValue，Throw 指向 C0 EXCEPTION_PACKET；Next/Close 无隐藏 payload。async 方法请求对象的公开引用与此私有请求视图分开。
结果视图同样封闭：USER_YIELD/AWAIT_SUSPENSION 各引用实际 export Use 与私有 capsule，BodyReturn 引用已求值 ReferenceValue，BodyRaise 引用 ExceptionPacket。角色记录不能自行产生 Value、携带第二份实际参数，或把 Raise packet 当已发生 exception-state 写。
选定 A 的 body owner 是 body RegionID；未来 B lowering 若产生多个 segment Region，必须保留对该逻辑 body 的映射，不能声称这些 Region 各自就是新函数激活，更不能凭 Region.parent 猜调用关系。
公共 generator/coroutine/async-generator 对象是 ReferenceValue；私有 continuation/frame capsule 是 ProtocolValue。二者不能用同一“handle”混淆，也不能把已声明的 capsule 直接当运行时对象身份。
capture roles 至少覆盖 live references/temps/evaluation stack、LocalBindingValue、delegate、active handler/loop/cleanup 控制状态、各活跃 cleanup 的原 pending 和 C1 saved-context token。未保存的值不能跨暂停后继续使用。
保存引用只保留身份；引用指向的 list/cell/global/buffer 内容仍从当前 state 读取。environment 已如此区分引用/内容（`scar/ir/program/environments.py:39–55`）。
StateLocation 目前只有 id/label/extent/stability（`model.py:126–139`），没有完整 owner/alias 分类。默认所有现有外部/coarse world 域均为当前共享域；不能凭标签把一个域宣布为可回放私有快照。精细私有域需显式 owner/不外逃适用条件，否则保守使用 capsule 中的私有协议值加当前 coarse state。

## 3. handled context 必须保留“继承”而不是扁平异常值

这里至少有四件不同的东西：本次 caller ambient、frame-owned handler/context 状态、C1 某次 Enter 的 saved token、当前读取可见的 handled exception。它们不能互换。
官方 CPython v3.14.7 `genobject.c:225–243` 在每次执行时将 generator 自身 exception-state 节点接到**本次** caller 的 exception 链；`errors.c:108–117` 会跳过空自身槽沿 previous_item 查找。于是没有自身 handler 的 generator 可能继承本次 caller，而不是保存固定 None/上次 caller 异常。[genobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L225)、[errors.c](https://github.com/python/cpython/blob/v3.14.7/Python/errors.c#L108)。这是实现依据；下面是由此提出的抽象合同。

1. frame capsule 保存 body-owned handler/context 片段及其继承边界；可以抽象为可重定位的 chain/slot 协议值，不必复制 CPython 指针。不能仅保存 `sys.exception()` 返回的引用。
2. 每次成功进入 drive，context-switch primitive 捕获当前 caller 的恢复 token，将保存的 body 片段接到该 caller；初次进入使用空 body-owned 片段。所有可见读取从当前 handled-context state 求值。
3. 暂停/真实结束/从该 drive 抛出时，保存 frame 自身状态并恢复**本次** caller token；该 token 不允许放入跨暂停 frame slots，在下一次 drive 使用。
4. C1 saved-context 继续是原 Enter activation 的私有锚；若其内容涉及继承环境，需保留可重新绑定的关系，不能捕获上次 caller 的扁平 visible exception 并永久重装。
5. C1 `HandledContextRead` 只是当前 state 上的抽象读取，不能同时充当 frame context capture/restore（`docs/M1_CLEANUP_INTERFACES.md:57–75`）。同步 C1 的“捕获 ambient”文字不能直接推出跨暂停时的扁平快照语义。

A 初次 body entry 加入显式 capture/switch Operation，以 canonical result 产生本次 caller token；恢复 edge 的 ResumeInput 提供本次 caller token/state，landing 内安装 frame context，不能再次制造另一份 caller token。每次卸载只恢复对应本次 drive 的 token。这样不必偷改 Python formals。
若改为入口协议参数，必须扩展 entry partition：现 `FunctionEntryLayout` 要求非 state/non-environment 参数全是 Python ReferenceValue formals（`environments.py:121–129`、`environment_validation.py:104–122`）。新增 request/context 参数不能塞成隐式 Python 参数。
context/lifecycle/retain/release 等实际效果必须用当前 StateAccess 表达；当前 coarse world 不可仅拆一个 context 槽后宣称其余域无效果。C1 全域保守后态可以作为先例；FrameRules 的 UNRAISABLE 只约束其释放 primitive，不能套到用户 close/throw/delegate 调用（`frames.py:23–43`）。

## 4. A：同 Region 的显式 temporal successor

Suspend 是独立 terminator/outcome。canonical temporal successor 的 arguments 是 `UseID | ResumeInput`；saved Use 来自暂停 operation 的真实 operands，formals 是恢复 block 的真实 BlockArguments。
ResumeInput 仅用于本次外部输入/当前共享状态，不能包装旧 world Use 来伪装 fresh。每个 accepted request case 的目标、签名、slot 类型/角色必须完整；非法/未交付请求不走该边。
temporal 边表示“若该实例将来被合规恢复可到达”，不表示立即执行、保证未来恢复或把暂停后的路径视为本次 drive 已执行。host payload/outcome 与这些未来边分开定义。

同一 canonical 边派生两个查询足够，不另存第二图：

- logical CFG：含 temporal 边，处理结构可达性、原 cleanup activation、pending/context copy、entry-relative fresh。Suspend 不 pop cleanup、不再次 Enter、不释放原 frame。
- availability CFG：Region entry 和每个 resume target 作为定义可用性的 roots；cut temporal 带来的旧定义可用性。只经 saved Use→formal 的旧值可继续，LiteralOrigin 可全局可用。不能继续沿普通 dominance 使用暂停前的 OperationResult/entry argument。

这比只对 Suspend 的直接后继检查一次更强：loops 和多 resume merge 的所有普通 incoming 都必须求交。恢复后再走到另一个 merge/同一 yield 时仍要沿 formals 传值。root 的额外入口不创造 logical predecessor/可达性。
本轮选定独立 resume landing blocks：只接对应 temporal case，禁止普通边混入；case 处理完再通过普通 merge 合流。共享 merge 仍按每条真实 incoming 做值可用性和 copy 检查，不能把独立 landing 当作其后所有合流自动安全的证明。
saved Use 的可用性在暂停 source 点核验；目标 formal 是新定义。不要为通过 dominated-use 检查而给旧值“saved=True”全局豁免。
对当前 state，每个恢复 block 的全部共享 StateVersion formals 都由当前 ResumeInput 来，不保存旧 before/after；恢复后每条普通边继续现有 current-state 检查。私有 capsule 与共享状态的交界须 typed role 限制。
C1 pending/context forward 仅认真实 saved Use→formal，不能认 ResumeInput/重 pack 为原 token；fresh 仍相对同一 CleanupEnter，不因 availability roots 而重置。这些需要修改目前仅认识 CompletionResult 的通用遍历。
初次 entry、Suspend、resume、真正 body Return/Raise 的 context-switch 覆盖必须逐点核验，确保所有 drive outcome 都恢复 caller；Throw/Close 接真实 handler/unwind 路径，不能绕过已保留的 cleanup。

现 core 单入口可达性/普通 dominance（`validation.py:290–339`）、全 block 同 state 域（`:341–355`）、INVOKE 私有双 completion（`:281–286`）都需要明确 versioned 扩展。现 C1 stack 沿每条 successor 传播（`cleanup_validation.py:245–281`），可复用算法骨架，但不能不分 temporal/ordinary 地假装运行时连续执行。

## 5. B 比较：只保留为未来 lowering 投影

以下说明为何 B 不能绕过逻辑合同；root 已不采用它作为独立规范模型。后续若 lowering 到 segments，必须由 A 的同一 canonical producer/逻辑 activation 派生映射，不能独立手写一套相互不一致的 resume 事实。

每个 segment 保留原单入口 CFG/current-state/SSA。它的机器 NORMAL exit 可输出私有 `SegmentOutcome`，封闭区分 `Suspend(site, capsule, export)`、`BodyReturn(ref)`、`BodyRaise(packet)`；typed adapter 再决定 host normal/raise。
这是真实 segment 结束，**不是**原语言函数的 Return；Suspend case 不形成 C0 Return pending、不执行最终 Frame EXIT、不清空 logical cleanup stack。需要显式 segment role 与 outcome case 合同，禁止把普通 RETURN 的名字自动解释成 body completion。
边界 Uses/results、entry/exit ports、canonical caller invoke 仍是唯一 actual 来源；布局只引用已有端口索引。没有真实 caller/driver connection 时，仅声明两个 segment 属同一 site 不能给入口补 predecessor 或证明某实际恢复进入它。

B 必须额外解决：

- C0 pending 的跨 Region 入口目前被标 incomplete（`control_validation.py:32–52`），不能声明同一 port set 就当原 token。须有 typed capsule export/import 对应与原 token must-copy 依据。
- C1 每 Region entry 从空 stack 开始，saved-context 不准作 Region input/普通 completion payload（`cleanup_validation.py:120–128,245–281,376–394`）。必须增加私有 resumption boundary 例外和 inherited stack/activation 归属，不是放宽一般 call/exit escape。
- 不能在新 segment 入口伪造新 CleanupEnter：那会重复捕获 ambient、换 pending 锚、把新恢复误作新 cleanup activation。旧 saved context/pending 只能导入原逻辑 activation。
- 原 ControlScope/ControlPort 的同 Region 归属要有跨 segment 的逻辑 owner 对应；复制同名静态 scope 或新建 Return port 不能自动证明同一个 pending 目标。
- entry protocol partition、context switch、共享 state 的当前来源与代次 gate 仍需新增合同；“各 segment 现 core validate 通过”只证明各段内部结构。

因此 B 的复用优势限于段内；边界合同可能比 A 更大。若选择 B，必须把 private typed boundary 明确建模，不能以不透明 NORMAL payload 掩盖缺失的 C0/C1 组合证明。

## 6. 完整协议表面：三个层次不能合并

区分 body outcome（USER_YIELD/AWAIT_SUSPENSION/RETURN/RAISE）、一次 driver 方法的 normal/raise、整个对象生命周期（Created/Running/Suspended/Closed 或版本化等价状态）。不同 flavor 可以有不同终态/可重用规则，不共享一个万能 NORMAL token。

| 协议面 | 最小必须声明的区别 |
| --- | --- |
| Create/start | 参数/environment 保留与 body 真正开始分开；首次 send 非 None 的失败不伪造 body entry。初始 Throw/Close 有专门状态合同。 |
| Next/Send | 无 payload Next 与显式 Send(ref) 强类型区分；None 也是真实值。接受请求后从当前暂停点继续。 |
| Throw | payload 是已存在 C0 ExceptionPacket；校验/注入与 body handler 处理分开；可能再次 yield、return 或 raise。 |
| Close | 独立请求/adapter，以 GeneratorExit 协议处理；不能降成普通 Send/Throw 后丢失 close 的 host 结果与非法 yield 规则。 |
| Delegation | 先取得 delegate，再 next/send/throw/close；各隐式方法调用复用 canonical INVOKE 与状态/异常，保留父 continuation 和 delegate 身份。 |
| Await | awaitable 获取/校验、驱动 iterator、scheduler request、表达式完成分开；可能零次暂停；中间产物不直接是 await expression result。 |
| Async generator | anext/asend/athrow/aclose 的 request-awaitable 创建，与真正 drive body 分开；内部 await 与用户 async yield 分开；请求对象自身也有生命周期。 |
| Cancellation | task cancel request、实际 delivered exception、被 body 捕获/抑制、task 真正取消/结束分别声明；用已交付 Throw 进入普通异常机制。 |
| Finish/escape | 真 Return、body escaping exception、适配后的 exhaustion 不靠异常名字推断；已 Closed 的方法行为不重放旧 Return payload。 |

版本化依据：3.14 reference 的 generator/async-generator 方法、coroutine 规范与现控制分册分别覆盖这些阶段。生成器 close 在 3.13+ 可返回 body 的 Return 值，非法 yield 会报错，不能统一假设 None/Closed；原生 coroutine 的关闭/复用规则也不能直接套 generator 表。[generator methods](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)、[coroutines](https://docs.python.org/3.14/reference/datamodel.html#coroutines)、`docs/model/PYTHON_CONTROL_PROTOCOLS.md:335–416`。
委托非 None send 不应自动回退 next，delegate close 失败可外传；这些是显式协议分支，不是普通词法子 Region。[PEP 380](https://peps.python.org/pep-0380/)。body 自行逃出的 StopIteration 与正常 Return 的 exhaustion 需分开。[PEP 479](https://peps.python.org/pep-0479/)。async generator 的内层 await 和对外 yield 确有不同协议结果；不直接复制历史 PEP 中后来修改的所有 close 细节。[PEP 525](https://peps.python.org/pep-0525/)。
Task.cancel 只是安排后续抛入 CancelledError 的请求，可以被捕获抑制；不能据 request 推定已经交付、清理完成或资源 ready。[asyncio cancellation](https://docs.python.org/3.14/library/asyncio-task.html#task-cancellation)。

## 7. 静态 ownership 与运行时证据的分界

最小静态 gate 合同应引用当前实例控制状态域（可先用 coarse world），封闭声明接受/拒绝请求的条件、成功开始 drive 的 claim、再次 Suspend 的 publish、完成后的 finish。claim/publish 必须有 canonical 操作/结果和当前 StateAccess，不能只是 `single_use=True`。
capsule 可以携带 expected instance/generation 的协议身份，但运行时 matching、互斥执行与单次消费必须由实际 adapter/guard 及证据保证。把 saved generation 的旧副本恢复成当前 lifecycle state 会使同代重新可消费，必须拒绝。
静态可核验 owner/site/slot 类型、私有不逃逸、gate 声明的路径覆盖、真实 copy/当前 state 来源；不可证明别名 generator 引用属于哪个动态实例、某请求已被接受、并发互斥已发生、某 generation 从未重复执行。
不能用 SSA Use 次数=1 当线性证明：互斥分支可以各有一个合法 Use，同一个静态 site 会有多次 visit；非法启动/重入尝试也不能消费一个未实际开始的 continuation。
未落实 source/driver 对应时，查询只能报告 declared boundary/unknown origin；不把接口 ID 匹配当自动导入/执行边，不把当前暂停状态当将来必达，不把无 observed exit 当静态发散证明。

## 8. 冻结前必须能解释的反例

| 反例 | 必须拒绝/保留的事实 |
| --- | --- |
| 两次 next 之间外部修改同一 list/cell/global | 保留引用，读取当前 state；不得恢复 yield-time world。 |
| 暂停前 x 的普通 dominance 跨过 yield；恢复目标间接 merge/loop 再用 x | 没有 saved Use→formal 就 unavailable；不能只查直接 landing。 |
| 两个恢复分支一条保存旧 binding，另一条没保存或换值 | merge 全 incoming 证明，不能用 capture 集合/类型相同当值相同。 |
| yield-in-finally 时 pending Return、局部 break 或已安装 Raise | 同一 cleanup activation/pending/context 继续；暂停不 pop，不重跑 Enter；新注入异常依真实路径 replace。 |
| generator 自身无 except，先在 except A 内 next，再在 except B 内 send | 本次继承 B；不得冻结 A 或固定 None。 |
| generator 自身 except 跨 yield，caller 换异常上下文 | 自身 handler 保留；退出自身 handler 后继承本次 caller，drive 返回恢复该 caller。 |
| 同静态 Enter/site 的旧 visit token 或上次 caller token | 静态 copy 不等于动态代次匹配；旧 caller token 不进 capsule。 |
| Created send(non-None)、close，及 Running 重入 | 不伪造 body/finally 进入或重复执行；错误请求有自己的 host outcome。 |
| close 捕获 GeneratorExit 返回值，或清理中再次 yield | 前者使用版本化结果；后者失败后不能一律标 Closed/释放 frame。 |
| yield from 普通 iterator 收到非 None send；delegate.close 抛异常 | 不伪造 next fallback/自然 exhaustion，保留新异常及父 pending 处理。 |
| await 立即完成，或多次产生 scheduler request | 零次暂停合法；中间 request 不是表达式结果，也不证明资源 ready。 |
| asyncgen aclose 创建后未 await；aclose 内 await 与用户 yield | 创建不等于 body 运行；内部 await 可暂停，用户 yield 另走非法关闭结果。 |
| cancel 被 body 捕获；两个别名并发恢复同一对象 | 不推定已终止/完成清理；运行时 gate 而非静态 handle 名称保证互斥。 |
| B segment Suspend 输出被认成函数 Return，或新 segment 重新 Enter | 不执行 Frame EXIT/cleanup pop，不改变原 pending/context activation。 |

上述是设计判据，未伪称已运行新的协议测试。现控制分册记录的旧观测与官方规范仍分别是证据来源；新类型声明、validator 接线、人工 IR 实测、source/runtime 自动对应必须分别验收。

## 9. 开始代码前尚须闭合

以下是 A 的合同清单，不是新增编译器任务；未闭合项不能以 `UNKNOWN` 偷换成已证明接线。

1. **creation/admissibility/HostOutcome**：冻结三种 flavor 的创建与首次进入关系、Created/Running/Suspended/Closed 下每种请求的接受/拒绝；明确 pre-entry failure 不进入 body、不产生假 continuation 消费。逐 case 写出 USER_YIELD/AWAIT_SUSPENSION/Return/Raise 到方法 normal/raise 的版本化映射，特别是 close 返回值、错误后 lifecycle 与 async request-awaitable 自身状态。
2. **context 继承重定位**：冻结 frame-owned 片段、inherit-current-caller 标记与 C1 token 的解释；初入 capture 与恢复 ResumeInput 的唯一 caller-token 来源；安装/暂停/结束/抛出的卸载覆盖与当前 state 效果。不能冻结为一个具体异常引用或 saved None。语言 agent 的新观测应另附证据，不与本报告的官方源码审查混称。
3. **cut availability**：冻结独立 landing、两种派生查询的边集合/root、LiteralOrigin 特例、capture slot roles、saved Uses 的 source 可用性、loop/多 resume 合流规则。明确 C1/fresh 使用 logical CFG，而非 availability roots。
4. **current shared-state ingress**：冻结每个恢复 case 的全部 state signature、ResumeInput 的 scoped 类型和 caller/frame 安装先后；禁止旧共享 StateVersion capture。现有粗域保守复用，细粒度 private ownership/alias 不作为本轮前提。
5. **delegation/cancel/await**：冻结 next/send/throw/close 的 delegate 分支及失败来源；await acquisition、零暂停与 scheduler yield；asyncgen 用户 yield 与内部 await；cancel request 与实际 exception delivery 的边界。未知 callable/调度器实现保留不透明正常/异常效果，不编造 body execution/ready 证明。
6. **C1 保存/恢复**：冻结 temporal saved Use→formal 对 pending/context 的身份复制、active cleanup stack 保持、暂停不 pop/不 Enter/不 Frame EXIT、恢复后新的异常真实 unwind/Replace、同静态 site 多 visit 的动态权属限制。不要把重 pack 或同 port set 当原 pending。
7. **独立事实与验收界限**：冻结 record/edge/result 的唯一来源、禁止私有值逃逸的例外范围、entry partition、codec/query 语义和 static-vs-runtime claim。列小型人工 IR 反例门槛，完成后分别报告类型声明/validator/人工实测/自动 source-runtime 对应；不以测试数当建模覆盖率。

闭合后只实现 A 的可审查静态组件，用第 8 节有限人工 IR 检验组合；B 留作派生 lowering。没有要求先造 Python 编译器：未建模外部行为保持保守与明确 unknown provenance，不能因此宣布整个 Python resumption 已验证。第一阶段完成后先停并说明。
