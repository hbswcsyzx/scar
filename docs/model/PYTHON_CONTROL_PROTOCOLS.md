# Python 3.14 静态控制协议

本文件规定静态图应表达的控制语义，非完整 lowerer 支持声明。
统一实体见 [MODEL](../MODEL.md)，构造范围见[协议目录](../PYTHON314_PROTOCOL_CATALOG.md)。
CFG、完成端口与状态引用同一 canonical Region/Operation/Value，不另建控制事实权威。
动态控制可以作为条件路径静态表示；不生成 Invocation、实际循环次数或运行选边。

## 1. 表达式、CFG 与出口

表达式接口返回符号结果及后态，保留正常、异常与合法挂起出口；不默认表达式纯。
语句只沿 Fallthrough 进入下一条；Return/Raise/Break/Continue 经介入 cleanup 转发。
合流携带各前驱的绑定与状态；未绑定不补成 None，已 Return 的分支不接普通 merge。
Unknown 条件保留所有合法分支；静态不可达仍须参与语法、scope 与函数种类检查。
循环和递归以 CFG 回边/Region 引用表示，不靠执行或无限复制节点展开。
临时引用、异常 packet、iterator 和 pending payload 的生命周期仅保留语义必要依赖。
不将编译器 staging、验证器步骤或解释器 frame 管理强制变成目标计算节点。

## 2. 条件与短路

Truth 可调用 `__bool__` 或 `__len__` 并抛异常；结果和值对象的引用分开。
If/IfExp 先判断 test，仅对应条件边进入 body/orelse，IfExp 返回选中表达式的值。
BoolOp 的 and/or 按顺序短路；值上下文返回选中 operand，不统一转成 bool。
直接条件上下文使用条件 continuation，不重复求真已经决定本次分支的 operand。
例如 if a and b 与先保存 a and b 再判断该变量，不保证 Truth 次数相同。
条件上下文的 not 交换真/假边；值上下文仍产生 bool 结果。
Compare 逐项求 comparator，中间值只求一次并供下一比较使用。
中间比较结果求真失败则停止；最终比较结果在值上下文不额外转 bool。
比较、membership 和 Truth 可有 effects；未执行分支不产生无条件值读取或写入。
Assert 遵循 optimize/`__debug__` 配置，message 只在失败路径求值；编译删除与运行失败分开。

## 3. 循环

While 的入口和回边到 test；使用当次符号 carried bindings/state，保留零次路径。
For 的 iterable 与 iterator 获取在循环入口处理；每次 advance 再接 target store 和 body。
只有 advance 的 StopIteration 适配成 Exhausted；target/filter/body 的同名异常不吞掉。
Continue 到所属循环的 test/advance，Break 到 after；只有正常耗尽/条件假才进入 else。
目标 store 可部分失败；零次迭代不凭空建立绑定，迭代后的最后绑定按作用域保留。
Break 不自动调用 iterator.close；引用释放与显式关闭是不同协议。
AsyncFor 用 `__aiter__`、`__anext__` 与 Await；StopAsyncIteration 仅在相应 advance 边成为结束。
异步循环保留 await 的正常/异常/挂起路径，不能把未知调度结果写成已完成。

## 4. 推导式

List/Set/DictComp 由外到内建立迭代 Region；前层 target 与 filters 成功才求下一层 iter。
每个 filter 按顺序短路；只在全部通过后求元素或 key→value 并插入容器。
set/dict 的插入还包含 hash/equality 与异常；不能仅保留元素数据边。
最外 iterable 使用外层作用域；迭代绑定不泄漏，walrus 遵循单独的 containing-scope 规则。
内联 comprehension 的 slot 保存/恢复表示词法隔离，不凭空创建函数调用或实际 frame。
异常退出也保留局部绑定恢复与已发生效果；失败不产生完整容器正常结果。
GeneratorExp 创建时处理最外 iterable/iterator，其余迭代、filter、元素属于 lazy body。
创建引用与消费/escape 分开建模；未知消费者不应让已知 lazy body 定义消失。

## 5. Try、handler 与 finally

