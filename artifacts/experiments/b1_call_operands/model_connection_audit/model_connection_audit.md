# 跨调用模型连接审查

审查日期：2026-10-16  
只读输入：SCAR worktree `8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`；LeWM source `f70fed80288462ca4d006cb3607ec6da6eaa851f`。未运行 LeWM、未运行长测试、未改产品源码。

## 结论

**对真实跨层自动建图，先补 body-preserving 的控制流/状态骨架，再扩 receiver/default/keyword binding。** B2 的绑定规则只会把已经存在的调用 `Operation` 的有序 `Use` 接到已构造的 callee formal。当前一个函数体遇到不支持的循环或赋值时，整个 body graph 会被拒绝，调用 `Operation` 和 `UseID` 也随之消失；此时 B2 没有端点可以连接。

B2 仍是必需的后续工作。LeWM 的关键路径确实包括实例调用、关键字和 `*args/**kwargs` 转发。可以继续用小型自动 fixture 开发、验收这些 binding 规则，但不能把它作为下一道完整程序连接门。下一道生产门应先让源函数保有可查询的 Region，显式表达循环、未知效果、状态前后版本、正常/异常/退出控制，再在这些调用点上逐步放宽绑定规则。

## 源码证据：不支持语法会拒绝整个函数体

在 `program_lowering.py` 中，语句 lowering 支持单目标简单赋值、表达式、`pass`、`return` 和 `if`；其余语句走 `_Unsupported`（528–590 行）。BOUND_FRAME 的语法检查也只接受 `if`、单个 `Name` 目标的简单 `Assign`、`Return`、`Expr`、`Pass`，不接受 `for`/`while`、`AugAssign`、复合目标、`try`、`with` 等（593–610 行）。闭包/`nonlocal` 会在进入 body 前拒绝；async/generator 也有明确拒绝路径（612–648 行）。

关键行为不是“生成局部 gap 后继续”：`run()` 最外层捕获 `_Unsupported` 后令 `graph = None`，并清空该次构造的 operation/value/use/call-target links（723–783 行）。因此，若 `solve()` 内一个循环不支持，循环之前或其余位置的 `self.model.get_cost(...)` 也不会留下可路由的 core call。调用路由要求来源侧调用、core operation、caller/callee body 同时存在；否则报 `SOURCE_CORE_BOUNDARY`（`call_operand_routes.py` 346–351 行）。

一个无业务特例的反例足以验证：

```python
def outer(x):
    y = helper(x)
    for item in items:
        y = step(y, item)
    return y
```

当前 source-to-core 不能为 `outer` 保留 `helper(x)`、`step(y, item)` 的 core operation，因为 `for` 令整个 body graph 为空。单独完善 `bind_call()` 不会恢复这些端点。

## 当前可连接的接口与缺口

