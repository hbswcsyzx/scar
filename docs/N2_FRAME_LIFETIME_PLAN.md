# C0：返回引用与 frame 生命周期依赖

日期：2026-10-15。状态：**Implemented，冻结自验中；外部 F4 尚未验收**。

本文件细化 [N2_CALL_COMPOSITION_PLAN.md](N2_CALL_COMPOSITION_PLAN.md) 的 C0。
下文保留设计与验收要求；当前实现见 [N2_FRAME_IMPLEMENTATION.md](N2_FRAME_IMPLEMENTATION.md)，
不以实现存在代替各门通过。沿用
[CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md) 的 Operation、Value、StateLocation、Region；
本门不增加 detector、backend 或工作负载名称规则。

## 1. 当前断点与本门目标

当前 `program_lowering.py` 的局部 Name 读取已经复用原 ValueID；普通 `y = x`
也保留该引用。但 Return 分支再次调用通用 `invoke()`，正常完成用
`CompletionResult(0)` 产生一个未知 ReferenceValue，随后返回它。因此普通
`return x` 尚不能通过核心图得到“正常返回引用来自当前 x”的关系。

退出效果也未闭合：返回处的 opaque 操作只消费 payload 与 world；未使用的
形参、仅在部分分支绑定的局部及表达式结果丢弃没有完整的生命周期依赖。
普通表达式 invoke 的异常分支直接 `finish_exit()`，没有独立的 frame unwind。

本门交付两个同时成立的结果：

1. 在明确的源码规则与未证条件下，正常返回 payload 保留原引用来源。
2. frame 持有、替换、丢弃及退出仍有完整的保守状态依赖，不因引用相同被删除。

引用身份相同不表示内容相同、无副作用、已释放、必然完成或允许缓存。
结果身份查询与效果依赖查询必须分别报告；观察根仍包括后状态和完成方式。

## 2. 有限支持范围与未证条件

### 2.1 支持范围

新 frame profile 仅建模已完成参数绑定的普通同步函数体：沿用现有表达式、
普通局部 Name 绑定、Expr、Pass、If、显式及隐式 return，并承接普通表达式
invoke 的异常完成。定义时默认值、装饰器及实际调用绑定仍属于独立接口。

本门继续整体拒绝尚未支持的 try/finally、with、del、显式 raise 的完整协议、
closure/nonlocal、generator/async 及循环。遇到这些边界不得保留一个声称完整的
部分 body 图。源文件中的其它函数仍可独立建图，不要求整份源码属于该子集。

### 2.2 NO_FRAME_INTERPOSITION

新 profile 必须携带显式、强类型、**未证明**的 `NO_FRAME_INTERPOSITION` 条件，
并保留标准函数局部作用域等既有条件。其准确范围为：

- 活动 frame 的普通局部槽不被外部 frame/locals 接口修改；
- 执行位置、返回 payload 或 pending completion 不被 tracing/profiling 等机制改写；
- frame 转移期间没有未建模的异步异常注入或观察钩子异常替换完成方式。

条件的名字不能代替上述定义，也不能由解析成功、code 匹配、一次 trace 或
用户没有显式启用某选项而自动升为已证明。依赖这些规则的查询要保留条件，
报告不得因此授予变换权限。

普通 finalizer 对对象、全局或外部状态的修改不被此条件排除，而由 coarse
world 保守承接。允许 frame 逃逸并继续被持有；禁止的是未建模的活动 frame
干预，不能把“frame 逃逸”偷换成“所有局部已经清空”。

## 3. 规范依赖与 FrameModel 对应层

### 3.1 核心图继续是唯一依赖来源

frame 转移使用普通 Operation 与 StateAccess：

```text
引用 uses + 当前 world S
    -> frame transition
    -> 新 world S'

StateAccess.mode          = READ_WRITE
StateAccess.full_overwrite = False
StateAccess.before        = 当前 STATE_CONTENT use
StateAccess.after         = 本操作产生的新 StateVersionValue
effects_complete          = False
```

