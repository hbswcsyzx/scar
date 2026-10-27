# 循环、状态及局部保留：可证伪的执行验收设计

日期：2026-10-16。只读审查基线：`/tmp/scar-call-windows-qx_qw6dk`，冻结 `8a300eb` / source FP `38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`。本文没有运行全仓、LeWM 或下述新测试，没有修改产品。后续拟实施目录为 `/tmp/scar-structured-model-280qf4mi`；其 typed API 尚在开发，本文区分现有事实与待实现合同。

## 1. 当前能证明什么

| 已审查位置 | 已有能力 | 不能作为的证据 |
| --- | --- | --- |
| `scar/ir/program/validation.py:27` | Use 唯一性、跨 region 接口、支配/可用性、逐真实 predecessor arity/type、每 block 的完整 state domains、current-state 使用、每路径 INVOKE completion、state/order roles | Python `while/for`、next 耗尽、break/continue/else、heap 效果与返回值的执行正确性 |
| 同文件 `:249`, `:304`, `:334`, `:397` | completion 私有目标；state SSA；未知效果在正常/异常路径产生后状态；禁止 stale state | 不能判定两条同类型合法 CFG 边是否符合源码语义；也不能证明一份错误的 `effects_complete=True` 摘要为真 |
| `scar/analysis/program_lowering.py:528` | Name assignment、Expr、Return、If；同步根；body 无法连接则明确拒绝 | 当前仍没有自动 for/while。不能把 source CFG 中的 loop 分类或手工图计数算成 core 支持 |
| 同文件 `:881` | 当前 source replay，完整 source/use/value 对应与结构检查 | replay 重跑同一 lowerer，无法独立发现 lowerer 自身稳定地产生错误 CFG |
| `tests/fixtures/program_graphs.py:130`、`tests/unit/test_program_graph.py` | 手工 loop/state/backedge 反例、结构 mutation | 未执行 core，未与 Python 比较 |
| `scar/analysis/constants_v2.py:476` | `SourceSemanticsGraph` 上有限不可变常量求值；明确拒绝 CALL、可变构造、循环依赖等 | 不是 `ProgramGraph` interpreter，不能用作下述语义对照 |
| `scar/analysis/frame_queries.py`、operand query | 有条件引用路径及明确 opaque/control 边界 | 不是 concrete execution；不证明 effect/world/content 等价或实际分支选择 |
| `tests/unit/test_frame_runtime_effects.py:82,110,143,176` | 真 Python：finalizer 改返回对象内容、unraisable、逃逸 frame、traceback 保活 | 没有 core evaluator 对照；它们正确地阻止更强的释放/纯性结论 |

全库搜索未找到 `ProgramGraph` 的现成 executable interpreter。最小增补应是**测试专属 core CFG evaluator**，不是新优化 backend。其输入来自真实 `.py` 自动构图，不能调用原 root 函数、`eval` 原 root 表达式或重走 AST 语句来代替执行图。

## 2. 独立 oracle 与最小接口

### 2.1 一次测试的两条独立路径

```python
source_path.write_text(source)
program = lower_source(source_path, "f", profile=NEW_STRUCTURED_PROFILE)
assert program.graph is not None       # 范围内 case 不许以 Unsupported/skip 过关
require_valid(program.graph)
require_valid_source_and_profile(program)
python_case = factory()                # 独立的、别名拓扑相同的新对象图
core_case = factory()
expected = run_python(compile(source, filename, "exec", dont_inherit=True,
                              optimize=optimize), python_case)
actual = run_core(program, arguments=core_case.args, globals=core_case.globals,
                  compile_debug=(optimize == 0), max_steps=10_000)
assert compare_observations(expected, actual)
```

`run_python` 真正调用编译出的 Python 函数；`run_core` 只执行生成 graph 的 block/operation/edge。两者的状态、事件列表、iterator 和 sentinel exception 必须由 factory 各创建一次。不能 deepcopy 任意用户对象（它本身会调用用户代码），不能共用有状态 iterator，也不能把 Python 执行产生的结果喂给 core 充当期望值。

最低 outcome 合同：

