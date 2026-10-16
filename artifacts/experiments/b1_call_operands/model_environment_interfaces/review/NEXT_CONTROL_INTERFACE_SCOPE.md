# M1 下一个控制接口：带清理的语言完成

审查基准：`e8267134b5daf40e5a2b89b1a00a73186284e864`。只读审查；没有运行测试、
目标程序或工作负载。`completion_validation.py` 在此版本不存在；完成边检查位于
`scar/ir/program/validation.py`，Python 循环/协议检查位于
`scar/analysis/structured_lowering.py`。

## 结论与范围

当前最大断点是语言完成无法穿过 cleanup：图能表示局部 CFG 跳转、函数正常返回/异常、
以及 `INVOKE` 的调用正常/异常结果；它不能在同一个 `finally`/退出回调前保存并路由
Return、Raise、Break、Continue，也不能让 cleanup 的新完成覆盖旧完成。

下一最小闭环应是一个 **带类型的 pending-completion/cleanup 接口**，先支持同步
`try/finally` 的 Fallthrough、Return、Raise、Break、Continue 保存、正常恢复与替换。
它复用已有 CFG、Value/Use 与状态 SSA；不另建控制图或第二套 world。`with` 放在同一
handoff 接口之上的下一小步，因为还需 manager lookup/enter/exit 调用、异常抑制和
逆序退出。此建议只定义组件顺序，不表示它们已经实现或 M1 已完成。

## 现有接口能做什么

- `ProgramGraph` 的 `Operation` 有有序 `Use`、结果、状态 `Access` 和控制 terminator；
  `Block` 的参数是合流端口，`Region` 有普通/异常 `ExitPort`。
- `Successor` 将当前 Use 转给目标 BlockArgument；`StateVersionValue` 由当前 block
  状态、逐边参数和 region 域约束形成显式 SSA。未知操作需保留每个状态域的出口。
- `INVOKE` 专用于操作本身的 NORMAL/RAISE：每边有独立签名与目标 block，
  `CompletionResult` 仅在对应后继可用；未知效果的每种出口须携带各自 post-state。
- `BindingDefinition` / `BindingRead` 和 `derive_binding_facts` 已能把同一局部槽的
  BOUND/UNBOUND/MAYBE 事实沿合流、循环回边推导；循环 header 的槽由同槽 block
  argument 接回。`LoopInterface` 索引真实 header、natural-exit、backedge、break、
  continue 边，不替代 CFG。
- `StructuredBodyModel.protocols` 给 synthetic operation 一个有版本的 Python
  协议和精确 source；validator 要求精确 source 对应，独立 source replay 才检查规则。
- `ExitKind` 只有 NORMAL/RAISE。这里 NORMAL 是一次操作/函数调用的 normal 出口，
  不是 Python 的 Return、Fallthrough、Break 或 Continue 标签。

当前 `structured_lowering.py` 能为有限同步子集建图：if、while/for、循环 else、
break/continue、return，以及常规表达式/调用。for 以 `ADVANCE_ITERATOR` 的 RAISE
分支和显式 `MATCH_STOP_ITERATION` 分出 exhaustion 与真正异常。`try`、`with`、显式
`raise`、async/generator/resume 仍落到 unsupported/boundary；不应把它们当作空操作。

## 推荐的最小 typed 增量

新增独立于 `ExitKind` 的语言完成联合：

```text
LanguageCompletionKind = FALLTHROUGH | RETURN | RAISE | BREAK | CONTINUE
CompletionTarget = FunctionExit(scope) | NormalSuccessor(edge) |
                   LoopAfter(loop) | LoopHeader(loop)
PendingCompletionType = typed value type, not ReferenceValue or bool
PendingCompletionValue = SSA value carrying one pending variant
```

目标必须是 scope/loop/edge 的强类型 ID，不存自由字符串或函数/变量名。Return 和
Raise 必须分别携带已求值 payload 引用；其他变体没有伪造 payload。pending 的定义和
沿边转交必须由 canonical `UseID` 表示，并由独立 typed relation 记录 tag、target、
payload use 与 `ControlEdgeReference(operation, successor_index)`。共享 cleanup 的
合流端口应有一个显式 pending SSA/block argument；validator 从每条真实前驱边推导它的
可选变体，不接受 metadata 自报“可能是哪几种”。需要完整字段前，必须先决定这个
relation 是 `Value` 定义/使用表，还是附着在 CFG edge 的 typed completion-flow；不可
让 Value、operation label 与 overlay 各自保存冲突副本。

