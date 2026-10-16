# Python 3.14 控制构造：逐字段协议

日期：2026-10-16。状态：**M2 控制协议分册，供独立规格审查；不是 lowerer、图验证
或 M2 整门已通过的声明。** 目标解释器为本机 CPython 3.14.7；语言参考网页目前显示
3.14.8。存在可观察实现差别的地方明确标版本，不能静默采用另一版本规则。

本文件落实 [整体模型](../WHOLE_PROGRAM_MODEL.md) 的 ControlPort、Environment、
规范 state、LanguageCompletion、Suspend 和协议 adapter。仅定义规则；不增加
detector/backend，不实现建图或化简。用户要求先完成程序建模阶段，再停下讲解。

## 0. 共同接口、phase 和证据范围

### 0.1 记号与不变量

| 记号 | 输入、输出和含义 |
| --- | --- |
| `V(e,S)` | 在当前状态 S 求表达式值；成功为引用/数据结果与后态，可 Raise 或 Suspend。没有“表达式默认纯”规则。 |
| `T(e,S)` | 直接条件上下文：产生 true/false 控制边及后态；按下文规则处理短路表达式，不能总改写为 V 后再求真。 |
| `Truth(ref,S)` | 一次真正求真协议：类型的 `__bool__`，否则 `__len__`，均缺省则真；类型/范围错误和用户异常单独 Raise。 |
| `Store(target,value,S)` | 使用编译作用域和赋值协议；target 不是先无条件 V。普通绑定、属性/下标、解包有不同写入/失败，成功前的写不回滚。 |
| `Suite(body,S)` | 语句按序；仅前句 Fallthrough 才执行后句。Return/Raise/Break/Continue 经 cleanup；Suspend 保存 continuation，恢复后继续。 |
| `Advance(iterator,S)` | 只将本次取下一项的协议性结束映射成 Exhausted；目标绑定、filter、body 的同名异常不自动成为结束。 |
| `Pattern(pattern,subject,S)` | Match / NoMatch / Raise；合法 pattern 字段不是任意 await 表达式。Match/NoMatch 都可有状态变化和路径相关绑定；外层 subject/guard 可有合法 Suspend。 |

`Match/NoMatch`、`Item/Exhausted`、`True/False` 是具体协议分支，不是新顶层实体，
也不是 Python 异常的别名。规范状态只由 core Uses/StateVersion 和逐边参数传递。
每个隐式用户调用都保留输入、环境、前/后态及异常，不靠 label 推导纯度。

phase 分为编译/作用域检查、当前执行、首次进入、挂起后的恢复。source span 与
`type_comment` 等归属保留，但不因此制造运行操作。编译失败没有 executable body；
不可达源码仍参与 scope、generator classification 和语法限制。

### 0.2 直接条件与值上下文不能混用

短路的规范是按 continuation 组合，并在**同一次条件求值**中传递已选择分支及必要
operand 引用。`if a and b` 中 a 为假，只求真 a 一次；先写 `v = a and b; if v` 则可能
求真 a 两次。这不是允许跨语句缓存 `__bool__`，而是两种原始程序不同的协议。

嵌套 BoolOp/Compare/IfExp 也要传递条件 continuation，例如 `(a and b) and c` 不可
机械地先把左子树物化为 Python 值，再无条件重新 Truth。`T` 递归消费已知本次分支，
需要值时保留选中 operand；任何离开这次表达式的后续读取都不能继承“永远真假”事实。
本机探针 `truth_context`、`comparison_chain` 给出实际调用次数和引用身份。

### 0.3 生命周期、异常、资源

表达式临时值、iterator、pending payload、exception target 和 manager 均有保留/释放
依赖。释放可触发 finalizer、逃逸或不终止；不等于 free。FrameRules 的未证
NO_FRAME_INTERPOSITION 不因本文件更完整而变 VERIFIED。

语言 Raise 的 packet、当前 handler 上下文与 host Threw 分开；每次异常保留已发生
的部分效果。生成器暂停不执行最终 Frame EXIT；恢复接保存 frame 与当前共享状态。
Await/async 协议不自动证明 GPU、文件或其他资源 ready。

### 0.4 独立语言证据

