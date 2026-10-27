# C2：可恢复函数的接口审查

状态：只读语言/工具审查；未改产品、测试、共享文档或 LeWM。工作树记录的当前 HEAD：fec9f5b426caad5e0c974c9bd99c42a0fb256882。结论供接口设计使用，不代表 M1/M2 完成。

## 结论

generator、coroutine、async generator 不是“普通函数多一个暂停边”。创建、开始、每次恢复、每次挂起、终止和关闭分别发生；同一静态 body 可跨多次动态 activation/resume。适合的最小模型是：保留同一个 body/CFG，在同一 Region 内表示真实控制后继，并把挂起点连接到独立的、带类型的额外 availability/resume roots。挂起和恢复之间是 temporal successor 关系，不能冒充同一次 CFG 执行里的普通分支或 Return。

每个动态 continuation instance 需要按实际创建对象和 generation 识别。frame-private 值在暂停时保留；共享 world、共享 cell 和引用对象的内容在每次恢复时从当时的 state 读取。恢复请求、被调度的 awaitable、yield/await 的对外结果、body 的终止 completion，以及 task 取消必须各有自己的类型/连接。它们不能压成一个 NORMAL / Return token。

这与 WHOLE_PROGRAM_MODEL.md §5.3 的 owner/site/protocol/saved-frame/generation 方向一致。建议本轮只冻结这些关系和准入条件，暂不增加 enum、wire 字段或产品记录。

## 证据范围

所有本机见证在 CPython 3.14.7、conda 环境 lewm，以标准库小脚本运行；没有导入 SCAR、PyTorch，也没有保留 frame、locals 或目标对象。

本次有 4 个脚本、23 个动态命名观察组（runtime 15、delegation 3、exception-context 5）及 4 个静态 code-shape 记录。它们是观察记录，不是断言式测试套件；没有意外未捕获错误，专门测试失败的 close 以记录的 RuntimeError 表示。此前控制分册的 17 组探针不在本轮重跑范围内。

- language-runtime-probe.py / .json：15 组；包括 shared dict 改写、close 失败仍 suspended、asyncgen 请求创建与驱动分离。脚本 SHA-256：f413c4718333c629c84cdbe57a071148c5c679eb0ffc903847d804919ec74266。
- language-delegation-probe.py / .json：3 组；throw 有/无委托方法、close 转发与子/父 finally。脚本 SHA-256：5479bd0b711b859492803689696730897a692cd753e54b6b28bf3d5859f52803。
- language-exception-context-probe.py / .json：5 组；每组有多次恢复或嵌套 caller 检查。脚本 SHA-256：b939847a945b1d5d1c4eac69a01f5c7d49e113655b0eff5c6a5c040bbe4c37a2。
- language-bytecode-probe.py / .json：4 种 code：generator、yield-from、coroutine/await、async generator。脚本 SHA-256：93af8789e2523a86d8b6b70de5adedb3f9b7be31b902d2f768e99ac79ab61869。

四个 JSON 是各脚本实际输出；JSON SHA-256 分别为 runtime 3a7c543e62d2b1d710717ec7291e6517827e0a2938b024bc7f71afd4708fb8f7、delegation 98d81a011cd26a38e3fca9d5d0563f3a64930dba6cf59f360642fbc79ef66dfa、exception 08ad741a3d15a831e6a10a6c33cb5fc0baf5c9fce74bab655a44f7ae5b19d071、bytecode 55676c0e5cbf3970576a7d05cd5949854332db4c8f8bc96748745ef2657eca6d。下面区分本机直接观察、语言文档事实和接口推导。在线 Python 文档目前显示 3.14.8，本机为 3.14.7，文档版本差异必须保留。

## 观察结果

### 创建、驱动、挂起、关闭

- 调用 generator function 后得到 GEN_CREATED，body 尚未执行；关闭一个从未启动的 generator 不运行其 body 或 finally。
- 第一次 next 进入 body，yield 的对象是这次 next 的结果。send(v) 将 v 作为暂停的 yield expression 的值继续执行；最后的 Return(v) 由 StopIteration.value 承载，generator 进入 GEN_CLOSED。yield 与 body Return 是不同结果。
- 本次 yield-from 见证里，父调用者收到 child yield；父 send 被转给 child；child Return(value) 成为父端 yield-from expression 的值；随后父 Return 又单独成为父的 StopIteration.value。
- 本地 shared-dict 见证在两次 next/send 之间改了 dict 内容。暂停前第一次 yield 读到 before-resume；恢复后第二次读取看到 changed-between-resumes。应该保留 cell/对象引用和可变 state 的连接，不能冻结一次 yield 时的内容。
- generator 在 finally 中再次 yield，close 抛 RuntimeError；该实例在错误后仍为 GEN_SUSPENDED。随后再调用 close 才完成关闭。失败的 close 不等价于已经 Closed。
- coroutine 创建后是 CORO_CREATED，body 未运行；手动驱动到 await 的 scheduler-token 后为 CORO_SUSPENDED；恢复值成为 await expression 的结果，coroutine 最终 Return 由 StopIteration.value 传出。
- async-generator.asend(None) 返回 async_generator_asend request，但 request 创建时 body 仍未运行、generator 仍 AGEN_CREATED。await request 才运行 body并让 item 成为该 awaitable 的 StopIteration.value。aclose() 同样先创建 request；实际 await 才运行 finally 并关闭 async generator。
- asyncio Task.cancel 是取消请求而非自动终止。见证 coroutine 捕获 CancelledError 后正常返回；task.cancelled() 为 false，而 cancelling() 仍为 1。

