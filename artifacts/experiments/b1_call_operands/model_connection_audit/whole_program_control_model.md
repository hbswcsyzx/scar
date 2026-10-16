# 完整程序的控制、完成与就绪模型

日期：2026-10-16。状态：**Proposed；独立模型审查，不是实现或自动建图验收。**

只读基线：`/tmp/scar-structured-model-280qf4mi`，提交
`dcd498699e0cd1331cf496158b29575c3fc2c536`；本次核对时工作树 clean。
没有运行 LeWM、全仓测试或新分析，也没有修改冻结产品、测试、gate 或 docs。
下文代码是模型反例说明，没有执行。

## 1. 确定建议

统一的是**有类型的端口、continuation 和状态传递规则**，不是一个可以到处替代的
“完成 token”。必须保留三组不同的接口：

1. **语言控制结果**：fallthrough、return、raise、break、continue，以及与这些
   最终完成不同的 suspension。`finally/with` 必须能携带、保留、替换或抑制待完成动作。
2. **一次 host 调用的结果**：返回或抛出，绑定到这次 call attempt；它不能证明函数体
   已进入、生成器已执行、callback 已完成，或 GPU 工作已完成。
3. **资源工作的进展**：issued、完成/失败/取消及针对具体消费域的 readiness。
   资源工作可以晚于 host return 完成，也可能永不完成。

程序图的 `Operation / Value / StateLocation / Region` 可以继续作为 control/data
投影的四个结构家族，但不能代表完整 ProgramModel 的全部实体。
**完整 ProgramModel 应显式包含 ResourceDefinition 与 ResourceRequirement**；
Execution 层再将其对应到 ResourceInstance。资源身份不等于 Python handle、不等于
资源的状态版本，也不等于某次操作。此项修正了早先 `end_to_end_type_review.md`
中容易将资源完全推迟到 Execution 层的表述；旧报告作为历史审查保留。

本方案不增加 backend，不按函数名或 LeWM 名称决定协议，不提供变换权限。

## 2. 最小实体与规范类型

以下是建议的**类型合同**，不是已落地的 Python API。名称可以在实现时统一；
这些区分和字段不能用 label 或自由 metadata 替代。

### 2.1 身份与实体

| 实体/身份 | 最少含义与合法连接 |
| --- | --- |
| `OperationID` / `RegionID` / `ValueID` / `StateLocationID` | 复用静态定义身份；静态 Value 的一次定义不等于某次执行的对象、迭代或事件。 |
| `ControlPortID` | `(owner RegionID, local port identity)`；端口声明协议、payload 类型、状态域和目标作用域。名字不是协议。 |
| `ControlTarget` | 强类型联合：`ReturnBoundary(RegionID)`、`LoopBreak(LoopID)`、`LoopContinue(LoopID)`、`Fallthrough(ControlPortID)`。不得将内层 loop、外层 loop 或另一调用的返回目标互换。 |
| `InvocationKey` / `AttemptKey` / `ResumeOccurrenceKey` | Execution 层的动态身份，至少隔离 trace scope、process、thread/task 与 occurrence；静态图不伪造这些事实。 |
| `ResourceDefinitionID` | ProgramModel 中的资源身份，允许程序进入前已存在、由操作创建，或由未执行分支选择。多个状态域、allocation、materialization、同步端口可共同引用它。 |
| `ResourceRequirementID` | 对资源种类、选择条件、能力或容量的约束；不是一个已经存在或已满足的 ResourceInstance。 |
| `ResourceInstanceID` | Execution 层实际资源及生命周期 generation；通过有证据的 realization 边连接 definition/requirement。两个 Python 包装对象可以指向同一资源。 |

支持 Resource 一等身份的反例：一个 stream 被多个 allocation 的生命周期与多个
work ticket 引用，它在任何单次 enqueue 之前就存在；stream 的队列状态改变，身份
不变。文件路径是值，open handle 是对象，底层文件/输出端点是资源，文件内容与
offset 是状态。把这四者合成一个引用会错误合并或拆散依赖。

反对增加 ProgramGraph 顶层 kind 的合理理由，仅限于该 graph 明确是 control/data
投影，且它的类型和端口引用 ProgramModel 的规范资源表。这样没有消除 Resource
实体，只是没有把所有实体强迫放在同一节点数组。不能以“四”或“五”为设计目标。

