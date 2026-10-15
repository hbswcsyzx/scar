# N2.b1：循环、局部绑定与 assert 的自动构图

状态：**Proposed；仅设计，尚未实现或验收。**

日期：2026-10-15。起点为 N2.b0 冻结提交 `a6ed118`；336 项 gate 通过只说明
此前范围的证据，不包含本文能力。入口加载证据与展开预算的前置工作见
[AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md)。本提案是循环子任务设计，尚未
实施；后续由代理执行验收。

## 1. 有限目标与前置事实

从普通同步 Python 函数源码自动恢复 `while`、`for`、零次路径、回边、嵌套
`break/continue`、loop `else` 和 `assert`。继续使用 N2.b0 的入口发现、精确
定义位置、每文件共享准备、typed 来源和跨文件候选条件；不要求用户补 IR
或逐参标类型，不以任何项目、函数或库名称选择规则。

支持范围是上述控制结构加当前已支持的表达式、普通局部名称赋值和返回。
`for` target 首批要求单个局部 `Name`；解包、属性/下标写入有独立定位边界。
这不限制迭代对象：参数、调用结果、用户迭代器均走相同 Python 迭代协议。
可达子结构尚不能转换时，保留完整 inventory，body 明确失败；不能把缺失
分支、异常或回边删除后报告完整 body。

`try/except/finally`、`with`、`async for` 和 generator body 在此 gate 后实施。
本门内部处理一次 `next` 的耗尽条件，不等于开放一般用户异常处理语法。

已核对的实现基础：

- `model.py` 已有 BlockArgument、JUMP/BRANCH、NORMAL/RAISE 的 INVOKE，允许 CFG 回边。
- `validation.py` 按 CFG 支配关系检查值可用性；每个 block/出口必须携带全部状态域。
  INVOKE 完成结果只在各自单入边私有后继定义，不能把循环 header 直接当私有完成目标。
- `tests/fixtures/program_graphs.py::loop_state_program` 已验证手工循环 state SSA，
  尚未验证 Python 迭代、局部引用 carry 或自动 loop lowering。
- 当前 lowerer 的环境交集只适用于已绑定分支变量；遇到未绑定局部会拒绝 body。
  `invoke()` 当前立即外抛所有异常，`statements()` 只返回一个正常 cursor，均需改造。
- Region 可以没有退出端口；当前 lowerer 固定声明 NORMAL/RAISE，不能用它推断
  函数终止性，或给无正常退出的循环添加虚构 `return None`。

## 2. 确定的模型选择

### 2.1 保留现有完成类别，增加有合同的协议操作

本门**不增加顶层节点，不增加 BREAK、CONTINUE、EXHAUSTED 或 DIVERGE ExitKind**。

- break/continue 是当前函数内的定向 CFG 转移；循环上下文决定目标和参数。
- StopIteration 是 `next` 的一种异常结果；在该操作的私有 RAISE 后继局部识别，
  可用现有 INVOKE、类型判别、BRANCH 和 JUMP 完整表示。
- 非终止没有完成事件。CFG 环和可能不返回的 Python 协议操作均不能被两个
  完成端口解释为“保证二选一完成”；完成签名只约束**发生完成时**的接口。

新增一个小的、规范性的 typed Python protocol descriptor，连接到 Operation。
它定义以下操作的输入、输出、状态和控制合同；SourceRole/label 只说明来源，
不能单靠这些展示字段授予规则。已有源码 Opcode 继续使用，不重复维护两套
互相矛盾的算子定义。若新增字段，需要 program codec 版本迁移及严格 replay。