### 恢复时的异常上下文与 pending completion

异常见证在两个不同 caller 的 except 中驱动同一个 generator；观察的是 sys.exception() 的类型和对象身份，caller 恢复后仍看到自己原来的活动异常。

- generator 没有本地活动 handler 时，其空异常状态沿当前 resumer 的异常上下文继承：分别在 ValueError、LookupError、IndexError caller 中恢复，generator 分别观察到当前 caller 的异常。它不是“保存了 None”。每次恢复都要提供当次 caller context。
- generator 自己捕获 KeyError 并跨 yield 暂停，下一 caller 即使处在 ValueError/OSError 中，generator 仍观察到同一个本地 KeyError；恢复结束后各 caller 的异常上下文得到恢复。
- generator 的本地 handler 清除后再次 yield，会重新观察到当前 caller 的 RuntimeError。这说明“继承 resumer”与“保存本地活动异常”是不同状态。
- pending KeyError 在 finally 内 yield 时保留为待传播异常，恢复后仍传播同一异常对象。
- pending Return 也可与继承来的活动异常同时存在：finally 中的 yield 观察到 ArithmeticError，但生成器仍完成原有 body-return。Pending completion 不能与当前活动的 handled-exception context 合并。

设计上，异常上下文至少需要可区别的 overlay：INHERIT_RESUMER_CONTEXT 与 SAVED_ACTIVE_CONTEXT(exception reference / handler stack)。后者必须能表示 generator 自身 handler 的保存状态。具体 Python handler 规则由 control/cleanup 模型负责；C2 不能把空槽降格为无异常，也不能让 pending Return/Raise 覆盖/代替当前 handled context。

### 委托和静态 code 形状

CPython 3.14.7 的小型 dis 记录显示四种 callable 的 code flags 可分类 generator、coroutine 与 async generator，并出现 RETURN_GENERATOR、GET_AWAITABLE、SEND、YIELD_VALUE、RESUME 等指令。它们只提供静态 offsets/opcode，不提供动态 instance、generation、调度请求或实际 delegate 绑定。RESUME operand 是解释器版本相关信息，不能按一个固定的 3.14 数字泛化。

yield-from 的直接见证显示：

- delegate 支持 throw 时，父 throw 请求转交 child；child 可 yield 并最终正常返回，StopIteration.value 成为父表达式值。
- delegate 缺少 throw 时，原异常进入父生成器，可被父 handler 捕获。
- 父 close 转给 child.close，之后 parent/child 的 finally 都执行。

这支持显式 DelegateActivation / iterator protocol 关系，但不能仅凭静态 yield-from 语法断言运行时动态目标、方法存在、调用成功或返回值来源。

## 推荐的最小接口分层

以下是接口提案，不是已有实现或已验证字段。命名只为说明职责，等 owner 冻结 wire 前不得把它们当作稳定 API。

### 1. 静态 body 与 temporal resume roots

- 一个 resumable body 仍引用一个 code definition、function kind、environment/formal layout 和单一 body Region。
- 静态 SuspensionSite 指向实际 yield/await/yield-from operation，声明 outgoing payload/scheduler-value port、保存的 frame layout、相应 resume availability root，以及可选 delegate interface。静态 site 本身不代表每次动态经过；loop 可多次命中同一 site。
- Region 的正常 entry 表示首次 body activation。每个 resume site 可以提供额外的、类型化 availability roots；它们是其它 activation 能从哪些参数开始的声明，不是普通 CFG predecessor，也不让 header 值无来源。
- 保留 body 内的普通 CFG / CFG completion 校验；另验证 temporal successor 与 availability root 配对、saved-slot 类型、传入的 sent/throw/close protocol、状态域入口。禁止用 yield→resume 普通 branch 来暗示同一次 activation 中可以沿边无限重复。
- suspension 不是函数 NORMAL/RAISE exit，也不是 iterator terminal completion。每种 drive 的 host result 与 body outcome 分开。
- 静态 liveness 决定哪些局部 binding、临时引用、evaluation-stack slot、handler/cleanup stack 与 pending completion 在该 site 要保存；这里不复制共享 state versions。恢复时要以本次新入口 world/state 重新读取 globals、cells、locations 和可变对象内容。