### 2.2 语言控制类型

```text
LanguageCompletion =
    Fallthrough(target: Fallthrough)
  | Return(target: ReturnBoundary, payload: Reference)
  | Raise(packet: ExceptionPacket)
  | Break(target: LoopBreak)
  | Continue(target: LoopContinue)

LanguageOutcome =
    Complete(LanguageCompletion)
  | Suspend(site: SuspensionSiteID,
            protocol: GeneratorYield | AwaitSuspension,
            exported_payload: protocol-specific value,
            continuation: ContinuationHandle)
```

`Suspend` 不是“函数已经 return”，也不是下一条普通 CFG edge。它保存恢复位置和
frame 私有状态，当前调用协议可据此产生 host return；之后可能恢复原函数。
`Return` 的 payload 是已经求值的引用，cleanup 可以改变它所指对象的内容。
没有完成边不等于已证明 divergence；不存在的观察也不能补成 `Normal`。

需要跨 cleanup 或 suspension 保存时，将 completion 物化为强类型
`PendingCompletionValue(id, region, origin, CompletionType)`。
`CompletionPack` 的规范 variant record 只引用 producer Operation 自己的 payload
`UseID` 和上述 typed target；`CompletionUnpack/Dispatch` 只在合法匹配边上产生
对应 payload。普通局部 jump 不必为此创建通用 token。合流保留 variant，不能把
不同 Return/Break 合流成无目标的 NORMAL。

`ContinuationHandle` 的静态类型至少含 `owner RegionID`、`SuspensionSiteID`、
`ResumeProtocol` 和 `SavedFrameInterfaceID`；执行实例另带 generator/task identity 与
suspension generation。`SavedFrameInterface` 按序声明 local-binding slots、求值栈中
仍存活的引用、held temporaries、handler/cleanup stack，以及存在时的 pending
completion。保存/恢复操作的规范 Uses 才给出具体值；这张接口表不复制其 producer
或 state version。它不承诺物理 frame 快照，也不是 Python 可随意复制的 continuation。

`ExceptionPacket` 至少关联异常对象引用、传播 traceback、cause/context 与
suppression 的相关状态，以及当前 handler 的异常上下文。对象内容仍由 StateVersion
表示；packet 不能复制一套独立可改的异常属性事实。bare raise 读取当前 handler
上下文；它不是“重新 raise 最近见到的对象”。exception group 需要有类型的
split/merge 规则，不能把 `except*` 当普通首个匹配 handler；完整模型应保留这一接口，
尚未实现时明确为协议边界。

### 2.3 host 与资源类型

```text
HostOutcome(call site; dynamic occurrence supplied by Execution) =
    Returned(payload interface)
  | Threw(ExceptionPacket)

WorkTicketType =
    (producer operation, resource definition/requirement, work generation,
     affected content/materialization obligations)

ResourceOutcome(ticket) =
    Completed
  | Failed(error/diagnostic interface)
  | Cancelled(protocol-specific completion)

ReadyTokenType =
    (ticket/generation, content or materialization version,
     consumer visibility domain, readiness kind)
```

`Issued` 是成功提交后的状态，不是一个终态。`Cancelled` 不普遍意味着工作从未执行、
没有部分输出或可以马上 free。协议不支持取消时，不凭空添加成功取消边。
`ReadyToken` 不能靠任意 bool、时间戳、host return 或相同引用构造；它来自规范同步
规则或具体完成证据，包含足够的生产者和可见性范围。

三个协议可共用端口/SSA 编码机制，**不能共用一个无区分 token 类型**。
PendingCompletion 是单一活动控制路径的状态；同一 suspension generation 的
continuation 只能被一次合法恢复转移消费（允许 CFG 上互斥分支，禁止动态复制执行）。
Ready 证据通常可被多个消费者使用，不能误套 continuation 的一次性约束。

### 2.4 状态与入口

每条边的规范状态参数统一引用当前 `StateVersionValue(location)`，不在 frame、
completion overlay 或 resource records 再保存另一套 before/after world。