证据位于 `artifacts/experiments/model_control_protocols/`：`probe.py`、`results.json`、
`results.initial.json`。命令（工作目录为本 worktree）：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/model_control_protocols/probe.py
```

最终 **17 组 PASS、0 FAIL**；报告含 Python 构建版本、命令、脚本 SHA、实际事件、
48 个相关 AST 类型的 83 个 `_fields` 与运行耗时。它们是 stdlib/小对象语言探针，**没有
导入 SCAR、运行目标程序或构造/验证 ProgramGraph**。下面未逐项运行的标准规则
不能冒称单独 probe 通过；规则来源或与已测基础协议的组合均明确列出。

## 1. 选择与短路

### 1.1 If / IfExp

| AST 与字段 | phase、顺序、绑定及结果 |
| --- | --- |
| `If.test` | 当前执行先 `T(test)`；其异常/挂起先处理，不开始任何 suite。 |
| `If.body` | true 边执行 Suite；使用 test 后态。 |
| `If.orelse` | false 边执行 Suite，空列表即 Fallthrough；elif 表示嵌套 If，仅当前 false 后进入。 |
| `IfExp.test` | 虽源码常写 body 在 test 前，实际先 T(test)。 |
| `IfExp.body` / `orelse` | 仅选中一支执行；值上下文取该支实际引用，条件上下文用 T 对接该支。另一支没有运行值/效果，但保留 source/scope。 |

If 的出口是所选 suite 的 completion；合流只接真实 Fallthrough 前驱，携带各自
binding/state。不能把某分支 Return 后的状态接到普通 merge，也不能将未绑定合流成 None。
IfExp 结果是选择的值，不分配“等价副本”，不得把两个分支的所有输入都当必需运行依赖。

### 1.2 BoolOp(op, values)

`op` 为 `And` 或 `Or`，marker 本身不执行；`values` 按顺序、至少两个。

- And：前项的假边短路，真边才到下一项；Or：前项的真边短路，假边才到下一项。
- 值上下文返回造成短路的 operand 或最后一项的实际值；不会统一转换成 bool。
  最后一项仅为返回值时不额外求真。
- 条件上下文每个需要判断的项按 T 组合，包括最后一项；嵌套短路接续已有控制边，
  不重复求真已经决定该路径的 operand。任一求值/Truth 可 Raise 或 Suspend。
- 未执行项的 Names 不产生运行读取；已经执行的部分状态不因短路回退。

### 1.3 Compare(left, ops, comparators)

`ops` 与 `comparators` 等长且非空；操作 marker 无独立效果。先 V(left)，再按索引
求 V(comparators[i]) 并做对应比较。中间 comparator 的引用同时作为下一比较左值，
不能求值两次。除最后一项外，对比较结果求真，假则停止。

值上下文在中间失败时返回该比较产生的实际结果对象；最后一项返回其实际结果，
不强行 bool 化。条件上下文最后也按协议求真；已短路的比较结果不重复 Truth。
探针确认自定义 rich comparison 的假结果对象可以成为整个链的返回值。

| marker | 具体隐式协议 |
| --- | --- |
| `Eq/NotEq/Lt/LtE/Gt/GtE` | 类型 rich-comparison slot 与反向对应；右操作数为严格子类型时有优先规则；NotImplemented 触发规范 fallback，不是真假值。双方均不实现时 Eq/NotEq 最后按身份 fallback，排序比较 TypeError。返回对象可非 bool。 |
| `Is/IsNot` | 对象身份判断，结果为 bool；不调用 `__eq__`。 |
| `In/NotIn` | 先求 needle，再求 container；执行 container 的 contains 协议。存在 `__contains__` 时调用并求真；否则 iteration/旧 sequence 接口搜索。NotIn 对规范 membership bool 取反。只将 advance 的结束识别为未找到，比较异常传播。 |

membership 的具体容器实现属于同一版本化协议：不能用一条任意 `needle == item`
替代其行为。本机普通 iterator fallback 先比较取到的 item 与 needle，仍受 rich
comparison 子类型优先影响；`comparison_dispatch_and_membership` 已核实。
原生容器可有专用 fast path，必须保留对象/状态及所用协议，不推断为无用户调用。

这些规则的语言依据为 [表达式](https://docs.python.org/3.14/reference/expressions.html)，
实际调用次数的版本证据以上述独立 probe 为准。

## 2. while / for / async for

### 2.1 While(test, body, orelse)

1. 入口直接到 test；每次用最新 carried binding/state 执行 T(test)。
2. true 执行 body；body Fallthrough 或属于该 loop 的 Continue 回到 test。
3. false（包括零次）进入 orelse；Break 直接去 after，不走 orelse。
4. Return/Raise 经介入 cleanup 后向外；如果 cleanup 替换 transfer，按新目标走。

test/body 可 Suspend；continuation 必须保留当前 loop activation 和局部状态。
false 不蕴含 body 没有效果；else 不是“前面没有异常”的任意公共尾块。

### 2.2 For(target, iter, body, orelse, type_comment)

| 字段 | 规则 |
| --- | --- |
| `iter` | 进入 loop 时 V 一次；随后 GetIterator 一次。`__iter__` 必须给 iterator；缺省的旧 sequence fallback 也有状态/异常。GetIterator 的异常不当 exhaustion。 |
| `target` | 每个 Item 后 Store(target,item)；不在获取 item 前执行 target 子表达式。解包/属性/下标写可部分成功后 Raise。 |
| `body` | target 成功后 Suite；Fallthrough/本 loop Continue 到下一次 Advance。 |
| `orelse` | 仅 Advance 的 StopIteration adapter 到此；Break 跳过。目标或 body 抛 StopIteration 向外传播。 |
| `type_comment` | 静态 type metadata/source 归属，不求值。 |

loop target 最后绑定通常保留；零次并不新增绑定，原有值保留，否则仍 UNBOUND。
iterator 与当前 item 的临时引用按实际作用域保留/释放；Continue 不重新求 iterable。
for Break 不自带 `iterator.close()` 的语言调用，不能把释放/GC 与 close 协议混同。

### 2.3 AsyncFor：字段与 For 同名，协议不同

1. V(iter) 一次，再类型的 `__aiter__` 得到 async iterator；3.14 不隐式 await
   `__aiter__` 返回值。返回旧式 awaitable 而非 async iterator 是错误路径。
2. 每次调用 `__anext__`，将其结果交 Await 协议；本次调用或 await 产生的
   StopAsyncIteration 才接 Exhausted。StopIteration 不是 async exhaustion。
3. item 的 Store、body、orelse 与 For 的控制规则相同；target/body 的
   StopAsyncIteration 不被当前 Advance adapter 吞掉。
4. 每个 await 保留 frame/handler/loop 状态并接恢复时共享 state；Break 不隐式
   `aclose()` iterator。异步 generator 的最终化属于另一个生命周期协议。

`asynchronous_iteration` 核实 __anext__ 同步抛终止异常、body 同名异常外传、零次
else 和 break 不调用 aclose。loop/else 的基础依据为
[复合语句](https://docs.python.org/3.14/reference/compound_stmts.html)。

## 3. Comprehension 与 generator expression

### 3.1 精确字段

| AST | 字段及执行点 |
| --- | --- |
| `ListComp(elt,generators)` | generators 形成嵌套迭代；每个通过所有 filters 的组合求 elt 一次，追加实际结果引用。 |
| `SetComp(elt,generators)` | 同上，但插入需要 hash/equality，可调用用户代码并失败；不能只建 elt 数据边。 |
| `DictComp(key,value,generators)` | 每个组合先 key 后 value，再字典插入；重复键处理与 hash/equality 有状态和异常。 |
| `GeneratorExp(elt,generators)` | 创建时处理最外 iter/iterator；其余迭代、filter、elt 到恢复时执行；elt 的值逐次 Yield。 |
| `comprehension.target` | 每个 item 的 Store，属于 comprehension 的迭代绑定 scope。 |
| `comprehension.iter` | 第0项在外层上下文求值/建立 iterator；第 i>0 项在前面各层绑定及 filters 成功后才求值，每次到达都重新建 iterator。 |
| `comprehension.ifs` | 当前 target 成功后按列表 T；首个 false 跳到当前层下一项，后续 filter/内层 iter/elt 均不执行。 |
| `comprehension.is_async` | 编译期 0/1 协议选择，不作运行真值调用；1 用 AsyncFor 的获取/advance-await 规则。 |

### 3.2 scope、phase 与状态

generators 顺序对应外到内；不能先求全部 iter 再进入循环。最外 iterable 表达式
使用外层 scope，所以 `[x for x in x]` 的右侧 x 不是尚未绑定的 comprehension x。
其他迭代变量不泄漏到外层，但它们的赋值/引用生命周期仍存在。

CPython 3.14 的 eager comprehension 可在 enclosing frame 内联，编译器保存/清除/
恢复被遮蔽 slot，异常退出也要恢复；**逻辑作用域不等于新物理调用 frame**。
不能伪造一个实际 function invocation 来解释所有 comprehension。见
[PEP 709](https://peps.python.org/pep-0709/)。

合法 walrus 绑定遵从 enclosing scope 的特殊规则，不成为普通 iteration-local；
在 iterable 表达式中的 walrus、与迭代变量冲突、class scope 等受编译限制，不能
事后按普通 Assign 猜。内部定义的 closure/生成器读取 cell 的时间也与 eager elt 不同。
容器分配/插入、遍历、过滤及销毁未完成容器均有依赖；失败不产生完整容器正常结果。

GeneratorExp 在创建时就求最外 iterable 并建立 iterator，因此这一步可以立即
Raise；内部 body 尚未进入。最外 iterator 存入环境，之后 resume 不重新求它。
其他表达式、内层迭代和对共享对象的读取在恢复时发生；`comprehensions` 已核实。

async comprehension 可 await/async-for；目标编译上下文决定合法性，异步 generator
expression 的创建与 awaitable iteration 仍分开。async iterator 最外 __aiter__ 的
调用在创建阶段，__anext__ 在恢复阶段；独立 probe 已核实。具体 nesting 和允许
位置按 3.14 编译规则检查，不能以 `is_async` 单独决定整个表达式同步性。
[PEP 530](https://peps.python.org/pep-0530/)

## 4. Try / except / except* / finally

### 4.1 Try(body, handlers, orelse, finalbody)

- 先 Suite(body)。仅其 Fallthrough 进入 orelse；Return/Break/Continue 不进入。
- 仅 body 的 Raise 进入 handlers 搜索。orelse 或 handler 的新异常不由这些兄弟
  handlers 再捕获；进入外层异常处理前仍运行当前 finalbody。
- finalbody 存在时，包围 body、handlers 和 orelse 的所有离开路径。进入时保存
  pending completion 与必要 payload/异常引用，使用当下 state。

### 4.2 ExceptHandler(type, name, body)

| 字段 | 规则 |
| --- | --- |
| `type` | 在异常到达且搜索到本 handler 时 V；不是定义时预求值。None 表示末尾 bare except。结果必须是允许的异常类/tuple；非法类型或求值失败产生新 Raise，停止同层搜索。普通匹配不使用虚拟 subclass 规则。 |
| `name` | identifier 字符串，不是表达式；命中后按编译作用域绑定异常引用，并设置当前 handled-exception context。 |
| `body` | 命中后 Suite；出口恢复前一个 handled exception，清除本 as-name（不恢复该名字的旧绑定）。清除的引用释放仍有作用。 |

普通 except 首个匹配胜出；一个 handler 抛的新异常不交给之后 sibling handler。
内层 handler 结束后恢复外层 sys.exception/bare-raise 上下文。异常匹配表达式可以
调用任意代码，不可认为只是读取 class 常量；独立 `try_handler_context` 已验证。

### 4.3 finalbody 的组合，不是普通 frame release

| finalbody 结果 | 规范组合 |
| --- | --- |
| Fallthrough | 保留原 pending variant/target/payload，接 finalbody 后态。 |
| Return / Raise / Break / Continue | 替换 pending；原 payload 释放、异常 context/traceback 和新状态均保留。 |
| Suspend | 保存原 pending、cleanup 栈和恢复位置；恢复后继续 finalbody，尚未恢复原转移。 |
| 无完成 | 不制造返回原目标的边。 |

return 表达式在进入 finally 前已经得到引用，不因 finally 修改其内容而重算表达式。
finally 内新 return 的 payload 则是新的求值结果。3.14 对离开 finally 的某些
return/break/continue 发 SyntaxWarning；warnings-as-errors 也是编译合同，不能一概
将这些构造当正常可执行或语法非法。`finally_and_raise_order` 保留观测。

### 4.4 TryStar(body, handlers, orelse, finalbody)

字段 phase 与 Try 相同，但 handlers 必须用异常组协议；不能复用“第一个匹配结束”。

1. body Raise 形成待处理 group；单个普通异常在需要时包装成适当的单元素 group。
   同时保存原异常树/传播上下文，用于最后重组。
2. 依次求 handler.type；不允许 bare except* 或捕获 BaseExceptionGroup 类本身。
   将当前剩余 group 按类别 split 成匹配子树和剩余子树；保留组层级和元数据。
3. 匹配非空才绑定 name、设置 handled context 并执行 handler.body。正常处理的
   子组被消费；handler 新抛异常或重抛需要暂存，**仍继续处理原剩余组的后续 handler**。
   新异常不作为后续 sibling 的输入。
4. 全部 handler 后，将未处理部分、保留的重抛部分与新异常按规范重组。全部被消费
   才 Fallthrough；否则 Raise 重组结果。不能 flatten 丢掉 group 结构/traceback。
5. type 求值/合法性检查或 split 协议本身失败，不是 handler.body 的暂存异常分支；
   结束当前分派，经 finally 向外传播。每条路径保留已完成 handler 的状态。

**版本细节：本机 3.14.7 即使前一 handler 已消费全部异常，后续 handler.type
表达式仍会求值。** 不能因为剩余组为空就剪掉这些表达式及其失败/效果；空组不进入
后续 handler body。独立 `exception_groups` 记录了 `type-evaluated`。这比语言概述
“处理到全部匹配”为止更细，必须保留实际编译协议。未匹配的裸异常最终仍以裸异常
向外传播，内部包装不能强迫它变成逃逸的 ExceptionGroup。

bare reraising 与显式 `raise subgroup` 可有不同 traceback/上下文，不能仅按异常
对象相同决定重组。自定义 group 的 split/derive 是实际用户调用，可能有状态/失败；
`exception_group_custom_split_and_failure` 已观察。handler name 清除/context 恢复仍适用。

编译禁止通过 return 或外层 loop break/continue 离开 except* handler；**handler
内部新循环的局部 break 可合法**，不能用 AST 后代一律含 Break 就拒绝。
依据 [PEP 654](https://peps.python.org/pep-0654/)；已测首 handler 抛新异常后第二个仍执行，
剩余异常与新异常合并，以及 matcher 失败不进入后续 handler。

## 5. Raise / Return / Break / Continue

| AST/字段 | 精确规则和 typed 出口 |
| --- | --- |
| `Raise.exc=None, cause=None` | bare raise 读取当前 handler exception context；没有活动异常时产生 RuntimeError。按当前 traceback 修改状态重抛，不另造原异常对象。 |
| `Raise.exc` | V(exc)；可为 BaseException 实例或类。类须按异常构造协议实例化；无效对象 TypeError，构造失败传播。 |
| `Raise.cause` | 存在时在 exc 表达式之后 V(cause)，然后执行 raise normalization；本机类形式先构造 exc 再构造 cause。None 设置显式 suppression；其他有效 class/instance 建立 cause。cause 表达式失败时原 raise 尚未完成。 |
| `Return.value` | 存在时先 V，否则使用 None 引用。成功后形成 Return(所属函数边界,引用)，经所有介入 cleanup；表达式异常/挂起不提前形成 Return。 |
| `Break()` | 无运行字段；形成所属活动 loop 的 BreakTarget，经 cleanup 到 after，跳过该 loop else。 |
| `Continue()` | 无运行字段；形成所属 loop 的 ContinueTarget，经 cleanup 到测试/advance；不重新求 for.iter。 |

raise 会更新传播 traceback/cause/context/suppress state；`raise ... from None` 抑制
显示链不等于删除原 context。RAISE 不能只传异常类名。探针确认本机 exc/cause
表达式都先求值，再异常类实例化的顺序。依据
[简单语句](https://docs.python.org/3.14/reference/simple_stmts.html)。

同步普通函数 Return 接这次 caller Host Returned；generator Return 接 iteration
completion；async generator 禁止非空 return。Return 不能跨嵌套函数指向外层。
Break/Continue 的目标由编译作用域与当前活跃 loop 决定；内层 loop 的 else 中
break 可以属于外层。finally 替换目标后必须采用新 target，不能保留原 jump。

## 6. With / AsyncWith

`With(items,body,type_comment)`、`AsyncWith(items,body,type_comment)` 的 items 有序；
每项为 `withitem(context_expr,optional_vars)`。多项等价于逐项进入的嵌套作用域，
不是先求全部 context_expr 再 enter。

### 6.1 一项同步进入

1. V(context_expr) 得到 manager 引用。
2. 按目标解释器特殊方法协议获取 exit 和 enter，保持实际 callable 及 manager。
   **本机 3.14.7 descriptor probe 观测 `__exit__` lookup 先于 `__enter__`**；不是
   任意实例 `manager.__getattribute__` 查询。不得依当前在线说明的列表顺序覆盖此证据。
3. 调用 enter；只有它成功返回后才注册当前 exit cleanup。lookup/enter 失败不调用
   本项 exit，但之前成功进入的外层项仍须清理。
4. optional_vars 非空则 Store(target,entered_value)，其解包/写入失败已在 exit 保护下。
   没有 optional_vars 也须处理 entered_value 的生命周期。
5. 再进入下一项或 body。type_comment 不运行。

### 6.2 退出及抑制

| pending | exit 调用与结果 |
| --- | --- |
| Raise(packet) | 传异常 type/value/traceback；exit 返回后 Truth 一次，真则抑制为 with 后的 Fallthrough，假则继续原 Raise，二者用退出后态。 |
| Fallthrough / Return / Break / Continue | 传三个 None；正常返回后继续原 pending，**不对 exit 返回值求真**。 |
| 任意 pending，exit 或必要 Truth 失败 | 新 Raise 替换 pending，保留 context 与部分效果。 |
| body/exit Suspend | 保存仍待退出的 manager 栈与 pending；并不立即退出其他所有 manager。 |

exit callable 在 enter 前保存，body 重绑 manager 的方法不自动改为新的 callable。
内层抑制后到外层 exit 时，其输入 pending 已改变；内层 exit 新异常则成为外层收到
的异常。`context_manager_protocol` 已测 target 解包失败、return 不求真和异常抑制。
规范组合参考 [PEP 343](https://peps.python.org/pep-0343/)。

### 6.3 AsyncWith

逐字段及嵌套次序同上，特殊方法改为 `__aenter__/__aexit__`；调用先产生 awaitable，
再 Await。aenter await 成功才注册 exit；aenter 调用/等待失败不退出本项。aexit
await 的结果才用于异常抑制。两处 Await 均可 Suspend/Throw，取消按异常协议而不是
假定“资源已关闭”。异步退出的结果不是 GPU/文件 ready 的通用证明。

## 7. Yield / YieldFrom / Await 与可恢复函数

### 7.1 Generator/coroutine 分类与创建

所属代码块含 yield 即有 generator classification，即使该 yield 位于 return 后；
扫描排除嵌套函数/class 的代码块。普通 generator function 调用先绑定参数、创建并
保留 frame/environment，正常返回 generator 对象；不执行 body。async def 也要
区分 coroutine 与 async generator。编译错误不构造虚假的正常 body Region。

### 7.2 Yield(value)

先 V(value)，缺省为 None，然后输出 Suspend(GeneratorYield,exported_ref,continuation)。
保存局部绑定、活临时、求值栈、handler/cleanup 栈和 pending completion；没有最终
Frame EXIT。该次 next/send 的 Host Returned 可以携 exported_ref，而原函数仍暂停。

| 恢复请求 | 当前 yield expression 的后续 |
| --- | --- |
| Next / Send(None) | 表达式结果为 None，继续后面的语句。 |
| Send(value) | 表达式结果是该次实际发送的引用。 |
| Throw(packet) | 从暂停位置产生 Raise，可被包围的 handler 捕获并继续/yield。 |
| Close | 协议性注入 GeneratorExit；遵循 close adapter，而不是普通 send。 |

同步 generator 的状态/请求合同如下；请求参数校验失败不伪造 body entry：

| 状态 | Next/Send | Throw | Close |
| --- | --- | --- | --- |
| Created | Next/Send(None) 首次进入；非 None send 是 TypeError，body 未进入。 | 在启动位置注入异常；没有已进入的 body/finally 来捕获它。 | 不执行未进入 body/finally，关闭并返回 None。 |
| Running | 重入错误，无第二个活动 continuation。 | 重入错误。 | 重入错误。 |
| Suspended | 从保存位置继续，采用本次发送值及当前共享 state。 | 从暂停位置注入，可被 handler 捕获并继续/yield。 | 注入 GeneratorExit；未处理的 GeneratorExit 正常关闭；其他异常外传。再次 yield 是 RuntimeError，实例可仍 Suspended。 |
| Closed | StopIteration；不重新执行 body，也不重新提供上次 return payload。 | 向调用者抛请求异常，不进入 body。 | 返回 None，无新的 body 执行。 |

close 成功不必总返回 None，3.13+ 可返回关闭时 body Return 的值；失败后的实例不能
被统一置为 Closed。`generator_protocol` 已测上述最易混淆的创建、发送、关闭返回、
未启动关闭及 close 失败后 Suspended 边界，表格其余常规路径依据版本化方法规范。

正常 generator Return(value) 在 next/send 边界成为 StopIteration.value。body 自行
逃出的 StopIteration 按 PEP 479 转 RuntimeError；不能按异常名称统一判自然结束。
async generator 有独立 StopAsyncIteration/awaitable iteration adapter；禁止非空
return。anext/asend 的 awaitable 驱动 body，body yield 的 payload 成为这次 await 的
成功值，body 自然完成则成为 StopAsyncIteration；显式从 body 逃出的终止异常另有
RuntimeError 转换。athrow/aclose 创建注入请求，真正 await 才驱动；aclose 的 graceful
结束为成功 None，非法 yield 为失败。不同请求和关闭后态不得共享一个 NORMAL token。
`async_generator_protocol` 确认创建 __anext__ 请求不执行 body、非 None 首次 asend
失败、关闭后 anext 为 StopAsyncIteration，而**本机关闭后 athrow 的 await 返回 None**；
不得把同步 generator Closed/Throw 行无条件套过来。参考
[generator 方法](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)
与 [PEP 479](https://peps.python.org/pep-0479/)。

### 7.3 YieldFrom(value)

1. V(value)，GetIterator；这两步的异常不是 delegated natural completion。
2. 首次 Advance；Item 对外 Yield，Exhausted 的 StopIteration.value 成为整个
   YieldFrom 表达式结果，然后继续父函数。
3. 每次恢复：Send(None)/Next 驱动 next；Send(non-None) 调用 delegate.send；
   缺失/失败按协议传播，不能一律退回 next。
4. Throw：有 delegate.throw 则转交；缺失时在父生成器传播原异常。若被委托方
   正常产 item 再 Yield；其 StopIteration 则完成 delegation，并返回 value。
5. Close/GeneratorExit：若存在 delegate.close，先调用，再在父层继续 GeneratorExit；
   delegate.close 的新异常可以覆盖。调用 close 不同于将普通发送值传下去。
6. delegation 保存 delegate、父 continuation、活引用及每层 handler 状态；真正
   动态调用关系不能仅由词法嵌套推定。父 finally 按自己的 pending 规则执行。

本机 `delegation_and_await` 已测 send、throw、子 finally 和 StopIteration.value
回到父 return；其余分支采用 [PEP 380](https://peps.python.org/pep-0380/) 的规范协议。
`yield from` 在 async def 内编译非法，不能伪装为 await。

### 7.4 Await(value)

V(value) 后验证 awaitable 协议：原生 coroutine/适用 generator-based coroutine 或
类型的 `__await__`；后者须返回合规 iterator，不能把任意 iterable/普通值接受为
awaitable。协议获取和校验本身可失败。

驱动 await iterator，正常中间 yield 形成 AwaitSuspension，对外给 scheduler 请求，
不把该值直接当 Await 表达式结果。scheduler 的恢复值/异常驱动 iterator；其
StopIteration.value 成为 Await 表达式结果，其他异常传播。等待完成可以是零次
suspension。重复 await 已消耗的原生 coroutine、重入和取消均走各自状态协议。

保存 frame 与恢复共享 state 的规则同 generator；scheduler/资源之间的 readiness
需另有 typed adapter。`delegation_and_await` 用手动 send 驱动小 coroutine，证明
创建、第一次 suspension、恢复值与最终返回的区别，没有引入任何应用 backend。
异步扩展依据 [PEP 492](https://peps.python.org/pep-0492/) 与
[PEP 525](https://peps.python.org/pep-0525/)。

## 8. Match 与全部 pattern 类型

### 8.1 Match(subject,cases) / match_case(pattern,guard,body)

先 V(subject) 一次，保留该引用；cases 按源码顺序尝试。对当前 case 先 Pattern；
Match 后才 T(guard)，缺省 guard 即通过；通过才执行 body，body 完成后不继续下一
case。NoMatch 或 guard 假转下一 case；全部失败为 Fallthrough。guard 可有普通
表达式效果/异常/合法 suspension，不能预求值。

capture 的作用域由整个代码块决定，不是临时 case-local。成功 pattern 后即使
guard 为假，已经发生的 capture 和副作用不回滚；后续 case 用更新后的状态。
语言不保证失败 pattern 的部分绑定总保留或总撤销：模型在具体 capture 点记录
binding，后续失败用同一 LocalBindingType 的受约束合流表示前绑定/捕获绑定的
允许结果（可含 UNBOUND），或由目标版本准确 compiler rule 消歧；不是另造一种
BindingChoice 值或把全部失败统一为 UNBOUND。

匹配结果有 Match/NoMatch/Raise 三类；getter/hash/比较等异常通常传播，只有协议
明确的“缺字段/缺键”等失败才 NoMatch。模式类与静态字段必须逐项展开，不能给整个
match 一个 UNKNOWN。规范允许的有限缓存/取值时序选择要逐操作标范围与条件，
不能据此丢掉可能执行的操作。依据 [PEP 634](https://peps.python.org/pep-0634/)。

### 8.2 每种 pattern 的字段合同

| AST/字段 | 求值、匹配和绑定 |
| --- | --- |
| `MatchValue.value` | 合法 literal 或 dotted value expression；到达本 pattern 才求值/lookup，使用 equality 及其真值决定匹配。可有属性/比较调用；同一次 match 内规范允许缓存同值 lookup，缓存必须有具体版本化规则，不能跨 match 推恒定。 |
| `MatchSingleton.value` | 静态 None/True/False marker；与 subject 按身份匹配，不调用 equality。 |
| `MatchSequence.patterns` | 先验证 sequence-pattern 资格，排除 str/bytes/bytearray；长度约束，再提取元素供子 pattern；子 pattern 按顺序匹配，首个不匹配结束。不是对任意 iterable 跑 for。最多一个 MatchStar。 |
| `MatchStar.name` | 仅用于 sequence；有 name 时将中段绑定为新 list，None 为 wildcard 无 binding。前后 fixed patterns 的相对位置保留。 |
| `MatchMapping.keys` | 与 patterns 等长；合格 mapping 和长度条件满足后，按到达顺序求 key 值。字面重复可编译拒绝；动态重复相等 key 产生 ValueError，不是普通 NoMatch。 |
| `MatchMapping.patterns` | 对每个 key 以 mapping 的 `get(key,sentinel)` 规则查值；缺键 NoMatch，不调用 __missing__ 来补值。存在值再进入对应子 pattern；hash/equality/get 的异常传播。 |
| `MatchMapping.rest` | 有名字则构造剩余键值的新 dict 并绑定；没有名字无 rest binding。`**_` 编译非法。剩余项与已匹配项排除涉及 mapping 协议，不是一个无状态 slice。 |
| `MatchClass.cls` | 到达时求 class expression，验证为 type，再做 isinstance 协议；metaclass 的适用调用和异常要保留。非实例 NoMatch。 |
| `MatchClass.patterns` | positional 子 patterns。先依据实际 class 的 __match_args__ 转成属性位置；tuple/string/长度错误 TypeError。有些 builtin 类型采用单一 self-match 规则，不能普遍当第一个字段。 |
| `MatchClass.kwd_attrs` | 静态 attribute-name 字符串，不各自求表达式；与 positional 转换名去重，冲突 TypeError。 |
| `MatchClass.kwd_patterns` | 与 kwd_attrs 对齐；属性提取后按相应顺序匹配。属性访问的 AttributeError 是 NoMatch，其他异常传播；不可默认 property 无效果。 |
| `MatchAs.pattern` | 非 None 时先匹配该子 pattern；成功后才能执行 as binding。None 表示 capture/wildcard。 |
| `MatchAs.name` | 有名字绑定整个当前 subject 引用；pattern/name 均 None 是 `_`，不产生 binding。不是复制内容。 |
| `MatchOr.patterns` | alternatives 按序，首个 Match 成功；失败后继续。所有 alternatives 必须绑定同一名字集合，编译检查；实际来源可不同，不能按名字把 Uses 合并。 |

### 8.3 不能机械按 pattern 子节点求值

本机 `pattern_fetch_before_subpattern` 提供三个反例：即使第一个 literal 子 pattern
最终失败，class 的后一个 property、mapping 的后一个 get、sequence 的后续提取
仍可能已经执行。CPython 的结构提取阶段可先收集多个 subject 部分，再逐项比较；
**“子 pattern 短路”不等于“未匹配到的字段从未读取”。**

版本化模式协议至少将下列步骤分开，保持每一步的 ordered Uses 和可能后态：

```text
类型/资格检查 -> 长度/位置/键/class mapping
              -> 结构提取（可以先取多个部分）
              -> 子 pattern 比较/递归 -> capture -> guard -> body