### 2. 动态 continuation 和请求

只有实际采集/受信任的 driver 事件才能填动态记录。可考虑 typed relation：

- ContinuationInstance：实际 resumable 对象身份、所属 function/code/environment identity、kind、创建 evidence。创建记录本身不表示 body 已进入。
- DriveRequest：instance + request kind + request occurrence + 参数引用/exception packet + caller/task/thread/context evidence。sync Next/Send/Throw/Close；coroutine Send/Throw/Close 与 scheduler drive；async-generator Anext/Asend/Athrow/Aclose request object 和对它的 await drive 应分别记录。Task cancellation 是对 task/coroutine 的请求，不是 body 已取消的证明。
- ResumeOccurrence：一次真实进入，同一 instance + 上一 suspension generation（首次启动可为空）+ request + 本次 world/state + resumer exception-context overlay。
- SuspensionOccurrence：对应 ResumeOccurrence、静态 site、generation、实际 yield/scheduler payload、更新后的 frame-private state。
- BodyTerminalOccurrence：Return / Raise / natural exhaustion / closed / protocol failure，以及对应 host adapter。每个 suspension generation 最多成功 drive 一次，Running 时重复/并发进入要得到具体重入/并发结果，不能复制 continuation。
- Frame 记录只能是规定范围的 metadata/引用见证。不能把 Python frame、locals dict 或任意 application object 藏进 snapshot 来声称可重放。

### 3. 请求、body 完成与外层 iterator/task 适配器

应至少分开建模这些边界：

- 普通 generator body Return(v) → StopIteration.value；body 自己逃出的 StopIteration 按 PEP 479 规则转 RuntimeError，不可只按异常类名算自然结束。
- iterator exhaustion 是驱动协议的 terminal signal，不是 body 的普通 Return value。async generator 的 yield item → 当前 anext/asend awaitable 成功结果；自然结束 → StopAsyncIteration。async-generator body 不允许非空 return。
- coroutine body Return(v) → coroutine iterator 的 StopIteration.value → Await expression result。中间 yield 是 scheduler hand-off，不是 Await expression result。
- close/GeneratorExit、throw、请求验证失败、close 中非法 yield 和最终 Closed 状态均保留独立 outcome；不能在收到 close 请求时预先标 Closed。
- yield-from adapter 要以实际 delegate iterator 和可调用方法为依据；throw 可转给 delegate，也可能进入父 body；child completion value 与 parent completion value 不可混。
- task cancel 的异常注入、coroutine 捕获/抑制及最终 task state 必须分别关联；不能因 task 收到 cancel 就删除后续 body/return。

## 从现有工具复用什么

| 工具 | 可复用的事实 | 不能据此推出 |
| --- | --- | --- |
| inspect | callable/code flags、generator/coroutine/asyncgen 的当前状态、frame/await/yield-from 属性；可做诊断与活性快照。 | 状态历史、instance 的创建/请求配对、可复制的 frame、下一次一定返回/结束。inspect 状态由当时 running/suspended/frame 状态派生；不要长期持有 frame/locals。 |
| dis | code 对象的版本绑定指令与 offsets，用于构造静态 suspension site 和 source witness。 | 一次循环命中次数、动态 yield 值、发送值、请求种类、外部 scheduler、异常 handler 当前身份。必须按精确 Python/bytecode 规则解码，unknown opcode 拒绝正例。 |
| sys.monitoring | 低层 PY_START、PY_RESUME、PY_THROW、PY_YIELD、PY_RETURN、PY_UNWIND、STOP_ITERATION 等可协助标记 entry/suspend/exit site；PY_RESUME 不覆盖 throw，必须另处理 PY_THROW；Python 3.12+ 的 StopIteration 可能需 STOP_ITERATION event，而不一定有真实异常抛出。 | generator 对象/request/asyncio task identity 的完整关联、任意操作数或 live frame 可重建性、工具安装期间从未漏事件。需有 scoped hooks、hook ownership/interference 检测和完整事件窗口；事件少不能推导“没有发生”。 |
| torch.fx（官方 stable 文档当前标 2.14） | 通过 Proxy symbolic trace 生成 placeholder/get_attr/call_function/call_module/call_method/output 节点，args/kwargs 保留结构；可作为纯 tensor/operator 子图 provider。 | 动态 data-dependent Python control flow；完整函数环境、generator frame、task/scheduler、任意 Python state/exception/cleanup。trace 可能执行一部分 Python。 |
| torch.export（官方 stable 文档当前标 2.14） | AOT tensor graph、graph signature 与 lifted parameters/buffers；可将明确限定的 tensor 子图作为外部 provider 结果。 | 普通 Python continuation、task cancel、yield-from/await delegation。run_decompositions 可把 alias/mutation 变换为更函数式表示，需区分原图/变换图与授权。 |