至少区分以下 owner/domain：frame 私有绑定与保留引用；函数环境中的 globals、
defaults、kwdefaults、cell identity/content；handler/execution context；共享对象内容；
资源协议/队列/生命周期。它们仍是 StateLocation 的不同类型和归属，不是每种状态
新增一个顶层节点家族。精细域与 coarse world 之间必须声明覆盖/可能别名关系：
**两个 location ID 不同，不构成互不干扰的证据。**

恢复入口尤其需要两个来源：保存的 frame-private 状态，以及恢复当下的共享状态。
caller 或 callback 可以在两次 `next/send` 之间修改共享对象/cell/globals；不可把
yield 时的 coarse world 作为 resume 的当前世界。不能分解时，应保留保守的共享状态
交接/干预依赖，牺牲精度，不能冻结旧版本。

### 2.5 端口的最少字段

每个端口声明 `id / owner / protocol / payload signature / state-domain signature`。
`protocol` 必须是上述联合中的具体变体或一个版本化 protocol identity，不是自由
字符串。跨边只传 `UseID` 或该边定义的 `Produced(index)`；保留现有边定义结果的
可用性规则。新增 payload 类型不能塞进 `ValueType.semantic_type` 字符串绕过校验。

| 端口 | payload / 额外必需字段 |
| --- | --- |
| 普通 body entry | ordered bound-formal references、隐式 FunctionEnvironment、调用协议；state domains 单独声明。 |
| lexical completion | LanguageCompletion variant、其合法 ControlTarget 集；Raise 接对应异常 dispatch scope。 |
| cleanup entry / dispatch | pending completion Use、cleanup scope identity；输出为保留/替换后的 variant，而非新造的通用 NORMAL。 |
| resume entry | generator/task reference、typed ResumeRequest、保存 frame 的 continuation；另接当前共享状态。 |
| suspension exit | protocol-specific exported payload、continuation；不得作为最终 frame exit。 |
| host outcome | 这次调用的 Returned payload 或 Threw packet；通过 attempt/entry relation 才能接具体 body。 |
| resource issue / outcome | ResourceDefinition/Requirement、WorkTicket、具体结果类型；Execution realization 不由端口存在自动成立。 |
| consumer readiness | exact work/content generation 与 consumer domain；绑定实际消费操作，而非一个全局“ready=true”。 |

## 3. 端口与组合规则

### 3.1 普通调用与递归展开

普通同步函数体的 `Return(ref)` 经函数边界适配为这次 host `Returned(ref)`；隐式
fallthrough 先形成 Python `None` return。`Raise(packet)` 经传播规则成为 host
`Threw(packet)`。body 的 Return 不是 caller 的 Return；必须经过 caller 唯一 call
continuation。实际 target/entry 尚未确认时，只能保留候选条件边。

argument 求值、packing、dispatch、参数绑定和 body execution 是不同阶段。任一
pre-entry 失败都可以有 host Threw，不能由此创建 callee body entry 或形式参数来源。
现有 attempt/entry handshake 可复用，但默认值与 bound receiver 不能由“同一对象
引用”推成某个显式 actual。递归/重复 call 必须以 invocation occurrence 隔离。

展开或折叠 Region 时应保持：有序 actual Uses；环境和资源需求入口；所有语言/host
结果及目标；每条完成路径状态域；suspension/resume 接口；外部可观察作用和未证条件。
只保留函数输入输出数据边不足以满足这一接口。

### 3.2 for / while / break / continue

for 的 iterable 求值、取 iterator、advance、目标绑定和 body 是分开的操作。advance
返回元素与 advance 抛出的 StopIteration 分别接 item 与 natural-exit；其他异常传播。
**只对 advance 的异常应用 exhaustion 规则**，不能吞掉 body 内任意 StopIteration。
while 每次读取当前绑定/状态并重新求真；零次路径和每条回边都有完整参数。