```

sequence 的长度/getitem、mapping 的 keys/get/hash/equality、class 的
__match_args__/getattr 不是单一纯运算。自定义 sequence 的长度与实际提取不一致
可能产生 unpack 异常，不能全改成 NoMatch。长度/value lookup 是否复用，由实际
协议决定；对标准允许但尚未固定的调用次数，保留受约束的策略选择和 effect 依赖，
不能以一次 probe 推成所有类型唯一次数。Pattern 的失败部分绑定也采用同样的
显式策略范围，非全局“未知整个 match”。

builtin self-match 类型包括 bool、bytearray、bytes、dict、float、frozenset、int、
list、set、str、tuple 的规范规则；适用继承/自定义 __match_args__ 仍须经过实际
class 协议。不可把类名字符串当作判定。compile 还校验重复 capture、不可达的
irrefutable case、OR 名字集合及 star/rest 的合法位置。

## 9. Assert(test,msg)：编译模式是输入

1. 明确目标 compile 的 optimize、继承 flags、解释器版本及 `__debug__` 条件；
   optimize=1/2 的 assert 不运行 test/msg 或异常构造。默认 optimize=-1 取宿主
   配置，不能隐式假设无 -O。
2. 启用时 T(test)；true 直接 Fallthrough，不求 msg。false 才 V(msg)，缺省为
   无参数 AssertionError；msg 失败先传播其异常，不再构造 AssertionError。
3. 使用目标解释器的 assertion-error 装载/构造规则。本机全局名字
   `AssertionError=RuntimeError` 不会改写 assert 抛出的内建异常类型；不能把
   assert 机械改成一次普通 global Name lookup。
4. AssertionError 构造及 raise 的状态/失败仍保留；`assert (x,y)` 的 tuple 是 test，
   不等于 `assert x,y` 的 test/msg。编译警告及 warnings-as-errors 另有编译结果。

被优化掉的 assert 仍保留 source ownership/编译 scope 影响，不能先删 AST 再求
local/cell 分类。`assertions_and_compiler_constraints` 测得 optimize 0 的 test→msg
顺序与 optimize 1/2 零运行事件；这是语言事实，不是 SCAR 常量折叠已通过。

## 10. 类型、完成与分解守恒的审查清单

| 族 | 不能漏的完成/连接 |
| --- | --- |
| 选择、BoolOp、Compare | 选中实际引用、未执行分支、条件求值次数、比较/Truth 异常/挂起和后态。 |
| loop/comprehension | 零次、每条回边、advance 特定终止异常、target 部分写、else、transfer 目标及 iterator 生命周期。 |
| try/raise/with | handler 上下文、匹配失败/新异常、pending 替换/抑制、enter 注册边界、清理顺序和异常后态。 |
| resumable | create/entry 分离、请求实例、保存私有状态与当前共享状态、delegation、终止 adapter、未完成与失败后状态。 |
| pattern | 结构提取和子匹配分开；所有 fields/guards/captures、NoMatch 与 Raise、规范允许策略及 effects。 |
| assert | 编译合同、禁用路径、惰性 msg、实际异常类型装载与失败。 |

数据和 binding 来源可经分支合流；不能因此把资源 ready、host return、语言
completion 或 suspension 当同一种值。协议表解释唯一 canonical Uses/edges，
不会维护第二份前后 world 或独立动态图。

本分册给出了所分配构造全部 AST 字段的 phase 与连接规则，17 组小探针支持易错
边界；未覆盖的具体类型/原生实现通过这里规定的调用/状态接口分解，不能据名字
假定效果。目标版本的可变实现策略必须作为明确的协议选择保留，不能删成纯路径。
这只关闭控制分册的规则草拟缺口，是否通过 M2 要由整体字段守恒、其他分册和
独立审查合并判定；没有推进 M3 建图、M5 闭合或 M6 化简。

### 10.1 明确未作穷尽核对的范围

- 17 组 probe 没有遍历所有自定义 descriptor、容器、metaclass、异常组子类、
  scheduler 或 native 库实现；它们仍有已规定的实际调用/有序输入/状态/完成接口，
  不能猜成无效果，也不能因此把整个外围控制协议隐藏掉。
- Pattern 标准允许的缓存次数、部分失败绑定及实现取值策略，没有被单个样例固定
  成唯一实现。规范保留逐步骤、受约束策略；需要精确运行对应时另绑定 compiler/证据。
- generator/coroutine/async-generator 的所有请求×状态组合没有逐一执行；表内非探针
  项基于规范，不能标“本机逐项实测”。未使用强制线程中断、native fatal error 或
  资源故障注入证明全控制完备；这些属于环境/资源协议的显式边界。
- 在线文档 patch 版本为 3.14.8，本机是 3.14.7；已发现的 lookup/except* 等差别优先
  保留本机证据并限定适用版本。后续换解释器须复核相关规则，不沿用 VERIFIED。