增加精确绑定到 cleanup source/region 的 `CleanupInterface`：入口接 pending 值及
当前全部 StateVersion，完成出口通过真实 CFG 边路由。cleanup 正常 fallthrough
保留原 pending 的 kind/target/payload，但用 cleanup 后的状态；cleanup 中的新
Return/Raise/Break/Continue 取代原 pending。对共享入口，完成后的分派必须由 pending
的 typed tag/target 显式路由到正确函数 exit 或 LoopInterface 端口。cleanup callback
本身仍是 `INVOKE`，其异常边会生成新的 RAISE pending 和异常后状态。

这一个增量不要扩展 `INVOKE` 的 NORMAL/RAISE 结果种类，不要把所有语言转移做成
`Region.ExitPort`，也不要用一个普通 `ReferenceValue` 承载 tag/payload。Pending
completion 只描述控制/负载；当前状态仍由已有逐边 StateVersion 参数传递。源码协议
表负责解释 Python 何时创建、保留、替换或消费该值，source replay 负责匹配 source，
core validator 检查类型、producer/Use 唯一性、边路由、目标 scope、payload 与 state。

### 需锁定的具体关系字段

1. `PendingCompletionValue` 的定义身份与静态变体范围；OperationResult 与 BlockArgument
   的唯一 producer/origin 规则。
2. 每个产生/转发 pending 的 record：`value`, `kind`, typed `target`, optional
   `payload: UseID`，其中 raise/return 必须恰有 Reference payload，其他类型无 payload。
3. 合流时每条 CFG 入边的 completion-flow：精确 operation/successor index、目标
   pending BlockArgument、该入边的 variant/target/payload Use。禁止不相关前驱借用
   支配值；同一 payload 静态值可在多边使用，但每个 operand occurrence 有独立 UseID。
4. Cleanup interface：owner/source、入口 pending argument、可达完成路由；每条
   resumed edge 必须消费当前 pending，并带最新 post-state。source protocol 决定
   哪些来源路径能进入该 cleanup，不由 label 决定。

上述第 2/3 项怎样在不把异构 payload 伪装为同一普通类型的情况下编码，是本轮应先
冻结的 schema 设计问题。可用带标签 union Value，或强类型 per-edge relation 加显式
pending block argument；两者都要让“Return(ref) 与 Raise(exception) 不串线”可由
validator 检查。不要仅凭名称或退出协议手工判断。

## 一个最小验收 CFG

```text
try: return f(x)
finally: audit()
```

```mermaid
flowchart TD
  C[INVOKE f(x), world S0] -->|NORMAL: result r, S1| R[Pending RETURN(exit, r)]
  C -->|RAISE: exception e, S1e| E[Pending RAISE(e)]
  R --> F[shared finally: INVOKE audit, current state]
  E --> F
  F -->|normal S2 / S2e| D[typed pending dispatch]
  F -->|raise e2 / S3| N[replace pending with RAISE(e2)]
  D -->|RETURN r, latest state| X[function normal exit]
  D -->|RAISE e, latest state| Y[function raise exit]
```

图中 `f` 或 `audit` 的异常后状态不回滚；`audit` 的异常覆盖原 Return/Raise；正常
`audit` 不重算 `f(x)`，并将先前求得的 `r` 原样带出。Return 和 Raise 的 variant 与
payload 不能通过普通 ValueType 相同而互换。

## 正反例验收

**正例必须通过：**

- 上图两个 incoming completion 进入 cleanup；正常 cleanup 分别恢复原 Return 或
  Raise，且使用清理后的 world。cleanup Raise 建立新 Raise，旧 pending 不再可达。
- `for ...: try: break; finally: continue`：finally 的 Continue 替换 Break，路由到
  此 loop 的 header/advance；不去 after/else。嵌套 loop 选定内层或外层 target 必须
  与 lexical owner 一致。