Break/Continue 带所属 loop 目标。没有介入 cleanup 时可投影为现有 JUMP；一旦跨
finally/with，就必须先携带 pending transfer 经过 cleanup，再到目标。Break 绕过
该 loop 的 else；Continue 保留 iterator 并到下一次测试/advance。内层 loop 的 else
已经退出内层 loop 作用域，其中的 break 可以属于外层，不能只按 AST 最近父循环猜。
loop else 的可达性取决于 natural exit，不等于“body 曾正常执行”。语言边界依据
[Python 循环和 try 规则](https://docs.python.org/3.14/reference/compound_stmts.html)。

### 3.3 try / except / finally

每个 cleanup scope 有 typed `CleanupInterface`：protected Region、pending 入口、
handler/cleanup Region、合法恢复目标与状态签名。它索引 core edges，不再维护第二张
CFG。对 finally，用以下规范组合，而非声称它是普通 frame release：

| finalbody 的结果 | 组合结果 |
| --- | --- |
| Fallthrough | 继续原 pending completion，使用 finalbody 后态。 |
| Return / Raise / Break / Continue | 以新 completion 替换原 pending completion；原 payload 引用的释放/异常 context 等作用仍保留。 |
| Suspend | 保存原 pending completion、cleanup continuation 和 frame 状态；恢复后继续 finalbody。 |
| 无完成 | 不向原目标制造完成边。 |

except dispatch 只接 protected suite 的 Raise；匹配表达式和 handler 本身可以产生新的
Raise。try else 只接 protected suite 的 fallthrough，handler 的正常完成不能误进 else。
handler 退出时恢复异常上下文、清除 `as` 绑定；bare raise 必须关联正在处理的 packet。
finally 可覆盖原返回或异常，其规则有别于 frame 清理。语言 transfer 的依据见
[Python return/raise/break/continue](https://docs.python.org/3.14/reference/simple_stmts.html)。

现有 `FrameRules.PRESERVE_PENDING_IF_COMPLETED` 仅继续适用于其受限 frame 引用转移：
`NO_FRAME_INTERPOSITION` 尚未证明，finalizer 可能写共享状态、逃逸或不终止；普通
`__del__` 的 unraisable error 不能凭空替换 pending exception。`del x` 也要区分本地解绑
与属性/下标删除；后两者可能调用可抛出的用户协议。不能把所有 cleanup 都归成这种
completion-preserving frame 转移。

### 3.4 with 与抑制

`ContextManagerInterface` 明确 manager、按版本协议获得的 enter/exit callable、
enter-success 后才生效的 cleanup registration、entered payload 及 exit 的调用端口。
enter 失败不为该 manager 调用 exit；enter 后目标赋值失败须进入 exit。多个 manager
按嵌套作用域退出，后一个 enter 失败时前一个仍须清理。

| pending | exit host 结果 | 后续 |
| --- | --- | --- |
| Raise(packet) | Returned(value) 且 truth(value)=true | 抑制原异常，Fallthrough 到 with 后；保留 exit/truth 后态。 |
| Raise(packet) | Returned(value) 且 truth(value)=false | 恢复原 Raise，保留后态。 |
| Fallthrough / Return / Break / Continue | Returned(value) | 忽略 value 的抑制含义，继续原 completion；不额外调用 truth。 |
| 任意 pending | exit 或必要的 truth 抛出 | 新 Raise 替换原 pending，并保留异常上下文规则。 |

调用 `__exit__` 的 host Returned，不能直接接 with-body 的 NORMAL；上表的
completion adapter 不可省。参考规范翻译与抑制规则：[PEP 343](https://peps.python.org/pep-0343/)。
`async with` 使用相同 pending 规则，但 enter/exit 的 await 是可恢复协议，不能假装
同步函数返回即完成了 enter/exit。

## 4. Generator、callback 与环境

### 4.1 Generator 的创建和恢复

`GeneratorReference` 仍是引用；其 generator/frame 状态是 `StateLocation`，协议状态
至少为 Created / Running / Suspended / Closed。不要用 code identity 当 generator instance。

```text
ResumeRequest = Next | Send(reference) | Throw(ExceptionPacket) | Close
ResumeInput   = generator state + request + current shared state
BodyOutcome   = Suspend(yielded value, continuation) | Return(value) | Raise(packet)
```

创建 generator 时完成该调用的 argument binding、创建并保留环境；**不执行 body**。
第一次合法恢复才进入 body。Created + Send(non-None)、Running 时重入等失败由协议
端口表达，不能创建假的 body continuation。yield 保留局部/临时/handler 状态，不运行
最终 Frame EXIT；恢复时 yield expression 的结果来自 Send/Next，Throw 则在相应位置
注入异常。基本恢复机制参考 [PEP 342](https://peps.python.org/pep-0342/)。

需要显式 `GeneratorBoundaryAdapter`：

| body / protocol 结果 | next/send/throw 的 host 结果 |
| --- | --- |
| Yield(value) | Returned(value)，generator 保持 Suspended。 |
| Return(value) | Threw(StopIteration carrying value)，generator 完成。 |
| 其他未处理异常 | Threw(packet)，并按协议关闭/保留相应状态。 |

`Close` 是独立请求：注入 GeneratorExit；close 中再 yield 会失败。不能把这类失败的
generator 状态统一写为 Closed，必须依据实际协议后态。Python 3.13 起，关闭时函数
返回的值可以成为 close 的返回值，因此协议须绑定编译/运行版本；不能硬编码 close
总是 None。已关闭/尚未开始的对象也有不同路径。依据
[Python generator 方法](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)。

函数自然 Return 引发的 iteration completion 与 body 非法逃出的 StopIteration
不同，后者需要 PEP 479 的 RuntimeError 转换。不能通过异常类名合并。
[PEP 479](https://peps.python.org/pep-0479/)

`yield from` 需要 delegation interface 将 Next/Send/Throw/Close 与子 iterator 和返回值
对应，不能当一次 opaque call。coroutine 与 async generator 可共用 continuation
机制，但必须用各自协议适配：awaitable 创建、实际 await、task cancellation 注入、
async iteration 的终止信号都独立。scheduler cancellation 不是 GPU work cancelled
的自动证据。未实现这些适配时，模型应保留明确协议边界，不能报告完整控制覆盖。

### 4.2 Callback 与 closure

callback 不是新的语言 completion kind。同步 callback 使用普通调用协议；异步注册
则先写注册/队列状态，后续 dispatch 独立产生实际 invocation。注册返回不证明 callback
执行过、只执行一次或在同线程执行，也不能替代 callback completion。

body 入口需一个有类型的隐式 `FunctionEnvironment` 引用，它不是 Python formal。
其绑定包含 FunctionObject 实例、code definition、globals/defaults/kwdefaults 及
有身份的 captured cells；各可变内容读取当前 StateVersion。一个 cell 可被多个
function 共享；同一 code 的两个 function 可以具有不同环境。closure cell 不可弱引用
是采集策略限制，不能在抽象模型中删除 cell identity 或按内容相等合并。

同步 callback 的 Return 回到实际 invoker 的 call continuation；被注册函数在退出其
词法定义 frame 后仍可持有环境。callback 可重入，不能以静态源码嵌套表达所有动态父子。
进入实际 body 前必须保留目标/环境/参数路由的未证条件，当前引用观察不自动证明这些。

## 5. CPU/GPU enqueue、ready 与 wait

ProgramModel 可以在未执行分支表达资源选择和同步约束。例如 device 分支选择某个
ResourceDefinition 或 Requirement，enqueue 依赖其 queue state 并产生 work ticket；
Execution 层才记录实际 device/stream/work occurrence。Program 不能只留下观测到的分支。

```text
host call returned ──> work issued / returned handle
                               │
resource execution ────────────┴──> completed/failed
                                      │
                              visibility adapter
                                      │
                           Ready(version, consumer domain)
```

这不是“ready 才能提交任何后续 GPU 操作”：后续 enqueue 可提前发生，但其**资源执行**
必须有 producer 完成到 consumer 开始的 ordering/readiness obligation。普通 host 内容
读取则须在读取前满足相应可见性。将这两种消费统一成 host 等待会错误串行化程序。

| 操作 | 必需结果/依赖；不得推导的事实 |
| --- | --- |
| CPU 同步计算 | 由具体同步协议将执行完成接到 host Returned；未知 callable 无此保证。 |
| CPU worker / GPU enqueue | 读取输入/版本与资源队列状态，返回 handle/ticket、提交后态；不保证内容已就绪。 |
| stream/queue wait | 为后续资源工作增加依赖；host 可以立即返回，不产生 host-visible Ready。 |
| host blocking wait | 成功完成时产出其合同范围内的 Ready/可见状态；超时、失败、取消等结果单独建模。 |
| memory lifetime tracking | 约束 allocation generation 的复用/释放；不能替代内容 readiness。 |
| encoder close / file flush | 按实际协议表达已完成、部分输出或失败；不从方法名称推断进程退出、持久化或成功输出。 |

同 stream 的顺序不能扩展为所有 stream 的顺序，异步错误也可能晚于 enqueue 返回才
被观察。这个区分来自 [PyTorch CUDA/stream 协议](https://docs.pytorch.org/docs/main/notes/cuda.html#asynchronous-execution)。
allocator 生命周期与内容同步分开，见
[Tensor.record_stream](https://docs.pytorch.org/docs/main/generated/torch.Tensor.record_stream.html)。

Frame EXIT/引用解绑不等于资源 free；未完成工作可以继续引用 storage。`Ready` 绑定
内容/物化版本及 allocation generation，不能套到之后重用同一地址的对象。Resource
的容量、队列、open/closed 等仍是状态，资源本身保持独立身份。

## 6. 必须由 validator / composition 检查的不变量

1. **协议不混用**：LanguageCompletion、HostOutcome、ResourceOutcome/Ready 的端口
   不能直接互接；只有声明了输入/输出及规则的 adapter 可以转换。
2. **目标和动态身份正确**：Return/Break/Continue 的静态作用域正确；Execution 中
   另核验具体 invocation/resume generation，不能把同 code 的另一次调用当目标。
3. **路径可用性**：payload 只在其产生边可用；异常路径不能读正常结果。不同完成
   variant 合流时保持 variant，不能借 phi 抹掉目标或类型。
4. **状态连续且不复制权威**：每条完成/恢复边的声明状态域齐全；cleanup 输出后态，
   不回退到 before。state facts 仅由 core Uses/definitions 给出，overlay 只索引规则。
5. **cleanup 注册与顺序**：只清理已成功进入的 scope，按作用域次序执行；pending
   replacement 要保留被丢弃 payload、异常上下文和可能 finalizer 的依赖。
6. **悬停不是释放**：yield 不作最终 EXIT；恢复使用保存 frame + 当前共享状态；
   同一 generation 不可同时 Running 两次。frame 逃逸/traceback 保留不伪装立即 free。
7. **别名与环境保守**：cell/world、资源/heap、handle/resource 的未解关系不能按 ID
   不同宣布 disjoint；同对象 actual 的不同 Use occurrence 也不能因此合并来源。
8. **资源完成范围**：正确 ticket、资源实例、generation、版本及 visibility domain
   才能满足消费；stream wait 的 host return 不能代替 Ready。
9. **非终止/外部干预**：未发生完成不能造假退出；interposition、并发干预、强制进程
   终止等未覆盖范围保留显式边界。`NO_FRAME_INTERPOSITION` 不因完整控制类型而变 VERIFIED。
10. **递归展开保持边界**：展开前后必须保留所有 completion、suspend、环境、状态、
    资源与 observable ports。未知 subtree 内部 call 不能计入已建图数量。

## 7. 五个击穿简化模型的反例

### 反例 1：finally 改写 return，并改变 loop else 的选择

```python
def choose(xs):
    for x in xs:
        try:
            return x
        finally:
            break
    else:
        return "empty"
    return "broke"
```

预期：空输入走 `empty`；有元素时 pending Return 被 Break 替换，绕过 else，走
`broke`。不能把 finally 接在已完成 RETURN 后，也不能将 break 记成无目标 NORMAL。
变体 `try: raise e; finally: return x` 必须覆盖原异常；嵌套 loop else 的 break 必须
按作用域归外层。Python 版本可能对此发 SyntaxWarning，编译条件应保留，不改变模型结果。

### 反例 2：with 抑制异常，但不抑制 return

```python
def use(cm, fail, x):
    with cm:
        if fail:
            raise ValueError("body")
        return x
    return "after"
```

cm.exit 正常返回 truthy 时：异常分支变为 `after`，return 分支仍返回 x。exit 返回
对象的 truth 求值只发生在异常分支，且可产生新异常；enter 失败不调用该 exit。
一个 NORMAL/RAISE 标签无法同时表示这些 body completion 和 exit host result。

### 反例 3：generator 的创建、yield、返回和共享状态不是一次调用

```python
def gen(log, box):
    log.append("entered")
    try:
        received = yield box
        box.append(received)
        return box
    finally:
        log.append("cleanup")
```

`g = gen(log, box)` 不执行 append；`next(g)` 返回 box 引用但没有结束 frame。
caller 可在暂停时修改 box，下一次 send 必须读修改后的内容；最终返回经
StopIteration.value 传出。throw/close 走恢复位置的异常/cleanup，close before first
entry 不应伪造 body 执行。缺少独立 continuation 或沿用 yield 时 world 均会错。

### 反例 4：同 code 不同环境、同 cell 多函数、callback 晚于注册

```python
def make():
    current = []
    def get():
        return current
    def put(value):
        nonlocal current
        current = value
    return get, put

get_a, put_a = make()
get_b, put_b = make()
register(get_a)
put_a(shared)
# callback 随后实际被 dispatch；register 的返回不是 dispatch 的完成。
```

get_a/get_b 可以共享 code，不能共享 cell identity；get_a/put_a 必须共享一个 cell
状态。dispatch 时 get_a 读新状态。不能从词法包含、函数名、注册返回或对象相等直接
接出实际结果。callback 次数/线程未知时保留条件，不给 callee/effects 权限。

### 反例 5：enqueue return、stream 顺序、内存生命周期相互独立

```text
write_ref, ticket = enqueue_write(stream_a, storage_generation_1)
enqueue_read(stream_b, write_ref)
```

第二行 host 顺序晚，不证明 stream_b 执行时可读。补 `stream_b.wait(ticket)` 可以
建立资源顺序，但它的 host return 仍不是 CPU 内容可读证明。之后同一地址用于
generation_2，也不能继承 generation_1 的 Ready。生命周期 tracking 不能替代 wait。
同一模型须覆盖 CPU worker、GPU、编码器队列；不能按某个库函数名伪造同步合同。

## 8. 冻结 IR 的可复用部分与缺口

| 当前文件/接口 | 已实现、可复用 | 本方案仍缺的类型/连接 |
| --- | --- | --- |
| `scar/ir/program/model.py:355` ExitKind；`:397` CompletionSignature；`:418` CompletionSuccessor | 普通 INVOKE 的 NORMAL/RAISE 私有入口、edge-defined payload、显式 state。 | 当前 `Operation` 强制恰好两种完成；没有 scoped language transfer、pending completion、suspension/resume 或资源完成端口。不能静默重新解释 NORMAL。 |
| `model.py:211,224` StateVersionValue、LocalBindingValue；BindingDefinition/Read | 局部绑定、未绑定状态、SSA 与 state 依赖可复用。 | ExceptionPacket/handler state、FunctionEnvironment/cell、保存与恢复 frame 的接口缺失。CompletionSignature 当前仅接受 ValueType，不能直接携带所有新 variant。 |
| `scar/ir/program/structured.py:19,78` PythonProtocol / LoopInterface | truth、iterator/advance/match、while/for、break/continue/else 的 typed 索引与严格重算。 | 跨 cleanup 的 transfer、cleanup scope/stack 和 generator delegation 未实现。 |
| `scar/analysis/structured_lowering.py:140,159` finish_exit / invoke | return payload + frame 后态；每次 invoke 的正常/异常后态。 | failure 默认直接 finish_exit；不能承接通用 handler/finally/with unwind stack。需要先将 pending 路由过 cleanup 再做真正函数出口。 |
| `structured_lowering.py:384,443` statements / build_function | 当前支持子集自动生成；关闭路径不继续虚构执行。 | Try/With/Raise 等 statement 尚未由此 builder 完整处理；Async、Yield/YieldFrom、free/nonlocal 环境显式拒绝。被拒绝不计内部覆盖。 |
| `scar/ir/program/frames.py:47` FrameRules | 未证 condition、未知 effects、可能不完成、unraisable、不保证 free。 | 可保留，但不能将这一规则升级成 finally/with 通则或 suspension 清理。 |
| `scar/ir/program/functions.py:80` BodyEntryInterface；call operand route records | formal/Use 与部分真实 call occurrence 的条件引用路由。 | 隐式环境入口、generator request/boundary adapter、实际动态控制选择、全状态/资源调用组合未完成。 |
| `scar/ir/v2/contracts.py:162,176` ResourceKind/Requirement；`values.py:151` Materialization | 有资源/物化的既有记录基础。 | ResourceDefinition→Instance 与新 Program core 的完整连接缺；`ready_event: str | None` 不是本文 scoped readiness 合同。 |

因此不能声称“当前四类 + NORMAL/RAISE 已经表达完整程序”。当前子集的局部 typed
validator、公共 source replay、实际 execution correspondence 分别证明不同事情；
它们不能互相代替，也不自动提供等价变换权限。

## 9. LeWM 实际路径压力核对

以下位置均在 `/home/zyf/AAA/le-wm`；是只读源码需求，不是运行 dispatch 结论。

| 实际源码 | 本模型必须回答的连接 | 当前自动生成状态 |
| --- | --- | --- |
| `stable-worldmodel/stable_worldmodel/world/world.py:403–446`，尤其 `:411–412` on_step、`:420` yield | advance/env step 的异常与状态；callback 后态；yield 保存 loop/局部/iterator；恢复后继续计数/reset；自然完成与 early return。 | generator profile 仍拒绝；不能因已索引/已采到 call 就称该 Region 控制完成。 |
| 同文件 `:541–550` nested on_step | goal_snapshot/results/frames 的 cell/环境，实际 callback entry 和 mutation 后态；return None 不表示无效果。 | 完整 closure/environment 接口未自动接入。 |
| `stable-worldmodel/stable_worldmodel/plot/video_utils.py:41–44` | 字体调用异常仅在 OSError 匹配时 fallback；其他异常传播；handler 后态进入后续图像构造。 | try/except 完整控制尚未由当前 builder 生成。 |
| 同文件 `:8–17` save_video | writer create、append 次序、close 的 host/资源完成合同；异常时部分输出；资源保留与释放。 | 可索引/观测调用不等于编码完成和外部 effects 已建模。 |
| `eval.py:160–169` 文件 with | enter、每次 write、异常/return 下 exit、输出后态；上下文退出不能由普通调用次数替代。 | with 协议未完整自动生成。 |
| `eval.py:88–97` 与 solver/model 调用链 | 加载、设备选择、enqueue/物化/ready、调用返回与保存路径的实际依赖。 | coarse world/部分引用关系不构成 GPU readiness 或整个程序依赖闭包。 |

验收必须从原始源码、真实采集与既有合同自动重建这些接口；不提供人工 LeWM 图，
不添加 purity/constant/名称白名单。五类反例需有自动源码构图、typed validator 拒绝
错误连边、公共 source/report replay，以及适用时动态 occurrence 对应。只有 opaque
父节点而缺少内部 calls/Uses，不算这条路径的结构覆盖。

## 10. 实施和兼容边界

建议先冻结上述完整模型，再分层实现：语言 transfer/cleanup → resumable frame 与
environment → actual invocation 的组合 → resource issue/ready/visibility。阶段间
允许明确未实现的端口，不能用未知外壳把整条路径计为完成。

新类型必须使用新 core/profile schema，保留已发布 profile 的原始解释与严格重放。
旧 NORMAL/RAISE 不自动升级为完整 LanguageOutcome；旧 report 没有 environment、
readiness 或 cleanup 证据时，不补 VERIFIED 边。具体下一 schema 数字由当前版本表
分配，不能覆盖历史 ProgramGraph v1–v3 或 source/inventory profile。

递归化简的 observable roots 至少包含语言正常/异常完成及 payload、外部写入/顺序、
资源同步与存活要求，并对允许观测的 termination/suspension 行为声明等价合同。
只对返回引用做逆追，不足以删除 cleanup、wait、callback 或 encoder close。

**本次结论是模型设计可表达上述协议，不是现实现已自动生成。** 当前冻结实现有
有限同步调用、结构化循环与 frame 依赖；完整 try/with、generator/environment、
GPU readiness 和全过程变换证明仍未完成。结构覆盖、语义精度、执行对应、变换权限
必须分别报告；本审查不授予纯度、缓存复用、删除/重排或加速结论。
