# N2.signature：分离函数体、定义时状态和调用绑定

日期：2026-10-15。状态：**S0 已有限验收，含外部严格重放；
S1–S4 仍为 Proposed，尚未实现或验收。**
S0实际报告见 [N2_SCHEDULING_ACCEPTANCE.md](N2_SCHEDULING_ACCEPTANCE.md)。

前置是 N2.entry 的运行来源桥接及全局 body 调度。本文规定下一门的模型与验收目标，不表示
当前已经获得这些能力。循环细节继续见 [N2B1_PLAN.md](N2B1_PLAN.md)。

## 1. 由实际断点选择任务

N2.b0 自动清单中，256 次 body 尝试有 97 次先被默认参数/装饰器等接口阻断。
N2.entry 自动来源范围扩大后的相同预算清单中，此类阻断为 111 次。还暴露了
更早的调度断点：文件内先处理观察定义，并不能保证所有文件的观察定义先于
其他定义消耗全局预算。256 个运行来源候选定义中只有 1 个连到 core，164 个
为 NOT_ATTEMPTED（包含预算和非函数接口，必须按 reason 分开统计）。
`program_lowering.py::function` 当前把这类定义整体拒绝；`candidate_bindings`
仅适用固定的必需位置参数。删除前一个检查而保留后一个算法会制造错误调用边。

目标不是把这些函数改成 pure，而是独立表达三件事：

```text
外层执行：求 defaults / decorator 等 -> 创建函数对象 -> 应用 decorator -> 名称绑定
调用执行：实际 callable + actuals + 当前函数状态 -> 参数绑定成功或 TypeError
函数体：已绑定 formal references + 隐式环境/状态 -> 正常/异常完成
```

函数体可以在参数绑定后的入口条件下单独建图。它不因此证明某个调用会进入
这个函数体，也不因此证明默认对象、装饰器、方法绑定和环境状态固定。

## 2. 类型与不变量

仍使用 Operation / Value / StateLocation / Region，不增加按业务含义分类的节点。
在已有 ParameterInventory、DefinitionInput 和来源对应之上增加有校验规则的
函数体入口接口及绑定状态；不能把关键条件藏入 label 或任意 metadata。

- formal 端口有稳定顺序和 ParameterKind，包含 posonly、poskw、kwonly、
  varargs、varkw。每个端口都必须连接已有源码参数槽；body 内是已绑定引用。
- `*args` 和 `**kwargs` 在函数体内分别是 tuple / dict 对象的引用，不能把它们
  偷换为散开的 actuals，也不能因容器为空而省略构造、身份或效果条件。
- defaults 在定义时求值，保存在函数对象状态；可变默认对象不是每次调用的新
  literal。`__defaults__`、`__kwdefaults__` 被改写时必须使旧绑定结论失效。
- decorator 的表达式求值、应用和最终 binding 分开；装饰后名字可能指向任意
  callable。源码原函数体存在，不等于经这个名字调用时进入原 body。
- 参数绑定失败发生在 body 入口前。缺参数、重复 keyword、posonly 被错误指定、
  未知 keyword、星号展开及展开异常不能通过假造 formal 值绕过。
- bound method 的 self、descriptor、闭包/cell、globals 和编译环境使用不同来源
  的环境接口，不能假装是用户显式传入的位置参数。缺少规则时保留具体边界。
- async / generator 创建与恢复具有不同的执行和生命周期；本门仍明确不支持，
  不能把它们降成一次普通同步 body 调用。Python 3.14 注解的惰性阶段也不能省略。

函数体图、条件调用候选、已确认调用实例的状态必须分开。body 成功不能自动
改写 callee，不能以效果不完整的调用替换为某个候选 body。

跨文件组合还必须显式映射状态域：当前 world LocationID 按文件和快照生成，
不代表物理世界相互独立。调用携带 callable + actuals + world，body 携带
formals + world；绑定/dispatch 与世界状态映射缺失时不能直接拼接两者。

## 3. 有限交付顺序