- `RETURN(reference/data, declared_post_world)` 或 `RAISE(exception, declared_post_world)`；`BUDGET_EXHAUSTED`、`UNSUPPORTED_PRIMITIVE` 必须是单独结果，不能伪装用户异常或正常结果。
- 身份按输入根/受控构造序号规范化；同对象 alias 必须保留，跨执行不直接比较 `id()`，不调用任意 `repr`、`==` 或 `hash`。
- 对 fixture 暴露的 list/dict/受控对象字段做快照，比较 mutation、别名关系、用户 hook 调用顺序和次数。
- 普通用户异常比较 type、exact-builtin args 及已标记 exception 的身份关系。语言只要求错误类别的本地 unbound 诊断，不先把 CPython 某版错误字符串当作跨版本合同。
- source/core/conditions 与 effects scope 仍独立保存。有限 fixture 等价不把当前 UNKNOWN、NOT_GUARANTEED 或 transformation flag 改为真。

### 2.2 Evaluator 必须执行的 core 机制

1. 用 `(Region invocation, dynamic block visit)` 执行 CFG；每次跳转先求完所有实际 edge arguments，再同时绑定目标 block arguments。不能逐个覆盖后又读取已更新值，也不能按 ValueID 将循环操作 memoize 一次。
2. `JUMP/BRANCH/RETURN/RAISE/INVOKE` 由 typed terminator 驱动。BRANCH 的 builtin bool 端口不再次调用用户 truth；truth 转换须是显式协议操作，恰好一次。
3. INVOKE 依据实际 Python 协议结果选择 NORMAL/RAISE，绑定该路径 `CompletionResult(i)`。异常前已经发生的 mutation 必须进该路径后状态。
4. state version 不是一个所有版本都指向同一可变 dict 的装饰标签。保存每次版本的独立观测快照/单调 token，并校验所消费 current state。出口同时核对**声明 post-world**与具体 heap/log；否则实际 host 变更会掩盖错误旧 world 边。
5. 执行 typed binding token；UNBOUND 不是 None、未知对象或漏 producer。分支/循环合流只 carry token；只有读取才触发 unbound 异常。token 自身不增加源语言 retain/release。
6. 每个普通 CALL 的 actual 按 exact UseID 顺序取值。同一个 Value 的两个 Use、同一静态 CALL 的两次 block visit 分开记账。可以执行测试实际输入的外部 callable 作为**一个 opaque host operation**，以观察其 mutation/raise；不可用原 root callable 替代图。已连接且纳入本次 evaluator scope 的 callee Region 应递归执行 core。
7. `Operation.label`、函数名字、SourceRole 文本不是语义 dispatch。已有表达式从 `OperationSource.semantic_operation` 找到 `OperationSemantics` 的 typed `Opcode`、attribute 与 ordered operands；新的 Python 协议必须有规范 typed descriptor。
8. 步数计入每个动态 operation/terminator，不按静态 node 数冒充动态预算。主测试仅有限循环；闭合不终止 SCC 只查图，不运行无限 Python。

### 2.3 已收到的 binding API 与仍需冻结的 primitive API

records agent 已明确：

- `LocalBindingValue(id, region, origin:BlockArgument|OperationResult, slot)`；`LocalBindingType(slot)`；`UseRole.LOCAL_BINDING`。
- `ProgramGraph.binding_definitions` / `.binding_reads` 默认空，旧 wire 显式分派。
- `BindingDefinition(value, state:BOUND|UNBOUND, payload:UseID|None)`：BOUND 的 payload 是同 producer 所有的 REFERENCE Use；UNBOUND 没 payload。
- `BindingRead(operation, binding:UseID, normal_result:ValueID|None)`：读取输入为 LOCAL_BINDING；普通 definitely-bound 或可能抛错的 INVOKE 两种路径均有显式正常结果。
- 普通 CALL、用户 formal/return/region exit 禁止携带 binding token；CFG carry 只在同 slot 类型之间绑定。

仍需 root 冻结：operation 到 typed protocol 的字段/record、`TRUTH`、`GET_ITERATOR`、`ADVANCE_ITERATOR`、`MATCH_STOP_ITERATION`、`MAKE_ASSERTION_ERROR` 及 opaque 生命周期规则；COMPILE_DEBUG 的环境端口索引/来源。当前计划保留 `next NORMAL(item)/RAISE(exc)`，**仅在该 NEXT 的私有 RAISE 后继**执行固定 builtin StopIteration 及子类判别，不新增全局 EXHAUSTED ExitKind。

MATCH 必须忽略用户 namespace 对 `StopIteration` 的重绑。GET_ITERATOR、body call、target store、truth 或 assertion message 的 StopIteration 不能误当 for 耗尽。

## 3. 必须能杀死错误实现的 executable cases