- `for` 的零次 `Advance` exhaustion 只去自然出口/else，已知 loop binding 留在原
  binding 状态；body 内部分配或异常不会被错误标成 exhaustion。
- return 值在 finally 前求值：`try: return x; finally: x = y` 仍传入此前的引用；
  finalbody 自己 `return z` 时只保留新的 Return(z)。

**必须拒绝或显式保持未知：**

- 把 `INVOKE` 的 RAISE completion 当成任意 cleanup `Raise`/function exit；它只代表
  该次 invoke 的结果，须由 source completion protocol 接上语言 pending。
- 把 cleanup 前 StateVersion 传到最终 exit，或在 exceptional edge 上退回调用前 state。
- finalbody return 后同时保留原 return 边；把一个 completion target 串到错误 loop/函数。
- 用 `ReferenceValue(None)`、bool、字符串标签或普通 state world 替代 pending union；
  这不能表达不同 payload 与 target 的关联。
- `with cm: return x` 对 `__exit__` 返回值做 Truth；仅异常 pending 可被真值抑制。
  `__exit__` 自己抛异常要替换原 pending。manager 尚未成功 enter 就不能调用其 exit。
- 把 for advance 的任意 `StopIteration`、body 中显式 StopIteration 或用户操作 RAISE
  当作 exhaustion；只允许 Advance 协议专用的匹配边。
- 缺失 source/handler/cleanup 路径当作 fallthrough；普通局部 UNKNOWN 不能被提升为
  definitely bound，也不能直接穿过带未知效果的操作。

## 可复用的不变量与现成思路

- 保留 core `validate()` 的 exact owned Use、每条 CFG edge 的参数/类型、dominance、
  私有 INVOKE completion target、每个 StateLocation 的当前版本/覆盖检查；不另造
  completion world 字段。
- 保留 `derive_binding_facts()` 的合流固定点；清理路径对 fast-local 使用同槽
  LocalBindingValue/LOCAL_BINDING Uses，分支/回边由实际 CFG 前驱推导。
- 沿用 `LoopInterface` 作为 CFG 索引：cleanup 路由产生的 break/continue 也必须更新
  实际 edge reference，不能只在 `CleanupInterface` 声明目标。
- Python 可借鉴编译器的 lexical block/handler stack 与 pending-reason/unwind 思路，
  但定义依据是 Python 3.14 control protocol 文档，不依赖某个字节码 layout。finally
  的 completion 替换、with 的异常专属抑制及逆序退出仍按文档逐项验证。
- MLIR 可借鉴 block arguments/branch operands 表示 CFG phi 和 loop-carried values；
  structured region `yield` 可供更高层结构化视图参考，最终仍降到 canonical CFG。
  LLVM-style invoke/unwind 可类比普通 CALL 的 normal/raise 双边，但没有 Python
  pending Return/Break/Continue 或 with 抑制语义；不能直接复用成全套完成模型。

## 推荐实现顺序与未决项

1. 先冻结 `PendingCompletion` union 与 per-edge flow 的单一 canonical 存储形式、
   ID 类型、消费规则和 v6 wire 版本；v1–v5 严格读取/原样重放。
2. 用 source-exact overlay + core validation 实现同步 `try/finally` 的保存、恢复、
   替换，再覆盖 loop target 与正常/异常 post-state。保持未支持路径显式 gap。
3. 复用同一 pending/cleanup 接口接 `with`：enter 成功注册 exit、嵌套逆序、异常
   suppression Truth、cleanup 覆盖异常；之后才扩 try/except/except*。
4. async/generator 的 Suspend 保存 cleanup stack 和 pending completion，是另一阶段；
   当前不引入伪造 resume token。

待决：pending union 是 `Value` 变体还是 per-edge completion-flow + argument；completion
dispatch 是否用专用 terminator 或 typed protocol 生成普通显式 CFG branch；一个 cleanup
region 能否容纳不同 payload 类型的输入（若不能，需明确 case-splitting，不可静默 cast）。
另外需决定对资源/异常对象身份、bare raise handler context、finally suspend 的引用
存活与释放如何逐项连接现有 StateLocation/Resource 接口。以上任一未冻结前都不能称
本轮完整支持 cleanup，更不能据此宣布完整 M1。