| 协议操作 | 必要输入 | 输出/完成约束 |
| --- | --- | --- |
| GET_ITERATOR | iterable 引用、当前 world | NORMAL iterator 引用/后状态；RAISE exception 引用/后状态 |
| ADVANCE_ITERATOR | iterator 引用、当前 world | NORMAL item 引用/后状态；RAISE exception 引用/后状态 |
| MATCH_STOP_ITERATION | exception 引用、当前 world | builtin bool；读取类型所需状态；没有用户名称查询或普通 `isinstance` dispatch |
| BIND_LOCAL | 引用 | Bound 局部绑定值；不是复制 Python 对象 |
| LOAD_LOCAL | 局部绑定值、当前 world | Bound 时取得原引用；Unbound 时产生 UnboundLocalError；分路径保留状态 |
| MAKE_ASSERTION_ERROR | 可选 message 引用、当前 world | 构造 builtin AssertionError 或构造失败异常；message 不预先转字符串 |
| RELEASE_REFERENCE / COMPLETE_FRAME | 被释放的源引用或完整 frame 绑定、当前 world | 保留释放/保留/回调等状态效果；规则不得把值节点消失当作已执行释放 |

规则应绑定到工具支持的 Python 语言/实现配置，源码调用目标仍未验证。
GET_ITERATOR 使用语言的迭代协议，包括适用时的序列协议回退；不能展开成普通
`obj.__iter__()` 名称读取，也不能因函数名叫 `range` 就获得 builtin 假设。
MATCH_STOP_ITERATION 使用协议规定的 builtin 异常类别及其子类关系；用户重绑
`StopIteration` 名称不应改变它。若分类需要对象类型元数据，必须读当前 world，
不能仅因为引用 ValueID 相同就当作类型状态不变。

具体 Python 行为仍未知的调用、truth、iterator 和 next 均不宣称 effects_complete。
coarse world 在每条正常/异常完成边产生各自后状态；异常时不能回退到调用前状态。

### 2.2 局部绑定是一个必要的 Value 强类型变体

推荐增加 `LocalBindingValue` / `ValueKind.LOCAL_BINDING` 以及对应 UseRole：

```text
LocalBinding = Unbound | Bound(Reference)
ValueOrigin 允许 typed UnboundOrigin（只适用于 LocalBindingValue）
其余定义仍为 OperationResult 或 BlockArgument
```

这是不可变的**名称绑定状态值**，不是 Python 对象引用或 StateVersion，也不引入
新的顶层实体。类型用于可能未绑定的局部及其合流/carry；已证明一直绑定的引用
可继续直接使用 ReferenceValue。建议先统一将需要循环 carry 的局部装入此类型，
避免对局部绑定性做路径枚举。

必要性反例：

```python
def last(xs):
    for item in xs:
        pass
    return item
```

循环出口需要同时表示零次时 Unbound 与非零次时 Bound(item)。现有 ReferenceValue
不能表示“没有对象”；用 None、未知引用或未定义 producer 占位均会造假。把每个
可选绑定拆成全套路径会随变量和嵌套循环增长。本变体复用现有 SSA 的有限合流，
并让 LOAD_LOCAL 的 UnboundLocalError 与依赖可检查。

约束：

- Unbound 不能经过 REFERENCE use、当 Python 参数或作为正常返回对象。
- BIND_LOCAL/LOAD_LOCAL 的对应关系由 typed 协议校验；普通操作不能伪造精确 Bound。
- STORE 更新的是当前环境映射。若旧绑定可能存在，其释放需要显式生命周期操作；
  不能无条件加载旧绑定，使一次合法首次赋值额外产生 UnboundLocalError。
- 合流不自动检查绑定性；只有执行读取时检查。循环结束但从不读取目标的零次路径合法。
- 绑定值、phi/block arguments、循环 carry 不引入额外 Python retain/release；它们
  表示源程序已有绑定。不可把 IR 参数个数解释为运行时引用计数。
- 仍用 symtable 确定本函数全部局部，包含不可达 import/del/except 等编译期绑定。
  closure/global 可写槽的详细模型继续是明确边界。

### 2.3 编译配置必须显式进入 assert 接口