下列 `source` 都应落成真实临时 `.py`；host hooks 是测试专属受控对象。先用普通 Python 获得观测，再用生成图执行获得观测。不能只断言 block 数或标签存在。

| ID | 实际源码/输入 | 必须比较的行为 | 必杀错误 |
| --- | --- | --- | --- |
| W0 | `i=0; while i<n: i=i+1; return i`，n=0/1/4 | 返回 0/1/4，condition 次数 1/2/5 | 强制一次迭代、错误初值、条件提升 |
| W1 | while 条件调用 `test()` 返回带 `__bool__` 的对象；输入 False / True,True,False | test 与 truth 各每轮一次，最后 false 的 effects 可见 | 重复 truth、漏最后 condition、使用 pre-loop world |
| W2 | `__bool__` 第 2 次先改 box/log 再 raise 标记异常 | 仅一次 body，异常同 sentinel，第二次 truth 的后状态保留，else 不运行 | 条件当纯读取、异常 rollback、else 接异常 |
| W3 | while 内先 `i=i+1`，i=2 continue，i=3 break；有 else 与 after log | continue 后仍重查条件；break 不跑 else；after 恰一次 | continue 去错误 header/latch、break 走 else |
| W4 | while 自然终止、零次、return、body raise 四种路径 | 前两种跑 else，后两种不跑；最后 post-state 分别正确 | 用共享 broke bool 代替真实路径 |
| F0 | `for item in xs: pass; return item`，空/1/3 项 | 空时 UnboundLocalError；否则最后 item 原引用 | None 占位、预取一项、off-by-one |
| F1 | `item=initial; for item in xs: pass; return item` | 空返回 initial；多次返回最后 item；真实 None item 是绑定值 | 用 None 当 unbound；清空原有 binding |
| F2 | SpyIterable/SpyIterator，0/1/3 项 | GET_ITERATOR 1 次，NEXT 1/2/4 次；耗尽本次 mutation 在 else 可见 | 每轮重新 iter；将 StopIteration.value 当 item；漏耗尽 NEXT |
| F3 | __iter__ 修改状态后 raise；另一个返回非 iterator | 原异常/TypeError，body/else 均无；状态保留 | 把 iter 的 StopIteration 当零次、直接调用普通 `obj.__iter__` |
| F4 | NEXT 第 k 次先改 box 再 ValueError；NEXT 的 StopIteration 子类 | 前者外抛且无 else；后者正常耗尽并跑 else；post-world 都是 NEXT 之后 | catch-all 耗尽、只认精确 StopIteration type |
| F5 | 正常 item body hook raise StopIteration；用户 global StopIteration 重绑 | body 异常外抛，无 else；重绑不改变 NEXT 耗尽规则 | 在整个 loop 外包一个 StopIteration catcher |
| F6 | for else/break/continue，break 首/中/末/不存在；空 iterable | next/body/else/after 的完整事件序列、最终 target binding | break 后额外 next、continue 漏 next、总是跑/不跑 else |
| F7 | 两层 loop，内层 break/continue，外层 else；loop else 中指向外层的控制 | 最近适用 loop 的转移，外层剩余工作仍执行 | 单一全局 loop 上下文；else 绑定已完成的自身 loop |
| L0 | 函数内循环写 local，同名 global 已存在；零次后读 local | 仍是 UnboundLocalError，不能回退 global | 根据当前 env 是否有值决定 LEGB，而未按 symtable 编译期分类 |
| L1 | 先用非空 xs 调 f，再用空 xs 调同一个 f | 第二次未绑定；不同 invocation 不保留上一轮 token | code-level env cache 泄漏到下一 frame |
| C0 | 循环中 `out=pick(item,right)`；xs=[a,b]、[a,a]；pick 记录 actual 顺序 | 最后结果来自最后一次实际 call；每个 visit 的两 actual Use 独立 | 静态 CALL result 缓存、同 ref 合并两个 Use/两轮 |
| H0 | `for item in xs: change(a,item); return b`；a/b 共享或不同；change 改 list/dict | 返回身份、heap 内容、alias 拓扑、每次 change 的顺序 | 将相同内容当 alias；忽略循环 state carry |
| H1 | change 第 k 次先 mutate 再 raise sentinel | payload 同异常；已完成及失败这次 mutation 都保留；后续 body/else 不发生 | 异常使用旧 world；将失败理解为无 effects |
| H2 | RHS hook、receiver hook、index hook 和 setter 的有序 source store | 若本门不支持 `box[key]=value`，必须明确整 body Unsupported；以后开放时按 Python RHS→receiver→index→store 比较 | 跳过 store 后仍称 CONNECTED；按直觉错排 Python赋值顺序 |
| A0 | assert test/message hooks，optimize=0/1/2 | debug false 时 test/msg 都不执行；debug true 时 msg 仅失败执行，异常 args 保留原 message 对象 | 工具进程 __debug__ 冒充目标配置；无条件求 msg |
| A1 | truth/message 构造 raise；global AssertionError 被重绑 | 原异常和状态保留；assert 用固定 builtin 类，不查用户同名 global | 提前转 str(message)，替换真正异常，名称查找冒充 assertion primitive |