| 层 | 已有结构 | 仍缺的连接 |
| --- | --- | --- |
| 调用点输入 | `Operation.invoke_arguments` 保存每个 input `UseID`；验证器逐 use 检查类型和控制绑定。 | 不支持的 body 没有 operation/use；当前动态路由只接受 `ast.Call`、`ast.Name` callee、无 keyword、每个实际参数是 `Name`（`call_operand_routes.py` 363–372 行）。 |
| callee 形参 | `BodyEntryInterface.parameters` 是按 formal slot 排序的 `FormalPort(slot, value)`，并带一个 `world` 端口（`functions.py` 72–92 行）。 `FunctionSignature`/`bind_call()` 可描述普通 positional、keyword、声明 default、`*args`/`**kwargs` 的条件绑定；starred 传参仍是 `INCOMPLETE`，default 被描述为读取 `DEFAULT_STATE` 而不是重新求值源码表达式（`function_binding.py` 19–68、145–160 行）。 | 当前 B1 routes 仅支持固定位置参数：需要 `EXACT_FUNCTION`、非 method、`layout.argcount == len(node.args)`、无 varargs/kwargs/kwonly/suspension、preload 为 plain function（`call_operand_routes.py` 354–387 行）。未把 `bind_call()` 的完整候选计划提升为真实调用证据。 |
| receiver/adapter | sidecar 原始观察保留 CALL callable/arg0 及 pre-load shape。 | 需要证明 raw bound method、优化后的 method call、callable instance、descriptor 或 wrapper 实际怎样把 receiver 变为 `self`；只看到 `FunctionType` 不能推出没有 receiver。函数名/代码名不够。 |
| defaults/keywords/packs | 源签名有 `default_source`，调用 AST 有带序号的 `CallArgument`。 | `default_source` 只是声明位置；要连接必须有调用时函数对象及其当前 `__defaults__`/`__kwdefaults__` 值的 runtime observation。Keyword 需要与实际 evaluated occurrence 和 `KW_NAMES` 等 code witness 对应。`*args/**kwargs` expansion 可能执行用户代码，必须显式记录 pack/effects/实际展开；不能按 AST 参数数推断。 |
| return/exception | `_Builder.invoke()` 产生 NORMAL/RAISE completion，各携带返回/异常 payload 与新 world；`Operation` 有 typed `CompletionSignature`、`CompletionSuccessor`、`CompletionResult`（`program_lowering.py` 361–389 行；`model.py` 448–515 行）。route overlay 能用同 attempt/entry 把 callee normal return 对到 caller normal-result（`call_operand_routes.py` 411–427 行）。 | route 仍是 conditional reference-provenance overlay，不是把动态 callee 写进规范 `Operation.callee`。异常后态不能回滚；body 没有完整 Region 时也无 return root。多动态目标必须按 invocation 保留，不能让一个静态 call site 被某次 dispatch 覆盖。 |
| 环境 | function body 的 entry 当前只有显式 formals 和 `world`；free/nonlocal bindings 被拒绝（`program_lowering.py` 642–648 行）。 | `globals`、`function.__builtins__`、closure cell、当前 defaults 应作为函数环境的隐式引用/状态端口，不是加成 Python 形参。要采到函数实例、当前 code、globals/builtins owner、closure cells/default values；相同 `CodeType` 不代表同环境。 |
| 可变状态 | `StateVersionValue` 有 location 和 definition；`StateAccess` 可表达位置、Footprint、读写；unknown invoke 通过两条 completion 产生前后 world。 | lowerer 给 world 的 `LocationID` 包含 source path/fingerprint（`program_lowering.py` 260 行），跨文件拼图不能因此默认把两个 world 当同一状态，也不能当作不相交。需要 workspace 级共享 coarse world 或显式有证据的 state-port mapping。未解析写入不能走 input state 原样穿出。 |

当前 `query_operand_routes()` 是参考用 lineage 查询：`CoreReferenceTemplate` 提取的是 `ReferenceValue`、formal 和 block argument 关系，不会证明 Tensor 内容相等、数值依赖、效果完整或 transformation authority。它也不能把不确定 branch 的前驱选成一次运行路径。C2 要在规范 core graph/查询里连接 DataValue、StateVersionValue、Operation effects 和控制边，而不是仅扩展 reference route overlay。

## 为什么循环/未知效果骨架先于完整 B2

LeWM 源码是一般 Python 结构压力，不是可以写特例的操作清单：

- `WorldModelPolicy.get_action()` 有循环与状态写入，并在 404 行调用实例 `self.solver(sliced, init_action=sliced_init)`；`kwargs` 还被声明在函数签名（`policy.py` 349–432 行）。
- `CEMSolver.__call__(self, *args, **kwargs)` 用星号转发到 `self.solve(*args, **kwargs)`（`cem.py` 91–93 行）。`solve()` 有 callback/batch/step 循环，并在 210 行调用 `self.model.get_cost(expanded_infos, candidates)`（148–210 行）。
- `LeWM.rollout()` 在 96–100 行循环并调用 `self.predict`，同时构造/累积列表和更新 info；`get_cost()` 有 cache 分支、字典 comprehension、字典读写，并依次调用 `encode`、`rollout`、`criterion`（`lewm.py` 70–108、126–151 行）。