增加 typed 编译配置记录及自动生成的环境端口角色。`__debug__` 对应 builtin bool，
绑定于**该函数的代码版本/编译配置**；它不是普通 global lookup，不是用户 Python
形参，也不能取 SCAR 进程自己的 `__debug__` 或 `sys.flags.optimize` 作为目标事实。

- 默认未知目标编译配置：入口自动带 `COMPILE_DEBUG` 的 bool 环境参数，保留开启和
  关闭 assert 的两条路径，不要求用户逐参声明。
- 显式给定 optimize 0/1/2 的 source profile：可按合同固定该值，但报告仍保留
  “实际 code object 与配置相符”未验证条件。不能把条件升级为运行事实。
- 其他依赖 `__debug__` 的源码表达式读取同一端口。未知配置必须在整个 body 一致。
- 不同函数可能来自不同编译配置；不能盲目把 caller 的 COMPILE_DEBUG 传给 callee。
  CandidateArgument 必须区分 Python 参数与环境端口；未绑定候选环境时，接口映射
  明示不完整，不能假造实际 Python 调用参数。已知 core callee 仍遵循完整 typed 接口。
- 配置、环境端口来源、假设及支持的 Python profile 进入持久化和重放。环境端口
  不是可由报告自行添加的证据。

## 3. 自动构图算法

### 3.1 两阶段建立 loop 接口

先扫描本函数作用域内的局部定义/读取，跳过嵌套 def/class/lambda 的独立绑定范围，
为循环建立稳定的 carry 参数列表。第一版携带该循环范围内相关局部的保守超集，
不在本门做最小 liveness 优化；每个局部有固定位置和类型，world 始终单独完整携带。

再创建 preheader、header、body、自然耗尽/条件失败、break exit、最终 join 等块，
先声明 block arguments，后填逐前驱绑定。不能先把回边的值视为 header 前已定义。

`statements()` 改为收集结构化流出结果：正常 cursor 与向当前循环上下文登记的
break/continue 转移。return/raise 结束该路径。使用循环栈选择最近循环，保留每条
实际前驱边和环境；不能只用一个共享 bool 表示“发生过 break”。

### 3.2 while

```text
preheader -- carry --> header: 求值 test -> truth
                              | true            | false
                              v                 v
                            body             loop else
                              | fallthrough/continue
                              +---- carry ----> header
body break ---------------------------------> after-loop join
loop else fallthrough ----------------------> after-loop join
```

test 的表达式和 truth conversion 每次到 header 都重新执行，包含首次检查；
continue 不能跳过下一次条件求值。它们可能产生效果、抛异常或不终止。false 路径
使用最后一次条件检查的后状态，不能使用进入循环前的 world。

### 3.3 for

```text
preheader: 求值 iterable（一次） -> GET_ITERATOR（一次） -> header
header: ADVANCE_ITERATOR
          NORMAL(item,Snext) -> target store -> body -> header
          RAISE(exc,Sraise)  -> MATCH_STOP_ITERATION
                                 true  -> 耗尽清理 -> loop else
                                 false -> 异常退出清理 -> 函数 RAISE
body break -> 当前循环清理 -> after-loop join（跳过 else）
```

每个 INVOKE 的 NORMAL/RAISE 先进入各自私有块，再 JUMP 到共享 header/出口。
用户 iterator 的内部变更属于 world；iterator 引用可以 carry，不证明对象内容不变。
target 只在 next 正常产生 item 后赋值，零次循环保留原 target 绑定或 Unbound。

StopIteration 分类范围严格限于本次 ADVANCE_ITERATOR 的异常：

- GET_ITERATOR 抛出的 StopIteration 是函数异常，不能当作空循环。
- body、target store、条件、message、普通 call 抛出的 StopIteration 均不能当耗尽。
- next 已修改 world 后抛 StopIteration，else 看到修改后的状态。
- StopIteration 的 return/value payload 不是 for 的最后一个 item；不能接入 target。
- 迭代器无限产出或 next 本身不返回均允许非终止，不能凭有限测试推断迭代次数。