操作使用适当的 READ、WRITE、MEMORY 行为类型。coarse world 继续包含 Python
与外部状态，本门明确将当前 frame 持有关系及相关生命周期效果包括在内。
不用新 location 名称推导与其它 world 不相交，不引入独立的 effect token。

操作的静态出现属于一个 body；动态持有关系属于一次 invocation。递归或两次
调用不得因为共享 RegionID、OperationID 或 ValueID 而共享一个运行 frame。

### 3.2 强类型 FrameModel

新增 typed `FrameModel`，作为版本化源码规则与核心图的对应层。它引用 body、
源码锚点和已有 OperationID/UseID/局部 slot；不能另存一份实际 def-use、状态
前后值或控制边。查询始终从被引用的核心记录取得这些依赖。

FrameModel 至少区分以下 typed transitions，不靠操作 label 字符串识别规则：

| 转移 | 必需对应 | 规则 |
| --- | --- | --- |
| ENTER | body、全部 formal slot 到引用 UseID 的对应 | 把已经绑定的各形参持有关系接入 frame/world |
| BIND | 当前 body 的普通局部 slot、assigned UseID | 先取得新引用，再替换槽位；旧引用释放效果进入后态 |
| DISCARD | 当前表达式结果的引用 UseID 与源码锚点 | 结束该次表达式临时持有，不删除同对象的局部绑定 |
| EXIT | frame 转移 OperationID、最终完成 OperationID、payload UseID | 保留 pending completion 的种类和 payload 引用 |

EXIT 的 NORMAL/RAISE 必须由所引用的最终终结器核对，不维护第二套实际出口。
同样，before/after world 从 StateAccess 和最终出口 uses 取得，不允许 overlay
与核心各自保存并解释一个不同的状态链。

FrameModel 的覆盖、槽位和 use 角色由同一源码快照的重放校验。它只能说明这些
核心连接符合某个条件化源码规则，不能自行证明运行条件成立、实际 callee、
引用内容、finalizer 目标或 effects_complete。

### 3.3 持有关系不按对象身份去重

ENTER 必须覆盖全部五种 formal 槽，包括函数体未读取的形参。它记录已经存在的
绑定，不表示再次执行参数绑定、再次分配 frame 或额外增加一次运行引用计数。

两个槽位或临时持有即使最终引用同一对象，也仍是不同的使用/持有位置。
`x = x` 必须先取得新持有再释放旧持有，不能先销毁对象。DISCARD 只处理表达式
临时持有，不能因为它和某个 local 的 ValueID 相同就删除该 local。

所有普通 Name 绑定都更新 world，包括首次赋值。If 合流必须按真实前驱携带
world；仅在某个分支存在的局部持有因此仍在状态链内，即使普通 env 合流不保留
该名称。不能只在函数末尾枚举 `cursor.env` 来代替生命周期依赖。

表达式内部的临时持有及失败清理仍包含在该表达式的 opaque 效果内；其正常结果
由随后的绑定、丢弃或返回规则承接。不能把所有 Expr 的丢弃效果推迟到函数退出。

## 4. 完成保持与退出状态

### 4.1 正常返回

返回表达式求值一次，先得到 payload 引用与求值后状态，再进行退出：

```text
evaluate expression -> p, S1
frame EXIT(normal, held p, S1) -> S2
RETURN(p, S2)
```

frame EXIT 是普通非抛出状态操作，不生成一个新的 payload ReferenceValue。
最终 RETURN 使用自己的 UseID 引用原 p 的 ValueID，并消费 S2。
这不需要新增完成类别、引用值变体或 INVOKE 私有完成块。既有分支端口仍按
逐前驱绑定查询，不能无条件合并不同路径返回的引用。

裸 return 和隐式 fallthrough 同样先取得 None payload，再执行退出转移。
输出引用在整个转移期间必须保持可用；不能把准备返回的对象当作已丢弃临时。

### 4.2 表达式异常与 unwind