| 自验门 | 自动输入与实现任务 | 必须能回答的查询与验收 |
| --- | --- | --- |
| S0 全局展开调度 | 先分离文件索引与 body 工作；自动形成跨文件的观察/调用/use 需求队列，再处理其余候选；同快照和有界缓存 | 早期文件的大量未观察定义不能饿死后续文件的需求；互换无关文件/定义顺序不改变优先级类别；模块/class/code thunk 不假装函数 body；准备/失败/编译成本仍计费 |
| S1 入口模型 | 从真实临时源码枚举所有普通同步参数种类；建立 typed body 接口和 codec/replay | 任意 formal use 追到哪个参数槽；kwonly/variadic 不丢；篡改 kind/order/slot 被拒绝 |
| S2 body 与定义分离 | 使用绑定后的 formal 自动 lowering；默认值、装饰器仍保留外层阶段及边界 | 带 default/decorator 的简单 body 可表达；无法据此声称调用实际进入 body；异步/闭包不静默放行 |
| S3 调用绑定 | 将当前确实可证明的绑定映射转成 typed 规则，其余明确 incomplete；无规则不生成完整 candidate arguments | 缺参/重复/posonly/default 状态/星号展开的正反例；每个 actual/formal/default 来源和绑定失败位置可追溯 |
| S4 全链集成 | 单入口 inventory、共享预算、严格当前源码重放、mapped gate/回归、未修改外部源码自动重建 | 不输入函数名单；新增成功 body 与后续阻断逐位置对比；来源/调用/状态精度分别报告，成本归档 |

S3 不要求本门解决任意 Python dispatch。可以先支持有限规则并为其余接口保留
显式不完整状态，但不能用“候选 body 存在”冒充绑定闭合。验收文档必须列出
每种支持/不支持规则，不可把新增参数种类全部计成完整调用支持。

至少包含：可变 default 跨调用复用与内容写入；重写函数 defaults；替换 callable
的 decorator；同名函数重绑定；posonly 同名键进入 varkw 的合法情况；关键字
重复及展开时抛异常；两次调用不同 actuals；外层装饰失败导致 body 不可达。
通过后同步 schema/迁移说明，旧报告不得被补造新绑定事实。

## 4. 后续依赖顺序

1. 本门：先全局展开调度，再分离 body 入口与定义/调用接口；不声称完整 loader 或跨层数据来源。
2. N2.b1：按已有提案实现 assert、零次/回边/合流、break/continue/else、迭代
   协议和局部未绑定状态。不得按猜测的迭代次数展开成一串 trace 节点。
3. N2.b2/N2.c：属性/下标/容器与 alias 状态、一般退出处理、跨文件/方法调用
   接口；用已有实际目标证据精化。coarse world 在对应范围闭合前不得删除。
4. N4/N3：将输入/结果 occurrence 和设备物化证据接到上述接口；从观察根查询
   依赖闭包，形成精确子图替换/上移/共享指导和单独的证明、失效、成本记录。

最终压力验收查询来自程序图：输入跨多少层传入、循环中哪些版本变化、缓存
写入和命中如何连接、物化值有哪些消费者、常量路径有哪些残余初始化效果。
先用不相关的通用程序验证，再自动应用于原始 LeWM；不按任何库或变量名选规则。
不能用节点数量提升替代这些查询，也不能通过人工填 pure、版本或边来通过门。

## 5. 自动化与可知性

自动化意味着 SCAR 自行构图、发现断点并输出证据，不要求用户手工建图。
它不意味着任意动态 Python 的所有路径、未来外部状态或全局最优变换都能被
静态精确求解。所有构造都应有模型位置；尚未掌握的目标/读写/消费者仍必须
有具体边界。后续通过通用规则、运行证据和可执行 guard 缩小边界，不能将
UNKNOWN 改写为 NONE 来制造自动化完成率。

## 6. S1 实施前必须处理的接口事实（Proposed）

`frontend_v2.py` 已为所有参数种类创建 input slot，但旧 `input_slots` 的顺序
是 posonly/poskw/kwonly 后再 varargs/varkw；不能把它的位置直接当作新的
调用ABI。新入口应按 ParameterKind 显式对应名称、源码槽和body入口Value，
不是对任意位置做zip。默认表达式的SourceReference也不是调用时默认对象。

`LoweringMetadata`、`CallTarget` 和 record codec 使用严格字段集合。新增body
接口或binding状态要选择显式版本化overlay/profile与迁移，不在旧dataclass
中塞入字段后破坏v1/v2/v3报告，也不把旧空arguments自动解释为绑定成功。
旧报告重放应保留其原规则，或明确要求重新生成；不能补造新证明。

新增body接口后，`candidate_bindings` 必须先核对完整formal集合。没有kwonly、
varargs容器、varkw或默认状态的规则时，明确不完整，不允许只映射positional
子集而看似完整。函数体的bound入口与实际调用成功仍由独立条件连接。
