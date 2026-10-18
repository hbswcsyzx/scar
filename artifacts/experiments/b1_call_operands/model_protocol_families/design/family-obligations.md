# C2/D3 resumable protocol families：义务与连接审查

状态：只读审查，基线 `/tmp/scar-structured-model-280qf4mi`，HEAD
`08c4cbfc6b675919ab15e8654567889727f3c466`。本报告不改产品、测试或共享文档，
不运行 pytest、Python 语言见证、LeWM、GPU 或编译工作负载。它保留完整协议分母，
不把 C2B/D1/D2 子门或一条 opaque 边称为 C2/D3 完成。

## 判断

现有静态 IR 已能保留 resumable body 的单一 CFG、typed suspension/resume ports、
frame-private 保存、每次 ingress 的最新 state、Create/driver 声明、首个 body outcome
frontier、context 与部分 lifecycle。它是可继续接线的模型基础。

**C2/D3 仍有两个独立缺口。** 静态 family 规则还没有把每类 raw request、前处理、
实际 BodyDrive 输入、body outcome 和 Python host adapter 连成经校验的协议；Execution
层也没有把某次动态 driver invocation 连接到持续的 body activation、本次真实 ingress
segment 与实际 first-outcome occurrence。即使补好其中一个，另一个仍然开放。普通
CALL/INVOKE、`ResumeInput` 或 `DriverRule` 的名称都不能代替这些连接。

Created.throw 是一个已复现实测的特别路径：有效初始 throw 不运行 generator/coroutine/
async-generator 用户 body，却会让对象关闭并向 host 抛出异常；无效参数则可能保持
CREATED；异常类构造器失败又观察到 CLOSED。它既不是 BodyStart/BodyResume，也不能
直接套 Created-close 专用的 NoBodyFinish。

## 审查范围与来源指纹