Try body 只有 Fallthrough 进入 else；该组 handlers 只处理 body 异常，不捕获 else/handler 的新异常。
异常到达且搜索该 handler 时才求 type；按源码顺序匹配，非法 type 或求值失败向外传播。
普通 except 选首个匹配项；匹配可调用协议，不能预先当作无副作用类名比较。
命中后绑定 as-name、切换 handled-exception context；离开时清除名字并恢复外层 context。
清除不恢复名字旧值；bare raise 读取当前异常状态，未处理异常时有自己的失败路径。
finalbody 包围 body/handlers/else 的离开路径，保存 pending completion、目标与 payload。
finalbody 正常完成就转发原 pending，使用 cleanup 后态；新控制转移替换原 pending。
return 表达式在进入 finally 前求值，不因 cleanup 修改状态而重算；新 return 有新 payload。
finalbody 挂起时保存 pending 与 cleanup 位置，不提前完成原转移。
异常保留 exception/traceback/cause/context 与已发生的后态；不猜 traceback=None 或隐式回滚。
raise 的 exc、cause 表达式和异常规范化按版本规则有序连接，from None 不等于删除原 context。

## 6. 异常组与作用域转移

TryStar 将异常组依 handler 顺序 split，匹配子组进入 body，剩余子组继续分派。
handler 的新异常和重抛暂存，不能作为后续 sibling 的匹配输入；最后按协议重组。
保留 group 层级、traceback 和自定义 split/derive 调用；matcher 自身失败直接向外传播。
不能仅因剩余组为空删除后续 type 表达式；目标版本的求值规则仍要保留。
except* 的非局部 return/break/continue 限制由编译作用域判断，不误拒内部循环的局部 break。
Return 指向所属函数，Break/Continue 指向所属循环；嵌套定义不能跨越这些边界。
所有合法跨 cleanup 转移都携带原 payload/状态，不能用普通 jump 绕过清理。

## 7. With 与 AsyncWith

多项 With 是按顺序进入的嵌套作用域，不先求完所有 context_expr。
每项先求 manager，再按目标版本的类型级特殊方法规则获取 exit/enter；不可替成任意属性查找。
CPython 3.14 的既定展开保留 exit 先于 enter 的查找顺序；保存所选 callable 与 manager。
enter 成功才注册本项 cleanup；optional_vars 的 store 已在其保护下，失败仍须 exit。
退出逆序：异常路径传 type/value/traceback，对 exit 结果求真并决定抑制或继续传播。
普通离开、return、break、continue 传三个 None，不因 exit 返回值为假改变原转移。
exit 或必要 Truth 抛异常时替换 pending；内层改变后的 pending 再传给外层。
进入失败不退出本项，但已进入的外层项仍清理；body 重绑方法不替换已保存的 exit。
AsyncWith 对 aenter/aexit 的调用结果执行 Await；成功进入、抑制与取消仍是条件路径。

## 8. Generator、coroutine 与异步驱动

生成器函数调用返回引用，body 首次驱动才进入；coroutine/async-generator 也有独立创建与驱动阶段。
源图保存一份 body Region 和入口环境/参数，不把创建当作 body 执行或复制每次 resume。
Yield 形成 Suspend：导出值、保存必要局部/cleanup/异常上下文及恢复端口。
恢复输入与保存值分开；共享状态取恢复路径上的当前版本，不冻结到创建时。
Next/Send/Throw/Close 是不同驱动接口，可拒绝请求、转交 delegate、恢复 body 或完成。
YieldFrom 保留 delegation 的 send/throw/close、StopIteration.value 与异常适配。
Await 保留 `__await__`、迭代/驱动、正常结果、异常及取消；不等同 GPU 或文件 ready。
body Return、body Raise、Suspend 与 driver 的 host 结果分开，PEP479 等转换属具体协议。
async-generator 的 yield、驱动 awaitable 和终止协议不能套用普通 generator 的返回规则。
静态只连接可能的 resume successors 与条件，不制造实际 suspension generation 或已发生的连续性。

## 9. Match 与模式

subject 只求一次，cases 按顺序尝试；匹配成功后才判断 guard，通过才进入 body。
sequence/mapping/class pattern 保留资格、长度/键/属性提取、子匹配、capture 和异常。
结构提取可先读多个部分；前一子 pattern 失败不证明其他字段未读取。
value/class 表达式、`__match_args__`、属性、get/hash/equality 可调用用户协议。
属性 AttributeError 等指定失败可成 NoMatch，其他异常依规则传播；不把全部错误改成失败匹配。
OR 分支绑定名集合、重复 capture 和不可达 case 由编译规则检查，失败部分绑定保留允许的策略。

## 10. 待实现边界

完整 except*、pattern、async/delegation 及其任意嵌套组合仍须逐项实现，不能由同名标签认定支持。
已有局部 Try/With/generator 能力不等于所有出口、cleanup 与恢复端口均已闭合。
未实现构造保留来源、合法前缀和缺失关系；未知条件保留分支，不吞掉操作。
数据绑定见[数据与定义协议](PYTHON_DATA_DEFINITION_PROTOCOLS.md)，资源完成见[资源协议](RESOURCE_PROTOCOLS.md)。