### 3.1 可直接参数化的三个基准源码

```python
WHILE = '''def f(n, emit):
    i = 0
    while i < n:
        i = i + 1
        if i == 2:
            continue
        emit(i)
    else:
        emit("else")
    return i
'''
# n=0 -> (RETURN 0, ["else"])
# n=1 -> (RETURN 1, [1, "else"])
# n=3 -> (RETURN 3, [1, 3, "else"])

LAST = '''def f(xs):
    for item in xs:
        pass
    return item
'''
# [] -> RAISE UnboundLocalError; [token] -> token identity;
# [left,right] -> right identity; [None] -> RETURN None, not unbound.

MUTATE_THEN_FAIL = '''def f(xs, change, box):
    for item in xs:
        change(box, item)
    else:
        change(box, "else")
    return box
'''
# change appends its item to box/events, then optionally raises a per-case
# sentinel on its kth call. Observe mutation BEFORE matching that exception.
```

`<`, `==` 的 SOURCE comparison 若仍是 typed OPAQUE 而没有精确可执行语义，不许根据 AST/label 私下实现比较。第一版可将条件与相等判别改为显式传入 `test()`/`is_skip(i)` host hooks，以测试 loop 本身；比较语法继续明确 Unsupported。若产品承诺已有 comparison 表达式支持，则应补 typed comparison primitive 后覆盖原源码，不能把该 scope 悄悄删掉。

### 3.2 同类型但错误语义的图变异必须被杀死

从真实 lowerer 输出修改一处，并保留结构合法性；不是手工图代替构图：

- true/false successor 对调；loop else 与 break 目标对调；continue 指向错误但类型一致的 header。
- header 初始/回边的两个同类型 local token 对调；把 initial token 代替 backedge 当前值。
- NEXT 的 RAISE 分类替换为普通 body call 的 RAISE；错误异常同为 ReferenceValue，单靠类型不够。
- 将失败操作的后 world 换成旧 world；错误完整摘要容许 forward 时，source/protocol validator 必须拒绝，或 evaluator 的 declared poststate 比较必须失败。
- 将一个 actual Use 替换成同类型另一个 actual；把两轮同静态 call 的结果误复用。

结构 validator 可拒绝的 mutation 应拒绝；结构仍合法的 mutation 必须被 source/profile validator 或真实执行差分抓住。source replay 本身不能替代差分，因为 lowerer 也可能产生同一错误。

## 4. 局部保留与生命周期：必须独立保留的反例

当前 FrameRules 是 UNKNOWN effects / MAY_NOT_COMPLETE / NOT_GUARANTEED release / UNRAISABLE finalizer errors；不得为让解释器简单而改成“EXIT 删除全部对象”。

1. **SSA cache 额外保活**：`v=make("old"); v=make("new"); emit("after"); return v`。CPython、无环且无额外外部 owner 的 fixture 中，old finalizer 在 after 前可见。evaluator 若用一个永久 `ValueID -> strong object` 字典，会错误延后销毁。任何精确 lifetime 模式都必须有独立 ownership ledger，不能把每个 SSA/block-argument token 当真实新 retain。
2. **返回引用与内容不同**：保留现有 `local=make(x); return x`，finalizer 改 x 内容；引用路线正确不等于返回内容或 effects 相同。
3. **逃逸 frame / traceback**：保留现有 getframe 与 original exception traceback fixture。返回/异常完成后局部可能仍存活，显式 clear 后才释放。模型不能无条件立即销毁 frame；unraisable finalizer 也不替换 pending normal return / 原异常。
4. **loop hidden iterator temporary**：break 不调用 iterator.close；iterator 引用是否析构受其他 owner 影响。target 仍持有最后 item，continue 不得释放仍绑定的 item。normal/exhausted/break/unwind 的生命周期义务都须保留。
5. **truth temporary**：无额外 owner 的条件对象 truth 后释放可在 body 前产生效果。不能用一个返回 bool 的“纯条件”表示该对象所有效果已消失。