### 3.4 break、continue、else 与嵌套

break 到**当前循环**专有出口，绕开该循环 else；continue 到当前循环 header。
内层 break 不得跳过外层后续语句或外层 else，内层 continue 不得重新执行外层
iterable/GET_ITERATOR。自然终止且零次也执行 else；return、外抛异常不执行 else。

loop else 中的 break/continue 按 Python 编译期上下文解析，不能误绑定到已经完成
的自身循环；非法源码由编译期符号/语法检查拒绝。外层存在时须有专门反例。

### 3.5 assert

```text
COMPILE_DEBUG false ------------------------------> after-assert
COMPILE_DEBUG true -> 求值 test -> truth
                                  true ----------> after-assert
                                  false -> 按需求值 msg
                                        -> MAKE_ASSERTION_ERROR
                                        -> RAISE
```

关闭时 test 和 msg 均不执行。开启时 test/truth 的异常直接外抛；仅判断失败才求值
msg，msg 自己的异常直接外抛而不包装成 AssertionError。无 msg 与一个 tuple msg
要保留不同参数接口，不可拆包或预先 `str(msg)`。AssertionError 类来自协议规定
的 builtin 机制，不能用模块中同名变量替换；对支持的 Python profile 实测核对。

### 3.6 生命周期与 frame 边界

所有新控制路径都保留相应的 world 和源程序持有引用。至少覆盖：loop target
重绑定、丢弃的表达式临时结果、迭代器在耗尽/break/return/raise 的退出处理、
被消费的 StopIteration，以及正常/异常 frame 完成。

- break 不自动调用 iterator.close；释放一个源引用也不等于对象一定析构。
- 不能在回边释放仍由 target/其他局部持有的 item；不能让 IR 中保留旧 Value
  自动延迟源语言本应发生的引用释放。返回值在 frame 完成期间保持可用。
- COMPLETE_FRAME 显式消费当前绑定/结果或异常/world；异常 traceback 或外部
  frame 引用可能保留局部。不可无条件把异常退出翻译成“立即销毁全部局部”。
- finalizer、weakref callback、unraisable hook 可能产生可观察效果；析构异常不能
  直接伪装成普通 Python 调用者会捕获的 RAISE。释放操作也可能不终止。
- 本门保留 opaque 生命周期操作和 `FRAME_EFFECT`/profile 条件，不宣称恢复了
  引用计数、GC、traceback 保活或精确析构时机。涉及这些规则的化简仍未授权。

## 4. Validator、查询与重放的必要改动

1. LocalBinding 强类型、UnboundOrigin、协议端口签名、编译环境端口加入严格 codec；
   反例必须同时经过构造校验、graph validation 和 source replay。
2. 保持逐实际前驱 arity/type/use 绑定、CFG dominance 和所有块的 world state SSA。
   header 初始/回边合流允许循环；值的定义、region 归属仍唯一。
3. source validator 检查 loop 的 header/continue/break/else 目标及协议来源；
   通用 core validator 检查结构，不能凭“图合法”证明源码控制流恢复正确。
4. 完成边仍私有，next 结果/异常禁止跨完成路径使用；StopIteration 分类必须对应
   当前 next 的异常值及后状态。不能接旧异常、旧 world 或 body 异常。
5. 出口声明按实际构建的接口确定，不为满足 NORMAL/RAISE 模板创建虚构终止路径。
   闭合非终止 SCC 合法；查询使用 visited/fixed-point，不能递归展开成无限 DAG。
6. loop carry、隐式 protocol 操作均有 typed 原因和 source span；AST atom coverage
   不因多个派生操作重复计数。unsupported target 与内部边界不能被 CONNECTED 遮蔽。
7. 构造操作预算包括失败/回滚工作；循环构图成本取决于源码块数，不按推测迭代次数
   展开。assert 未知配置增加的路径及生命周期操作同样消费预算。