当前失败点覆盖调用链的不同层：loop 使 `get_action`/`solve`/`rollout` body 整体无法进入 core；method/instance/keyword/pack 又使已识别的调用不能按窄 B1 规则产出 argument route。**只增加 binding 能力，仍会遇到 source/core 无 Region 的失败；只加循环但把循环整个压成 OPAQUE，也仍然隐藏其中调用。** 必须递归建循环骨架，并在内部继续 lowering 可识别的 call、read、write；不支持的子操作才成为带边界的未知效果。

## 建议的最小通用 core 结构

不新增第五种顶层实体。用现有 `Region`、`Block`、`Operation`、typed `Value`/`Use`、`StateLocation` 表达函数体与控制流；增补 typed loop/control interface（或等价的 typed relation）标出 header、latch、exit 端口和 carried values。标签字符串不能代替 backedge 与完成语义。

```text
preheader -- (live local values, W0) --> header block arguments
header -- condition/item operation --> body | natural-exit | raise
body -- ordinary operations/calls/mutations --> latch
latch -- updated carried values, Wn --> header block arguments
break -------------------------------------> after-loop (skip else)
natural-exit --> loop-else? --> after-loop
raise -------------------------------------> exception handler/function raise
```

验收语义：

- `while` 的 predicate 每轮重算；truth conversion 可调用用户方法并可 raise。
- `for` 的 iterator creation/advance 是有调用和异常边界的操作；区分 yielded item、正常耗尽和其他异常。`else` 只接正常耗尽；`break` 跳过 else；`continue` 回正确 latch/header。
- 循环 header block arguments 显式携带每个活跃 loop-carried local 和 coarse state version。backedge 把该轮的新值/新 state 传回；静态 ValueID 可以复用作循环模板，但不代表各轮值相等。需要零次迭代边和可能无限回边。
- 未知 body/call 对未知 world 做 `READ_WRITE`，使用 `Footprint.UNKNOWN`，正常和异常路径分别产生 post-state。不能把 pre-state 复制到两条出口并称未变。控制不终止由回边/`MAY_NOT_COMPLETE` obligation 保留，不静态展开循环次数。
- 简单 local rebinding 与 heap mutation 分开。`x = y` 是新 binding；`obj.field = x`、`d[k] = x` 是位置未知的 mutation。未解析 selector/alias 时连 coarse world 或对应 unknown location，不能用 empty target/empty effect 表示“不影响”。
- 对不支持语法保留源位置和局部 graph 前缀/后缀。可递归提取并 lower 已支持子表达式；若子表达式自身未支持，发 typed unsupported-effect operation/gap。不能把包含受支持 `self.predict(...)` 的完整 loop 变成单一 opaque op 后宣称 call 已入图。

首版可以把循环条件、iterator advance、unknown attribute/subscript write 表达成保守的未知操作；这只承诺 control/effect/state 依赖保留，不承诺数值、alias、目标或 purity 已知。对动态 call 不可解析为唯一 Region 时，Operation 仍保留其 `Use`s、unknown callee、normal/raise post-state 和 unknown effects；另以 per-invocation evidence 记录候选/实际 entry。不要把 capture 中观察到的一次 target 填成静态 source callee。

## 推荐实现顺序