第一门测试 evaluator可以明确将精确 RC/GC/traceback timing 标为 `LIFETIME_OBLIGATION_UNRESOLVED`，保留真 Python反例与模型固定 UNKNOWN。此时不能宣称已经比较并证明这些物理生命周期行为等价。若 gate 要求精确生命周期比较，它就是单独未通过项，不能以 PASS/skip 掩盖。普通值/heap/顺序差分通过的范围须排除这种未解决的对照。

## 5. 最小 validator 增补

- core codec/type：LocalBindingType/Value/UseRole/BindingDefinition/Read；CFG 同 slot carry；禁止 token 当 Python 对象、参数、正常返回；每 producer 精确对应，UNBOUND 无假 payload。
- protocol：每种 typed kind 的 exact inputs/results/completions/state；TRUTH、ITER、NEXT 是可能执行用户代码并 raise 的 INVOKE；MATCH 仅接本次 NEXT 私有异常及后世界，不查重绑 global。
- source/profile：typed loop reason 与精确 span；header/entry/backedge/break/continue/else 的来源与最近 loop 对应；不靠 block label。真正无法连接的 target/store/内部 syntax 整 body 明示 Unsupported，不能删分支后发布完整 body。
- state：延续当前 STATE_CONTENT/current world/所有完成路径 post-world；部分/未知写入不得借 full_overwrite 用 STATE_ORDER 绕开内容依赖。
- frame：当前 validator 要求每个 ordinary operation 都是一条 frame transition。新增非 INVOKE ordinary primitive/binding operation须有新 profile 的明确覆盖规则，不能通过宽松白名单或不检查普通 op 逃过 frame 义务。
- compile debug：环境端口与当前函数编译配置绑定。未知端口的 true/false 两个值都执行差分；各函数配置独立，不把 caller 配置暗传成 callee事实。
- 控制：generic core CFG 合法不证明本次 predecessor；动态 query 遇重复 call result 或不同来源 merge 仍要明确控制选择/歧义边界，不能按 ref 相同选路径。
- 非终止/预算：无出口闭合 SCC 合法，不补虚构 return None；测试 evaluator 步数超限不是用户异常；构造预算按真实工作计，不能通过小预算剩半张图而称完整。
- 历史：任何字段/profile/wire变化须显式分派，旧 source-program/inventory/core canonical replay 不解释成新 binding/protocol事实。

## 6. 可执行测试落点与验收判据

拟新增且仅测试支持：

- `tests/fixtures/structured_program_oracle.py`：CFG evaluator、独立 Python runner、bounded execution outcome、受控 observation normalizer。未知 typed kind 返回明确 Unsupported；不提供业务函数名单。
- `tests/unit/test_structured_program_execution.py`：上表真实 source→自动 graph→execution 对照、同类型 mutation、UNKNOWN/lifetime boundaries，以及有界 finite cases。结构校验复用现产品 validator，不能修改旧测试预期以适配新 default。

通过必须同时记录：每 case 当前源码、输入生成策略、Python outcome、core outcome、typed semantics/source replay 与预算状态。仅返回值相同不足以通过；异常和可见 heap/log不相同就是失败。尚无 evaluator 或 typed primitive API 时报告未实现，不以只验证 Python 一边的结果说 gate 已通过。

## 7. 当前外部 offline driver 的只读状态

读取 `windows_lewm_analysis/progress.json` 与进程状态时：inventory phase 仍 RUNNING，没有 returncode；inventory.stdout/stderr/time-v 尚为空。实际 CLI PID 568259 已连续使用 CPU（一次快照 elapsed 6m39 / CPU 6m39 / RSS 246500 KiB）。公开参数已被 argparse 接受并进入执行，当前没有可归类的 schema/API 失败证据，不能把空 stdout 或进度 elapsed=0.121 当失败或挂死。

Driver 只在 phase 开始/结束原子更新 progress，长 phase 中 elapsed 不是心跳。未启动第二次 pipeline、未附加执行 target、未修改 driver 或 frozen source。后续若进程退出，必须先看实际 returncode/stdout/stderr/result，再区分 CLI INVALID、driver inspection schema不匹配和真实采集/建图边界；不得并发重跑来掩盖现场。