```text
expression INVOKE RAISE -> e, S1
frame EXIT(raise, held e, S1) -> S2
RAISE(e, S2)
```

unwind 必须读取表达式异常完成产生的 S1，不能退回 invoke 前状态。最终异常
payload 引用仍为 e；它所关联的 traceback、context 等内容可反映后状态，不能
据身份保持宣称异常对象内容未变。

普通表达式 invoke 的失败支路改为先构造一次 unwind，再调用低层终结器生成器。
frame 转移本身不再次调用会自动生成失败清理的通用 invoke，避免递归清理或
虚构无限多 RAISE 分支。

### 4.3 非抛出不等于纯或必然完成

在第 2 节条件下，typed frame 规则的定义是：**若转移完成，它保留 pending
completion；它仍可能产生未知效果或不完成。**

- finalizer、弱引用回调及其外部交互仍属于 world 效果；
- `__del__` 抛错走 unraisable 协议，不人为替换正常返回或原异常；
- finalizer 可能阻塞、不返回或触发其它外部行为，不能从没有 RAISE 边推导 total；
- 未证明可观察效果为空、必然终止前，不能删除、外提或合并该转移。

这种 may-diverge 与未确定效果是 frame 规则的规范约束，必须由 typed rule 和
查询结果保留，不能只藏在自由文本 gap 中。它无需一个声称“已经发生”的 DIVERGE
出口；不完成意味着没有到达后续完成端口。

### 4.4 退出不保证释放

frame 逃逸、traceback、其它引用和 GC 策略可以延长对象生命周期。EXIT 表示
运行时规定的退出及所有权/保留关系变化，不保证所有局部被立即解绑、析构已经
执行或资源已经释放。状态摘要不能把 pending 返回引用、异常或被保留的 frame
当作必然已销毁。

