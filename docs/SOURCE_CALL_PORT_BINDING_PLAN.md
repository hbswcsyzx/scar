# 源调用端口绑定与捕获引用路由分离

2026-10-26。Proposed；为第一阶段建模补依赖连接，不增加优化 backend。

## 问题及边界

当前 source858 的真实100,550 CALL attempts只接受27组窄引用路由。其中2656组
已越过入口握手与 source/core 检查，停在 Name-only 条件。准确分母见
[全量审计](../artifacts/analysis/call_route_gaps_20261026/REPORT.md)。

`f(x + y)` 的一般程序依赖应为：求值产生的 ReferenceValue → 调用的有序 Use →
参数端口。这个依赖并不要求知道 `x + y` 的 Tensor 数值；运行时到底是哪次静态
定义的发生，仍需当前 Invocation、CALL site、直接入口与编译见证限定。

不把上述源端口关系当作引用相等、内容恒定、函数纯性或允许代码移动的证据。
不将未观测的 frame/statement/BlockVisit 伪造为实际发生。

## 首个规则与复用

- 复用 normal fresh `link_call_operands` 的 call model、operand scan 与 SourceBodyAccess；
  不重扫 raw，不接受报告 JSON 作为 live owner。
- 复用 `bind_call`/`CandidateBinding` 和规范 CallArgument、ParameterBinding、Formals。
- 仅 exact Python function、唯一匹配的 direct handshake；双方 code/source/body 都已
  经正常读者检查。原 capture gap/metadata 丢失检查继续适用。
- 初版仅显式位置参数：无 `*`/`**`/keyword/default/隐式 receiver，非 suspended。
  不要求 callee/实参为 Name。精确核 CPython CALL arity、source position、源实参到
  invoke Use 的顺序、参数 kind/layout 和正式端口。
- 使用有类型的源端口绑定记录，引用已有静态端点与原调用/入口 fact。不会新增一套
  可修改的 producer/value 图；缺少 runtime value identity 时明确不授此资格。

## 接入及验收

现有 ArgumentRoute、历史 wire 和窄引用规则保持原义。先由可选的正常 linker consumer
在同一个 fresh 输入会话得到新关系，验收后接入统一建模入口。不要为保存一个字段而
重复运行 source/frame binder 或再次校验全部图。

根验收使用保存的真实 LeWM 完整采集，逐项保全100550 attempt分母和准确 frontier；
检查正常 reader、真实 source/slot/caller/arity 交换反例。仅做这些变更必需的验证，
不添加测试矩阵。若数据不足，给出原 anchor 和缺少的关系，不用 parent/time 填空。

交付必须区分：静态 binding、实际 entry 对应、引用身份、内容/state 和可替换资格。
第一阶段未完成前不因此执行优化。