8. 持久化修改 carry、loop 目标、协议类型、debug 配置、消息路径、状态或来源必须
   replay 失败；继续检测源码漂移和新增 import 候选。旧报告迁移不能补造新事实。

## 5. 分步实施顺序与停靠点

| 步骤 | 交付与依赖 | 此时可以声称的范围 |
| --- | --- | --- |
| B1.1 | typed LocalBinding/协议/编译配置端口；codec/validator；通用小 IR 反例 | 新接口合法性，尚非源码支持 |
| B1.2 | cursor 流出集合、loop 栈、header 参数预声明、unbound load、生命周期接口 | 可承载分支与循环，保持 N2.a/b0 回归 |
| B1.3 | assert 自动转换、未知/明确编译配置、惰性 msg 与异常 | assert 有条件模型；不宣称 live optimize flags 已知 |
| B1.4 | while 零次/回边/continue/break/else/嵌套与无正常退出 | 通用 while 自动图 |
| B1.5 | GET_ITERATOR/NEXT、局部 StopIteration 路由、for 生命周期 | 通用迭代控制，单 Name target |
| B1.6 | inventory/replay/预算集成、自动外部源码压力、完整本门验收 | 本文有限 gate；随后再开 try/with 门 |

各步骤可分提交，但 B1.3 单独通过或某个外部函数能转图不算 N2.b1 完成。
若遇模型反例，修订类型/接口并保留失败证据；不把本门关键循环路径移出验收表。

## 6. 可执行通用验收清单

每个正例从临时真实 `.py` 自动构图，不能用手工修图替代源码 gate。使用测试专属
Python 对象记录事件和结果，作为独立期望；针对图查询检查执行许可、依赖和状态。
本门不引入图执行 backend，也不执行 LeWM 模块/函数。非终止验证查图，禁止运行
无限循环；需要运行的迭代器均使用有限序列或受控异常。

| 组 | 最小正例/对照 | 必须查询及负例 |
| --- | --- | --- |
| while 零次 | `while pred(): x=step(x)`，初始 pred=False | body 不执行；test/truth 后状态进入后续；删首次判定拒绝 |
| while 回边 | pred/step 带 event log，至少两轮 | 条件每轮一次；carry 用新绑定/新 world；接旧版本拒绝 |
| 未绑定 | `for x in xs: pass; return x`，xs=[]/[v] | 零次 UnboundLocalError/非零原引用；禁止 None 占位或空列表强制一次 |
| 旧目标 | `x=sentinel; for x in xs: pass; return x` | 零次返回原引用；非零最后一项；body 从不读取时不制造 unbound 异常 |
| 引用 carry | `for x in xs: y=x; ...; return y`，含 `y is x` 与分支赋值 | 无值复制或虚假身份精度；逐前驱绑定/读取位置正确 |
| for 协议 | iterable.__iter__/iterator.__next__ 记录事件；对象覆盖序列回退 | iterable/iter 一次，next 每轮及最终耗尽一次；不能改普通属性 dispatch |
| next 状态 | next 先记日志再 StopIteration；loop else 读取日志 | 耗尽后状态保留；异常回退前态拒绝 |
| 异常界线 | __iter__ 抛 StopIteration；next 抛 ValueError；body 抛 StopIteration | 仅 next 的 StopIteration 走耗尽；错误类型/错误来源 catch 拒绝 |
| break/else | 空序列、自然耗尽、中途 break 三种 | 前两者执行 else；break 绕过；把 break 接 else 拒绝 |
| continue | 中途 continue，含 while 条件/for next 计数 | 到当前 header；不得重做 GET_ITERATOR 或跳外层 header |
| 嵌套 | 内层 continue/break；外层 else；loop else 内合法外层转移 | 每条转移最近有效循环；内层 break 不代替外层 break |
| 退出 | loop 内 return、协议异常、body 异常 | 不运行 else；清理顺序/最新状态；返回值与异常路径不混 |
| 非终止 | `while True: pass`；无限 iterator 的源码图 | 有有限 CFG 环；无伪造正常完成；closure 查询终止，不作总性证明 |
| assert 开关 | 同一源码以 compile optimize=0/1/2 的测试函数对照 | optimize>0 无 test/msg 事件；unknown 配置有两个受控路径 |
| assert 惰性 | test True/False/raises；msg factory 记录事件或 raises | msg 仅 False；msg 异常不包装；提前求值或错连异常拒绝 |
| assert payload | 无 msg、tuple msg、带 __str__ 的 msg、重绑 AssertionError 名称 | 保留构造参数；不预先格式化；不使用同名全局替换协议类型 |
| 生命周期 | 带可记录 finalizer 的 iterator/item、共享引用、loop break | 不隐式 close；释放依赖显式；共享引用不等同立即析构 |
| 作用域 | 不可达 import/del、nested def/lambda、未绑定分支 carry | symtable 不回退；不把内层局部当外层，未支持仍定位 |
| 覆盖/预算 | 多文件、多 body，循环后另有 unsupported statement | 不藏后续 gap；prepare 每文件一次；失败成本扣共享预算 |