语言依据见 [Python return](https://docs.python.org/3.14/reference/simple_stmts.html#the-return-statement)、
[对象生命周期](https://docs.python.org/3.14/reference/datamodel.html#object.__del__) 和
[finally](https://docs.python.org/3.14/reference/compound_stmts.html#finally)。后续支持
finally 时必须先持有 pending payload，再执行 finally；finally 可修改对象内容、
替换返回或替换异常。C0 不通过本规则跳过它。

## 5. 实施位置与版本迁移

按以下依赖顺序实施：

1. 在 `ir/program/` 增加 FrameModel 的 typed records、规则条件和严格解码；
   明确每个引用都指向核心图，验证前后状态与 payload 对应。
2. 在 `program_lowering.py` 增加新 frame profile；改 `function`、`store`、
   `statements`、`invoke` 的源规则，拆分 frame 转移与最终 `finish_exit`。
3. 验证器/来源重放检查 ENTER 覆盖、BIND/DISCARD 位置、EXIT 与终结器匹配、
   当前状态与新后态，以及没有遗漏或多出的 FrameModel 对应。
4. 增加 body 内的引用来源查询与独立效果义务结果，最后接入公共构图/重放。

版本策略固定为：

- 新增 **frame lowering profile**，具体 enum 名称实施时确定；不能改变现有
  `LEGACY` 或 `BOUND_FORMALS_V1` 的语义。
- `SourceProgram` 增加 schema v2，持久化 profile 和 FrameModel；旧 schema v1
  继续按旧 lowerer 路径严格重放。
- 新默认 `ProgramInventory` 使用 **v5**；v1–v4 按各自历史 profile、接口和
  预算顺序严格重放。不能在加载旧报告时隐式补 ENTER/EXIT。
- 当前 program-graph **v2 结构可复用**；核心使用已有 Operation、StateAccess、
  Value 与终结器。本门新增信息由源码规则对应层承载，不伪造新的核心依赖。
- 旧调用报告继续绑定原 inventory 文档身份；不能静默用新 v5 图替换旧图。

新 frame 操作计入实际构造预算；失败和回滚的构造成本继续计费。来源层准备、
全局调度、上下文封存及独立验证上限不能因 profile 升级绕过。

## 6. 自主验收门

代理负责实施、独立反例、冻结定向门、回归及外部来源核验；不把人工检查图或
用户逐参标类型作为产品输入。除校验器破坏性反例外，所有正例从原始 `.py`
自动构图，必须经过公共序列化及来源重放。

| 门 | 必须交付和查询 |
| --- | --- |
| F0 类型与状态 | FrameModel 严格解码；引用真实 Operation/Use；ENTER/BIND/DISCARD/EXIT 与当前 world 一致；篡改失败 |
| F1 自动引用来源 | `return x`、返回别名局部、返回新局部、分支返回、None/fallthrough 都有正确的逐路径 payload 来源；退出效果仍保留 |
| F2 生命周期与异常 | 全部 formal、分支局部、覆盖、Expr 丢弃进入状态依赖；表达式失败后 unwind 保持异常 payload 与后状态 |
| F3 版本与预算 | 新 SourceProgram 与 inventory v5 严格重放；旧 v1–v4 fixture 不变；新 profile/FrameModel/状态/端口/预算篡改拒绝 |
| F4 冻结外部来源 | 原入口与真实证据自动重建，比较新增连接、残余缺口、时间和内存成本；LeWM 源码与环境不改，不手补图 |

### 6.1 必需通用正反例

1. **未使用形参仍有退出依赖**：`def f(unused, x): y = x; return y`。
   payload 查询回到 x；EXIT 的状态依赖仍覆盖 unused 的入口持有。
2. **别名与覆盖**：`x = x`、`y = x; x = replacement; return y`。
   不按相同 ValueID 去重持有，不改变返回 y 的身份，不删除旧槽释放效果。
3. **分支局部**：`if flag: local = make()`，随后在分支外 `return x`。
   local 不在 env 交集也不能丢失其条件持有/退出状态；零绑定路径不伪造 local。
4. **丢弃时点**：`make(); mark(); return x`，以及局部覆盖后再 `mark()`。
   DISCARD/BIND 必须位于 mark 前的状态链；不能统一移到 EXIT。
5. **返回对象内容变化**：其它局部的 finalizer 可以修改返回对象。
   正常引用来源保持，但内容及外部效果仍依赖退出后态，不得推导纯 identity。
6. **unraisable**：finalizer 抛异常的通用小程序。
   不因此新造 replacement RAISE；保留未知外部效果与可能不完成的义务。
7. **异常后状态**：`touch(); return failing()`。
   failure 的异常 payload 和后态先经过 unwind；不得回到 touch 前或 invoke 前状态。
8. **frame 保留**：返回被持有的 frame，或异常 traceback 保留局部的通用例子。
   不能报告已 free；也不能借此自动证明 NO_FRAME_INTERPOSITION。
9. **显式边界**：finally 重绑定/替换返回、del 后读取、显式 raise、closure、async。
   在本门未实现这些规则时，自动构图整体报告具体 UNSUPPORTED，不输出伪精确出口。
10. **校验器篡改**：删一个 ENTER formal、漏/重复 transition、把 READ_WRITE 改为
    overwrite、EXIT 改用另一个 payload 或旧 world、绕过 unwind、提升条件权限、
    修改 profile/预算，公共重放必须拒绝。

## 7. 本门之后仍未满足的目标

当前调用引用查询在 formal 处的 `ARGUMENT_ROUTING_UNVERIFIED` 继续有效。
bound method、Name-bound method、partial、默认值同引用等反例已说明：code 与
引用 token 相同不足以证明 actual 到 formal 的来源。C0 不能重建被撤销的错误边。

**实际调用绑定 E4 仍未满足**：本门只加强 body 内返回来源和退出效果，不能
据此宣称 caller → callee formal → return 的普遍跨调用依赖链已闭合。
函数对象/defaults/closure 环境、逐调用状态域映射、细粒度 alias、循环与 GPU
完成等仍是后续门。没有真实连接及变换证据前，不报告缓存许可或 LeWM 加速比。