源码、规格均按当前 clean HEAD 读取。路径及 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `docs/M1_RESUMPTION_INTERFACES.md` | `1d42e97c34c7288067c867026369ee29db1725b4b9525a93204d5bc419a405b2` |
| `docs/M1_DRIVER_INTERFACES.md` | `4ce49de650d58d77dc78a5d98184b57739b28a1f721d68b31eb54c6da4b32a79` |
| `docs/M1_DRIVER_CONTRACT_V2.md` | `4a943058b1accf60e8be708c1770a958d914e77ef772a82f37065b296ca57f0a` |
| `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` | `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699` |
| `docs/model/PYTHON_CONTROL_PROTOCOLS.md` | `db0269f2fd50e9da3fde14986d4f1e69d19c0751f63f24661b53a1ed62c7707d` |
| `scar/ir/program/resumption.py` | `ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac` |
| `scar/ir/program/drivers.py` | `d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd` |
| `scar/ir/program/resumption_validation.py` | `3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a` |
| `scar/ir/program/driver_validation.py` | `4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3` |
| `scar/ir/program/driver_flow.py` | `1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa` |
| `scar/ir/program/lifecycle.py` | `326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7` |
| `scar/ir/program/lifecycle_validation.py` | `49dee4e82ebe09964a1a72c0d5d19fc91b67645822e7b1abc4961d13ba381daa` |
| `scar/ir/execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `scar/ir/execution/flow.py` | `e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc` |
| `scar/ir/execution/calls.py` | `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f` |
| `scar/ir/execution/call_validation.py` | `9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2` |

Historical stdlib observations are reused as observations, not rerun tests. The earlier
CPython 3.14.7 runtime/delegation/context/bytecode JSON hashes are respectively
`3a7c543e62d2b1d710717ec7291e6517827e0a2938b024bc7f71afd4708fb8f7`,
`98d81a011cd26a38e3fca9d5d0563f3a64930dba6cf59f360642fbc79ef66dfa`,
`08ad741a3d15a831e6a10a6c33cb5fc0baf5c9fce74bab655a44f7ae5b19d071`, and
`55676c0e5cbf3970576a7d05cd5949854332db4c8f8bc96748745ef2657eca6d`.
The four delegate-context observations are in
`language-delegate-context-probe.json` (SHA
`64e752d1e3f88da6879a0a4a4bdf62c69f22c48d04f55eee80dcf9a833dc2f1d`). These were
small CPython 3.14.7 observations, not assertion suites and not source/runtime evidence for
SCAR.

An additional root-owned bounded CPython 3.14.7 witness is archived at
`artifacts/experiments/b1_call_operands/model_protocol_families/created_throw_witness.json`
(SHA `a252e2b377fcbd227f1a188278f52dee9667b41b5a3d88c2e7d287768b0ebc0d`). Its script
SHA is `511abb54885c693fd10910fda359e247ed3ebcb3815dcab076d54f15f46009df`. Six cases
are recorded. The first assertion attempt passed the empty-body-log assertion and then
stopped at `constructor_failure`: the script incorrectly expected both invalid input and
constructor failure to leave the generator CREATED. Preserve that failed attempt and JSON
as written. The later assertion expecting a StopIteration-to-RuntimeError conversion was
not reached. That expectation belongs to the root-owned witness script; it was not this
review's earlier inference. The observation JSON instead records the original StopIteration
and a CLOSED generator. This review's earlier, separate source inference that any exception
normalization failure restores CREATED was incorrect and is retracted below.

The old IR probe `current_core_probe.json` (SHA
`51aaa2ebdda244aae1c0afddd22f881422c163200e120ba8c3d06d9c0e191d09`) was prepared by root
against this exact HEAD. It reports five structural checks: four family-incompatible or
adapter-unproved constructions validate, while `COROUTINE + YIELD` is rejected by the
existing `resumption_flavor` check. Those acceptances are not claimed as valid Python
adapter graphs; they show the precise limit of today's typed checks.

Online version note: the linked Python 3.14 documentation currently serves 3.14.8. The
language witnesses ran CPython 3.14.7. For the Created.throw source trace below, the code
link is pinned to CPython tag `v3.14.7`; it is source inference, while the six local
observations are runtime observations.

## 已有静态结构

| 实现 | 可直接复用 | 它没有证明什么 |
| --- | --- | --- |
| `ResumableBody`, `SuspendTerminator`, `ResumeSuccessor`, `SavedRole`, `ResumeSlotKind` (`resumption.py:32–190`) | body family、YIELD/DELEGATION/AWAIT/ASYNC_YIELD、saved locals/pending/context/delegate ref、handoff 所有 current state、每个 temporal successor 独立 landing 和 slot。 | 这条 static edge 在某一运行实例上发生，输入由哪次 request 投递，或该 site 只被消费一次。 |
| `resumption_validation.py:145–204` | 按 family 限制 suspension flavor；Coroutine 不能用 YIELD；检查每个 state slot、saved role、当前 Detach frame 与 ingress Attach。 | raw request 到 slot 的语义映射、Python 方法对 packet 的构造/校验、host result 适配。 |
| `ResumableCreate`, `AsyncRequestCreate`, `RequestAssociationRead` (`drivers.py:95–162`) | 静态 Create capture；async request 创建与当前 request→body/latent 关联读取分开；使用原 INVOKE normal result ports。 | 两个静态 Create 中哪一个对象被本次驱动，association 声明已在运行中读到，或 request 已被 await/消费。 |
| `RawRequestDefinition`, `DriverInterface`, `BodyStart/BodyResume`, `BodyDrive` (`drivers.py:66–299`) | NEXT/SEND/THROW/CLOSE 的 raw operand arity；BODY/ASYNC_REQUEST receiver、raw scheduler、D1 final gate；body Start 入口无动态 resume slots，Resume 根据 Suspend signature 提供 sent/packet/delegate 与每域 state。 | request arity以外的 method 语义；raw THROW class/value/traceback 已变成 exception packet；raw SEND/THROW operand 与具体 delivered slot 对应。 |
| `BodyDriveTerminator`, `first_body_outcome_operations` (`driver_flow.py`) | 每个 Drive 必须列出其入口/该 resume landing 上沿普通 CFG 的精确 first Suspend/Return/Raise frontier；不跨下一条 temporal edge；发散路径不造出口。 | Python host outcome 是 Return/StopIteration/StopAsyncIteration、close result、scheduler handoff，或哪次 async request complete。 |
| `DriverLifecycle`, `BodyOutcomeCommit`, `CreatedCloseTest`, `NoBodyFinish`, `SessionUpdate`, `TerminalFrameRelease` (`lifecycle.py`) | body outcome publication 与 request/body session、created-close no-body 路径、terminal release 分开；Suspend 不 seed body-finished；当前状态沿 core state SSA。 | 任一家族的完整状态机、close 失败的实际状态、异步 request 的成功/取消完成、析构/finalizer 完成。 |
| `RegionActivation`, `ExecutionSegment`, `InitialEntry`, `ResumeIngress`, `OperationOccurrence`, `UseOccurrence` (`execution/coordinates.py`) | 实际 Region activation、初入或由哪个 suspension occurrence/index 恢复的 segment、block/op/use/value occurrence。 | segment 是由哪个 BodyDrive occurrence 造成、跨多个 segment 的 body 是同一 continuation generation，或者该次 drive 的实际 outcome。 |
| `CallActivation` (`execution/calls.py`) | 普通 CALL/INVOKE 的 caller↔callee activation 和精确原 actual/formal、出口/landing 对应。 | 不能复用给 BodyDrive：BodyDrive 是独立 typed terminator，不是 callee INVOKE；持续 body 可跨许多 driver calls，一个 call activation 也不等于一个 body generation。 |
| `DriverRuleProfile.PYTHON_RESUMPTION_V1` + `ProviderFactReference` | 一个版本化规则引用和来源定位。 | profile 名称或 FactReference 不是规则表、执行事实、native correspondence 或 `verified` 位。 |

这些实现保护了 canonical graph：producer、owned Use、CFG successor 和 state SSA 仍只
保存在 ProgramGraph。任何后续连接都应引用其 OperationID/ValueID/UseID 和 execution
occurrence，而不是复制一套 arguments、结果或 state 图。

## 完整 family 分母与逐项缺口

表中“已有”只指 IR 可表达/可验证部分；“缺”是 family 语义的静态连接或动态
correspondence，不能由 opaque 名称补齐。

| family / 路径 | 必须分开的事实与当前承载 | 缺失的连接与具体反例 |
| --- | --- | --- |
| **Generator 创建与首次启动** | function definition/code、已绑定 captures/Environment 与 generator object 是不同阶段；`ResumableCreate` + `BodyStart(body)`，initial Attach 接 frame context，body entry state 由当前 Drive state 输入。next / send(None) 首次才运行 body。 | `BodyStart` 没有 resume slots，能表达“按 capture 开始”但无规则约束 raw NEXT 或 SEND(None) 的差别、谁有资格启动。accepted Create 是抽象已绑定 frame-create，不证明原 source call/default/pack/capture。 |
| **同步 generator Next/Send** | `RawRequestKind.NEXT/SEND`，正常 yield 为 `SuspendTerminator(YIELD)`，yield expression 输入在后续 `SENT_VALUE`，每次恢复 state 从最新 current values 提供。历史探针看到共享 dict 两次恢复间改变，不能保存成 private snapshot。 | validator 不把 NEXT→yield expression None、SEND(v)→相同 request 的实际 v 与具体 resume case 连起来。能将另一条合法 Reference Use 作为 sent input；仅类型正确不能证明它是 request operand。 |
| **同步 Throw（已暂停）** | 原 raw throw 1–3 有序 Reference Uses；`ResumeSlot(THROWN_PACKET)` 可表示已规范化异常；Raise/handler/cleanup/context 由 core/C0/C1；当前 caller context 与 frame saved context 分开。 | raw type/value/tb 的形状检查不等于 traceback 验证或 exception construction。异常类构造可回调/失败，packet 可能还未形成；它可能在真实 body resume 前失败。没有 exact raw operands→normalization INVOKE/result→selected resume packet 的 relation，也没有 caught/yield/terminal host outcome profile。 |
| **同步 Throw（Created，无 body entry）** | 六组 root 见证中：有效 ValueError instance 对 generator/coroutine/async-generator body log 为空且对象 closed；无效 raw `42` 在 generator 上报 TypeError、仍 GEN_CREATED，随后 next 可进入；自定义 exception constructor 记录回调后抛 RuntimeError，body log 空但 generator closed；Created throw `StopIteration` 观察为原 StopIteration 且 closed。Asyncgen 的 request 创建阶段仍 AGEN_CREATED，await 后才见 closed/error。 | 这不是 BodyResume（没有 prior Suspend），也不是正常 BodyStart（用户代码/finally 未运行），不是仅 CreatedCloseTest/NoBodyFinish（它要求 close+真实 true edge）。还需一种 source-relative initial-throw/no-user-entry outcome，引用原对象、raw request 和真实规范化/失败 source；区分 invalid-before-delivery 保持 Created、constructor failure 和成功 delivery 后 closed，并把原 host exception 接出去。静态构造方案仍 OPEN，见下一节。 |
| **Close / GeneratorExit / frame 状态** | CLOSE raw 无 operand；已暂停 body 可用 THROWN_PACKET 表示注入 GeneratorExit；Return/Raise/Suspend 是真实 outcome；Created-close 独有 `CreatedCloseTest` bool 分支与 `NoBodyFinish`。历史见证：finally 中 close 再 yield → RuntimeError，但对象仍 suspended；后续 close 才能结束。 | 没有 family guard 证明 CLOSE→GeneratorExit；body terminal Return(v) 在 Python 3.13+ 的 close 可返回 v；非法 yield 的 host RuntimeError 不应把 body mark Closed。异常 finalizer/unraisable、release 的完成/后效也不是 terminal release declaration。 |
| **yield-from / iterator delegation** | `SuspensionFlavor.DELEGATION`、saved `DELEGATE_REFERENCE` 与 `DELEGATE_VALUE/DELEGATE_PACKET` slots 能保留相关端口；父体 Yield / Return / Raise、普通 callback INVOKE 可以保留核心 edges。 | delegate `.throw` 存在时可能直接回给 host 一个 item，父 body 没有恢复；无 `.throw` 时异常落到父体；child StopIteration.value 成为父 yield-from expression，而 parent Return 是另一结果；close 转发有独立 callback。静态 delegate Ref 不指定当前 iterator identity/方法存在/调用结果，也没有 delegate-only drive outcome。context witness 还证明 delegate direct throw/close callback 可看到外层 caller 的 B，而正常 next/send sees 父 handler A；不能先无条件 Attach parent 后调用 delegate。 |
| **Native coroutine / await** | `ResumableKind.COROUTINE`+`AWAIT`、scheduler raw、Resume sent/packet/state slots、Return/Raise/Suspend frontier 能表达一个原生 coroutine body 的结构。`FrameContextAttach/Detach` 和 C1 saved context 可接 handler state。 | `await x` 的 `__await__` 查找/调用、结果必须是合规 iterator、generator-based coroutine/native coroutine 与普通自定义 iterator 都没 family adapter。await 可零次挂起；中间 yield 是 scheduler handoff、StopIteration.value 才是 await expression result。body Return(v) 对 host coroutine driver 不是裸 `RETURN(v)`，还需实际 await adapter；错误 awaitable/重复 await/reentry 不等于 body Raise/finish。 |
| **Async-generator 请求与 async yield** | `AsyncRequestCreate` 与 `RequestAssociationRead` 区分 awaitable request 创建和 body/latent 读取；DriverInterface 有 `ASYNC_REQUEST` receiver；`ASYNC_YIELD` suspension 可输出 item，同一 body 后续仍可再驱动。历史探针观察 request 创建不运行 body，await 才运行。 | 没有本次 request await/delivery→BodyDrive association；请求的 awaitable完成和 body terminal 不同。`anext/asend/athrow/aclose` 的 created/start/suspended/closed 路径、初次 asend 非 None、throw/aclose 的 GeneratorExit、yield-on-close、StopAsyncIteration 和 StopIteration item carrier 尚无严格 family matrix。异步生成器禁止非空 return也没在 source→IR adapter 此处校验。 |
| **Task cancellation / cancellation delivery** | INVOKE/Raise/Resume(THROWN_PACKET)、普通 state/CFG 可表示某处实际观察到的 CancelledError、catch 后继续或 terminal。历史 Task.cancel 见证：cancel 请求之后 coroutine 捕获 CancelledError 后正常返回，`task.cancelled()` false，取消计数仍 1。 | Task.cancel 是 task 上的请求，不是 `.throw()` 的同义调用，也不证明异常已投递或 body 已结束。RawRequestKind 没有 TASK_CANCEL（合理地，它不是生成器方法）；但无 task identity/cancel-request/delivery/uncancel/status 关系。若 D3 需覆盖 asyncio lifecycle，必须加独立层；若不覆盖，应保留明示外部边界，不能把取消压为 body THROWN_PACKET 后宣称理解。 |
| **Frame handlers、pending completion、终结/最终化** | `FrameContextInitial/Attach/Detach`、SAVED_HANDLED_CONTEXT 与 DRIVE_CALLER_CONTEXT、Saved pending/cleanup roles、C1 cleanup、BodyOutcomeCommit、SessionUpdate、TerminalFrameRelease 分层；已存见证确认空异常槽继承 caller 而不是固定 None，局部 handler 可跨 yield，pending Return 可与 caller active exception 并存。 | 当前记录是声明式结构。它不验证 CPython 在每个 dynamic call/await/delegate path 上是否安装/恢复该 context，不涵盖 asyncgen finalizer hook 完整生命周期、错误报告或 task/event loop shutdown。FrameRules 明确允许未知 hook/effect、不保证完成。 |
| **重复 drive / epoch / body generation / 实际 outcome** | Static `BodyResume(suspend,successor)` 与 execution `ResumeIngress(suspension occurrence,index)` 可指同一个静态 site 的多次动态 occurrence；每次 ingress 都有独立 segment 和当前状态。 | ExecutionModel 无 `BodyDrive OperationOccurrence → 持续 RegionActivation → 本次 ingress ExecutionSegment → 该次 first body outcome occurrence` 的 typed link，也无 driver request / async-awaitable occurrence 对这次 drive 的 link。普通 `CallActivation` 限于 CALL/INVOKE 的 child activation，不能表示一个 body activation 被许多 BodyDrive 持续驱动。静态 operation ID 不能代表 request epoch、dynamic generation 或单次消费。 |

## Created.throw：记录的证据和可选形状

### Observed

CPython 3.14.7 的六组 witness 中，用户 body 和其 `finally` 均没有在初始 throw 时运行。其
中 invalid raw `42` 留在 CREATED；构造自定义 exception 期间的 callback 随后 RuntimeError
却使 generator CLOSED；对一个 StopIteration instance 的 throw 原样传播 StopIteration，
且对象 CLOSED；普通 instance 的 generator/coroutine/async-generator 均 CLOSED。Asyncgen
只在 await 其 `athrow` request 后变 CLOSED，request creation 本身仍 AGEN_CREATED。

首轮 witness 的空 body-log 断言通过，随后要求 invalid 与 constructor-failure 都保持
CREATED 的断言在 constructor-failure 项失败；不要声称 StopIteration 那条 assert 也实际执行
或失败。原 JSON 是六条事实观察，脚本 SHA 与结果如上。此前本审查从源路径推断“exception
normalization 失败会恢复 CREATED”，该推断错误，现撤回。另一个独立错误预期是 root-owned
witness script 后置断言把 Created.throw(StopIteration) 预期为 RuntimeError(cause=StopIteration)；
该断言未执行，且不属于本审查先前的推断。PEP 479 不可机械套到这个初始 throw：JSON 中
StopIteration instance 是原异常并关闭对象；这行是观察，不应描述成 body 内 StopIteration
被 PEP 479 包装。

### CPython 源码与版本化文档

固定 3.14.7 的 [`Objects/genobject.c`](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c)
把 raw throw normalization、delegate throw fastpath 与 `gen_send_ex` frame driving 放在
同一入口；`throw` 触发异常 normalization 可执行用户 exception constructor。该源码能定位
哪些真实边必须拆开，但不是 SCAR adapter。在线 [Python 3.14 expressions](https://docs.python.org/3.14/reference/expressions.html)
描述 throw/close、asyncgen method 先返回 awaitable 且 await 才驱动；它当前显示 3.14.8，
不是 3.14.7 本机见证。异步 cancel 规则见 [Python 3.14 asyncio Tasks](https://docs.python.org/3.14/library/asyncio-task.html)。
方法细节还可核对官方 [PEP 380](https://peps.python.org/pep-0380/)、[PEP 479](https://peps.python.org/pep-0479/)、
[PEP 492](https://peps.python.org/pep-0492/)、[PEP 525](https://peps.python.org/pep-0525/)；
PEP 479 适用于 generator body 中逃逸的 StopIteration，不能把本 witness 的 initial injection 改写为 body Raise。

### 两种可审查的结构形状（Proposed，未冻结）

1. **独立 no-user-entry outcome（推荐继续审这条）。** 从已声明 CREATED instance 与确切
   THROW raw operands/实际归一化 operation 分出 `NO_USER_ENTRY` 的 driver terminal；该结果
   明确带 host exception 和 object lifecycle outcome。`BodyStart`/`BodyResume` 都不执行，
   body outcome 与 BodyOutcomeCommit 不伪造。按可观察分支保留三种不同轨迹：参数无效、规范化
   callback 失败、成功注入后异常向 host 传播。优点是不会谎报 body entry；validator 必须把
   lifecycle after 与准确 source edge 绑定，且把 callback 真实 Invoke/partial post 保留。
2. **Initial injection port，但仍不进用户 body。** 给 driver 侧增加“入口前投递异常”的
   独立端口/分支，随后产生同一 no-user-entry outcome。它不能作为 `BodyStart.resume_inputs`
   或 FunctionEntry formal：否则可把 thrown packet 传给用户 body block 并允许 handler/finally
   执行，和 witness 冲突。它可能更明确暴露 exception normalization 的时序，但多一个静态
   port容易与真实 Invoke 的 operands/results重复，只有在现有 INVOKE＋驱动 outcome 无法标定
   入射异常/生命周期时才值得加。

`NoBodyFinish` 现有合同明说是 `CreatedCloseTest` 的真分支；不可拿它为 THROW 造 predicate，
也不能只在任意 `Raise` 上附加 “closed” metadata。先冻结上述四个实际分支及 ASYNC_REQUEST
“created request → await/delivery → no-user-entry result”的精确 relation，再决定最小记录形状。

## 静态 false positives 与要连接的规则

旧 `current_core_probe.json` 在声明图上实际看到：

1. Generator body 的 `Suspend` outcome 接到 driver `RETURN`：结构接受，可对应一次 yield item，但不能证明 host 实际收到 item。
2. Generator body 的 `RETURN` 直接接 driver 正常 `RETURN`：结构接受；Python generator exhaustion 应经 StopIteration.value adapter，而不是裸普通 Return。
3. Generator body 的 `RAISE` 直接接 driver `RAISE`：结构接受；packet identity、wrapper 和 handler/caller context 没被证明。
4. GENERATOR body 可声明 `receiver_kind=ASYNC_REQUEST`，并把 body Return 直连 driver Return：结构接受；family 和 async request/host result 规则没有约束此关联。
5. `COROUTINE + YIELD` 被 `resumption_flavor` 正确拒绝。这个局部拒绝是有效边界，不代表其余 generator/coroutine/asyncgen 适配已证明。

raw request arity也只是约束：NEXT/CLOSE 为 0，SEND 为 1，THROW 为 1..3 个 reference Uses。它
没有保证这些 Uses 到达正确 packet/delivered slot；不存在函数名、method label 或 Value type
可以推断 family outcome。

## 最小连通方案与有限验收门

### 静态关系（M1/M2）

继续单一 canonical ProgramGraph：Suspend、body operations、Invoke signatures、state accesses、
pending/context、Resume slots 和 host adapter operations 都沿原 Uses/results/ports 表达。增加的
只能是引用这些 canonical ports 的窄 family-rule/adapter 关系，并按 versioned rule/provider
定义、显式适用范围、source route 与本体类型校验。最小闭环需要连接：

1. raw request kind/原 ordered operands → 真实 normalization/association operations → 本次
   accepted、rejected、delegate-only、no-user-entry、Start 或 Resume 结果；每次 Invoke 的
   NORMAL/RAISE 与部分 state 后态都保留。
2. accepted 的 delivery 到唯一对应的 `ResumeSlot`（或 Start 无 user input）；raw SEND/THROW
   引用不许按端口个数/类型随便挑。Created.throw 是 no-user-entry，不是 ResumeSlot。
3. `BodyDrive` first frontier source → 按 ResumableKind + SuspensionFlavor + request kind 得到的
   host result/status 和值端口。Generator Return/StopIteration、coroutine await result、asyncgen
   item/StopAsyncIteration、close 值/错误各有显式 adapter；body Return 与 driver host Return 不
   互换。
4. delegate/await 内部的 callback INVOKE、item/packet/result、父体是否真正恢复，以及当次
   current state/context。允许直接 delegate-only outcome；不强制伪造 parent BodyDrive。
5. Created-close、Created.throw、suspended close 与 finalizer release 必须由不同源边、state
   后态和 host outcome 表达；Task cancellation 独立于 raw `.throw()`。

不要求静态 family rule 证明 native 执行已正确。unknown provider/profile applicability 必须保留
gap；不能按名字或类型把现有图提升为 Verified。

### 动态关系（D3/M4，复用既有 ExecutionModel）

对真实进入 body 的一次驱动，薄关联以 `BodyDrive` 原 `OperationOccurrenceID` 为 drive occurrence，
连接实际 instance、持续的 body `RegionActivationID`、本次 `ExecutionSegmentID`（ingress 使用
已有 `InitialEntry`/`ResumeIngress`）和本次实际 body first-outcome `OperationOccurrenceID`。instance
Use 从原 BodyDrive operation 的 Use 派生；segment 从原 entry/resume visit 派生，不复制第二份
Use 或 segment 字段。ports 从 ProgramIndex/D1/C2 queries 派生，不复制 actuals、结果或 state。

无用户入口和 delegate-only 是另一类 F 路径：它们锚定实际 driver/helper/adapter occurrence，并
连接其请求、状态与 host 结果；不能创建虚假的 `BodyDrive`，也不能要求一个不存在的 body segment
或 first outcome。request creation、request await/delivery、body activation、drive epoch、body
suspension generation、host result 各保留自己的 identity/status。需要有关系时才跨这些事实连接，
不把单个名字或同一对象类型当作关联证据。

CallActivation 不适用：它要求真实 CALL/INVOKE caller 和 child activation，一次普通 call 路由到
callee；BodyDrive 是 body 控制 terminator，同一个持续 body activation 会被多次 driver invocation
跨不同 segment 恢复，且可在另一 host thread 上恢复。BodyOutcomeFrontier 只是静态首源，不提供
具体 occurrence 或“一次 generation 被消费一次”的证据。

### 必需正反例

| 场景 | 正例必须看到 | 必拒/必须保留 gap |
| --- | --- | --- |
| Create/Start | 两个 Create 各有精确 capture，同 body 多 drive；Start state 取 gate 正常后态。 | 无实例来源不能借同 Code/Environment 自动选 Create；创建不等 body entry。 |
| NEXT/SEND/THROW | 每条 raw Use 映射到特定 effective input/packet；catch 可以再 Suspend，uncaught 可 Raise。 | 类型相同的非operand Use、交换 SEND/THROW slot、缺失 traceback/异常构造效果。 |
| Created.throw | invalid 42→TypeError+CREATED 可再次 next；constructor callback RuntimeError→CLOSED；StopIteration instance→原异常+CLOSED；所有这些无用户 body/finally。 | 把 initial throw 变成 BodyResume、伪造用户 handler/finally、把所有异常化失败折成 CREATED 或把 StopIteration 用 PEP479 擅自改写。 |
| close | Created close no-body；Suspended close 向实际 yield site 注入 GeneratorExit；close 中 yield 后 RuntimeError 且 body仍 Suspended。 | 见 CLOSE 即 closed；无 NoBody true edge 捏造 completion；把 RuntimeError host error 和 body terminal 合并。 |
| yield-from | delegate yield/send/throw/close、child terminal value 与 parent terminal value，direct callback 与 parent resume 两个不同 routes。 | 代理方法缺失/直接回 host 仍伪造父 body ingress；把 parent handler context attach 到外部 fastpath。 |
| coroutine/await | async function create ≠ first await；scheduler token ≠ await result；零次 suspension可直接 result。 | 把任意 awaitable自动当 ResumableBody；把每个 Suspend 都当 await expression completed。 |
| asyncgen | request 创建保持 AGEN_CREATED；await 才 delivery；一个请求 item 完成、同一 body 仍 suspended，后续 request继续。 | request complete即 body finish；asend(nonNone) created 被当为有效 ingress；aclose yield后伪造 close success。 |
| cancellation | Task.cancel request、实际 CancelledError delivery、catch/suppress、Task最终状态分别对应原记录。 | cancel request 即 body throw/closed/task.cancelled。 |
| execution generation | 同一静态 suspension loop 两次动态 occurrence严格配对；另一次驱动不可重复消费旧 generation；delegate-only可以无 parent ingress。 | 仅按 OperationID / call count / thread / same type 合并 instances；缺 occurrence 直接当无 body work。 |

## 不在本轮宣称完成

- 还没有由 AST/source family lowering 生成完整通用 body driver；也没有自动把 CPython/asyncio
  的 method/bytecode 证据变成上述静态连接。
- 没有完整 native method/generator/coroutine/asyncgen/Task 动态采集，未证明 request、object、
  drive epoch、activation、segment、outcome 的真实关联或无漏事件。
- 没有完整 delegate/awaitable/native adapter 与 event-loop finalizer 证据；opaque envelope只能
  保留未知，不等于内部 understood。
- 没有证明任何 M2 compile/source closure、M4 runtime correspondence 或变换资格；C2/D3、完整
  第一阶段、whole-program automatic recovery 和 LeWM 优化仍 OPEN。

## 可核验一手资料

- [Python 3.14 Expressions: yield, generator methods, async generators, await](https://docs.python.org/3.14/reference/expressions.html)（在线当前 3.14.8）。
- [Python 3.14 asyncio Tasks: task cancellation](https://docs.python.org/3.14/library/asyncio-task.html)（在线当前 3.14.8）。
- [CPython `Objects/genobject.c`, tag `v3.14.7`](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c)：generator throw/close/send、exception normalization、asyncgen request implementation。
- [CPython `Python/ceval.c`, tag `v3.14.7`](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c)：frame/generator return 与异常状态切换；版本实现证据，不泛化为其他 Python implementation。
- [PEP 380](https://peps.python.org/pep-0380/), [PEP 479](https://peps.python.org/pep-0479/), [PEP 492](https://peps.python.org/pep-0492/), [PEP 525](https://peps.python.org/pep-0525/)：委托、StopIteration 转换、native coroutine/await、async generator 的设计合同。