额外 schema 反例：Unbound 当 Reference、carry 参数重复/漏传、continue 用上一轮
state、正常 item 供异常边使用、两个完成共享 header、伪造 precise alias、把
COMPILE_DEBUG 当普通可变参数或替换为 SCAR 自身旗标，均应拒绝或留下明确失败。

验收证据至少包括：冻结 revision、命令/解释器、正反例结果、失败前与修复后记录、
源码覆盖/图接口查询、构造成本、persist/replay，以及尚未实现的边界。代理自行
对照清单逐项验收；不会把确认工作交给用户。

## 7. 自动 LeWM 源码重建查询

复用 N2.b0 相同入口、项目边界和预算，默认只读源码，不 import 目标。
按精确路径和位置比较 b0/b1 报告，查询：

1. 发现文件/定义/atoms 是否完整且身份稳定；新增规则不能改变 source coverage 的分母。
2. assert/for/while 的总数、转换数、具体失败位置；同一 body 内最早阻断消失后，
   后续新的 unsupported 边界是什么。分别报告 inventory 与完整 body 成功数。
3. 每个成功 loop 的零次、回边、break/continue/else、异常和 carry 接口是否可查；
   每个 next 的 StopIteration 分流是否局限本次操作，world 是否逐路径推进。
4. assert 的 COMPILE_DEBUG 来源/条件、惰性 msg 和异常路径；不得以工具当前配置
   把全部 assert 消失当作覆盖提升。
5. 子图或 body 重用是否保留每个调用实际端口；跨文件 witness 仍只是有条件候选，
   不因循环重复调用而提升为同一运行 callable/相同结果。
6. 每文件 prepare 次数、构造/保留操作数、body 数、报告体积、耗时和预算耗尽位置；
   原有 336 gate 中相关项及本门测试必须回归，必要时再执行冻结集成 gate。

不以 LeWM 中恰好使用的名称、Tensor shape 或循环常量增加捷径。若目标循环的
解包 target、状态写入或调用签名仍阻断，报告该通用边界，保留完整 inventory；
不能宣称已得到完整 solver/policy/world-model 执行图或加速。

## 8. 本门完成后仍未解决

细粒度 Tensor/对象/文件/RNG 状态写入、alias/footprint 及覆盖写规则；一般 Python
dispatch 和 live callee 确认；defaults/装饰器/closure 的完整调用接口；try/finally/
with 的异常优先级与清理；精确 frame/GC/finalizer 生命周期；并发、GPU stream/ready、
autograd、执行次数/终止性证明、缓存合法性与优化收益，均不因本门而成立。

本门增加可检查的程序控制和依赖，不授权删除循环、assert、异常或效果，也不增加
运行 backend。N3 化简必须继续以完整观察根、明确合同和单独证据为前提。