不能把 FX/Export 结果回写为 Python 全程序来源、调用或 alias 事实；provider signature 只表示 provider 声明的 tensor 图边界。

## 验收提案

下列是下一门建议的必要正反例，不是本报告已执行的测试：

1. generator create 不产生 body-entry；first next 启动；yield value 与 send-expression result 与最终 Return 各有不同端口。
2. 两次恢复之间改 shared dict/cell；第二次 read 看到新内容，拒绝 frozen-old-world。
3. 将同一静态 yield site 通过 loop 命中两次：两个 dynamic generations，禁止重复消费旧 generation 或同次 activation 直接走 temporal edge。
4. 初始 non-None send、闭合、closed 再恢复、running reentry/concurrent resume、throw 与 close 后状态；每种不能伪造 body entry 或 terminal outcome。
5. finally 中 close 时 yield → RuntimeError，实例保持 suspended；另测正常 close 和 finally exception 覆盖。
6. yield-from：child send/throw/close 支持与缺失分支、child StopIteration.value 到 parent expression、parent Return 分离。
7. async def create 不执行；await driver 产生 scheduler request；恢复值到 await expression；正常 completion 值到 caller。
8. asyncgen anext/asend/athrow/aclose 请求 object 创建与实际 await 驱动分离；yield item、StopAsyncIteration、非空 return、aclose 错误后状态分离。
9. Task cancel 作为请求，CancelledError 可被 suppress；Task 是否取消依实际终态，不由 cancel request 决定。
10. 本地 active handler 跨 yield 与 caller context 每次恢复切换；空 frame exception slot 继承当前 caller，pending Return 与活动 caller exception 可并存。
11. delegate/iterator 在两次 resume 间变化、delegate 缺 method、callback mutation 和事件缺失都只降低证据状态，不默认安全/纯。
12. 静态 bytecode/source 与动态 events 完整相符；错 offset/opcode、缺 PY_THROW/STOP_ITERATION、hook ownership/mask 变化均拒绝 positive link。

## 未验证项与边界

- 本轮新 runtime probe 共有 15 个命名观察项；delegation 3 项；exception context 5 项；bytecode 4 种静态样例。没有重跑先前的 17 组探针，也没有穷举所有请求×状态、异步取消、重入和多线程组合。
- 本轮未探 async-generator athrow、未测 GC/finalizer 的异步关闭，也未覆盖任意 event loop、native scheduler、线程切换和 tracing/profile hook 对抗。现有分册中的部分验证是此前见证，不应跟本轮新运行混为一谈。
- 没有真实目标 trace/LeWM 证据；未证明实际模型现在能 lower、捕获或查询这些 continuation。
- 官方链接如下。文档网页显示的 3.14 patch 版本可能领先本机 3.14.7；适用性需固定版本并用本机 probe 复核：
  - Python expressions / generator & await protocols: https://docs.python.org/3.14/reference/expressions.html
  - Python data model / coroutine methods: https://docs.python.org/3.14/reference/datamodel.html
  - inspect: https://docs.python.org/3.14/library/inspect.html
  - dis: https://docs.python.org/3.14/library/dis.html
  - sys.monitoring: https://docs.python.org/3.14/library/sys.monitoring.html
  - asyncio task cancellation: https://docs.python.org/3.14/library/asyncio-task.html
  - PyTorch FX: https://docs.pytorch.org/docs/stable/fx.html
  - PyTorch Export: https://docs.pytorch.org/docs/stable/export.html

## 归档命令和文件哈希

环境未安装/升级包。更新 runtime 结果的实际命令：

    source /home/zyf/miniconda3/etc/profile.d/conda.sh
    conda activate lewm
    PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_resume_interfaces/review/language-runtime-probe.py

结果版本：CPython 3.14.7；产生时间 2026-10-17T23:31:25.836012+00:00；runtime-probe 15 observations，异常见证 5，delegation 3，bytecode 4 code shape；未捕获 probe failure = 0（close 的预期 RuntimeError 已捕获并记录）。

以 sha256sum 对脚本、JSON、本报告本身复核；报告中的路径相对当前 worktree。未改 tracked 文件。