1. **Body preservation gate。** 新 profile/version 不改变历史重放：单个 unsupported node 不再触发整个函数 `graph=None`。输出 per-span boundary、仍可验证的 core Region/Use 和 completeness；严格失败仍拒绝不变量损坏，不把 source coverage 伪装成 complete。
2. **Control/state skeleton。** 先支持 `if`、`while`、`for`、`break`、`continue`、loop-else、`return`、`raise` 的 typed CFG / loop-carried ports；加入 unknown normal/raise completion 与 may-diverge 标注。用 zero/one/multiple iteration 和 unknown mutation 反例验无 passthrough。
3. **Call-preserving recursive lowering。** 在循环/分支内部仍生成每一个可识别 call Operation 和每个有序 Use；处理 attribute callee、keyword occurrence、attribute/subscript assignment 的 read/modify/write 序列作为独立 source/core work。不能因为 callee unresolved 就删 call node。
4. **B2 binding adapters。** 在已有 `Operation` 与 body `Region` 上分别实现 receiver/method、current defaults、keyword、variadic pack 规则。每条规则有失败阶段和 evidence route，规则外留 unknown。B2 可并行在 synthetic multi-file fixture 上开发，但 production gate 不能把它当作替代第 1–3 步。
5. **Environment and state composition。** 增加 function-environment implicit ports，runtime capture 绑定当前 code/function/globals/builtins/closure/defaults；workspace 级 coarse world 映射 normal/raise pre/post state。保持 effects unknown，直到 state access/alias/overwrite/order 语义有独立证据。
6. **查询验收。** 同一次动态 invocation 内查询 caller actual → callee formal → callee 内层 call → returned payload → caller completion；保留 call site、argument occurrence、entry/exit、状态版本。多次同一 call site、递归、zero-iteration、raise 与不同 dispatch 反例不能串线。报告 route conditions；不把 conditional lineage 称为 content/effect equivalence。

## 最小通用验收集

自动生成的跨文件小项目应包括：

1. `while` 零次/多次、`for` exhaustion、`for-else`、`break`/`continue`、body raise、iterator raise 与可能不终止；检查 loop-carried local/world predecessor。
2. 循环内 `leaf(x, x)`、keyword、`obj.method(...)`、callable instance 与 nested helper；每个 source call 必须在 core 中有单独 operation 和有序 Use，unsupported binding 必须有特定 boundary。
3. unknown call/mutation 后 normal 和 exception world 都是新 StateVersionValue；RETURN/RAISE 读对应路径 state；无 state input 原样透传的假阳性。
4. 分支写入后 merge；key/attribute mutation；别名未知时 coarse effect 扩散，不能因为 Value/reference identity 仍相同就丢 state dependence。
5. 同 code 不同 globals/defaults/cell、函数对象换 `__code__`、dispatch 后 entry mismatch；只建立条件绑定或拒绝，不借 signature/source 为运行时状态补值。
6. 一个 body 同时包含支持的 call 与不支持的独立语句；unsupported boundary 不清空可验证的 body prefix/suffix，也不将被 opaque 子树隐藏的 call 算成 core-covered。

通过以上结构和查询门后，再用真实 LeWM 的 `SOURCE_CORE`/`DISPATCH` 分布决定具体补哪些通用 lowering 规则。Source AST 频率、trace 中出现某个 code、runtime CALL 数量都不能代替实际 core/use coverage。

## 目前可引用的采集事实及限制

本次审查发现 `artifacts/experiments/b1_call_operands/windows_lewm/trace/` 下有新 CPython 3.14.7 capture。其 run command 是 LeWM PuShT inference，单进程 capture `call-edge` 侧有 168,626 rows / 84,313 invocations / 850 codes，0 drops；`CPYTHON_CALL_WINDOWS_V1` sidecar 有 312,812 rows，其中 100,550 call attempts、4,069 entry handshakes、945 gaps、0 drops，约 114.2 MB raw sidecar。metadata 声明未观察 Tensor 内容、未建立 callable environment、未授权 transformation。`capture-result.json` 状态是 `NEEDS_READER_REVIEW`，这只是 collection 统计，不是 reader、source mapping 或 core-route 结果。

旧 `artifacts/experiments/b1_call_operands/lewm_real/` 是 `CPYTHON_LOAD_OCCURRENCES_V1`：sidecar 在 2,000,000 event 上有 1 drop；`archive-result.json` 标记 `capture_coverage_status=FAILED_BUDGET` 且 `route_analysis_performed=false`。不用于任何正向 route 计数。

截至这次审查，没有新 windows capture 的 inventory/link/query 结果，所以**没有可报告的 LeWM `SOURCE_CORE` 或 `DISPATCH` 比例/计数**。需等 raw reader、strict inventory/source matching 和 route builder 完成后，从其带 issue/boundary 的正式 report 取数；不得从 CALL attempt/handshake 数推导。
