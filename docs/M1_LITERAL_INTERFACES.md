# M1 L：精确内容、来源与求值接口

本文件说明实现后的接口；结果见 `M1_LITERAL_ACCEPTANCE.md`，原分母和限制见
[计划](M1_LITERAL_PLAN.md)。完整第一阶段仍未完成。

## 1. 图上的三种不同关系

```text
PythonLiteral                       精确 builtin 类型/内容表示
    ↑ literal 字段
ExactLiteralOrigin                  仅 DataValue：抽象内容常量

原 OperationResult / NORMAL CompletionResult
    ↑ LiteralEvaluation.site        原 producer 和原结果端口
    ├─ literal                      已知内容或 UninterpretedConstant(reason)
    └─ definition                   来源声明，不是第二个 producer

ValueOccurrence → ValueDenotation   本次数据/对象指代，沿原 execution 接口
```

`ExactLiteralOrigin(literal,definition)` 只能定义 DataValue。Data 的 declared type
必须等于 payload 对应 builtin 的完整类型名，不把 bool 当 int、数值当字符串或
native scalar。它不产生 Python 对象。旧 `LiteralOrigin` 保留旧有限行为/wire。

`LiteralEvaluation(site,literal,definition)` 附在已有 Data/Reference 产出上。附件
不改变 value.origin、Operation.results、ordered Uses、状态、效果或完成方式。
即使内容已知，加载、分配、回调、异常、构造和 release 仍由原操作承载。只有
旧/新抽象 literal origin 进入 activation 的可用性规则；附件绝不进入该规则。

## 2. Payload 与 profile

共享 `scar.ir.literals.PythonLiteral` 保留 kind/payload/items 三字段。

| 内容 | 表示 |
| --- | --- |
| None/bool/Ellipsis | 原带类型标签的空载荷或 exact bool |
| int | canonical decimal string，非全局大整数格式化 |
| float | FLOAT64，16小写hex binary64 bits |
| complex | COMPLEX128，32小写hex，real bits 后接 imaginary bits |
| 普通 str | STR，原文本代码点，无 normalization |
| 含 surrogate 的精确 str | STR_CODEPOINTS，每代码点8小写hex；至少含一个surrogate |
| bytes | 任意字节的小写hex |
| tuple 内容 | 有序递归 items，不代表对象/源构造已可删除 |

`PythonLiteral.from_python(value,exact=False)` 默认保留旧支持子集；`exact=True`
启用新 complex 与可逆 surrogate 编码。`require_exact_literal` 复查整棵树并拒绝
raw STR 中的 surrogate；新核心 origin/附件全部调用它。`require_legacy_literal`
让旧 SourceSemantics/OIR family 拒绝两种新 kind，原前端显式保持旧 profile。

STR_CODEPOINTS 区分两个代码点 D800/DC00 和单一 U+10000。普通 escaped JSON
不能保留这个区别。旧 raw STR 与旧 family 协议保留，它的相邻 surrogate 合并
是 baseline defect；没有将新 profile 的修复冒称旧协议已改变。

`from_dict/as_dict/from_python/to_python`、通用 record codec、record_errors 与
旧 v2 literal decoder 共用预检。固定每 payload 上限是：root depth0、depth64、
16,384 展开节点、1,048,576 scalar payload bytes、4,096 decimal digits；integer
先检查13,608 bits，再分块转换。不得修改全局 integer digit 限制。

共享子树每次使用都计数，active-stack cycle 拒绝；节点在入队前预留预算，不能
先排队几十万节点再触深度界。超长 str 在扫描 surrogate 前按长度拒绝。nested
本地 record tags 也经过同一迭代、严格 shape/标签校验，没有无界递归去标签。
合法类型的超大内容可保留原求值和明确未解边界，不截成另一个有效 literal。

`literal_builtin_type` 只返回 builtin type，不物化值。record equality 表示 typed
descriptor 相同，不是 Python ==、NaN 自反相等或对象 is。list/dict/set、可变元素
和用户对象不能进入 payload；不调用 repr/hash/eq 或任意反序列化器。

## 3. 原 producer 端口与来源

site 复用原 `OperationResult(operation,index)`，或
`InvokeLiteralResult(ControlEdgeReference,CompletionResult)`。direct 必须是原
Data/Reference 结果，origin 与 slot 一致。INVOKE 只准 NORMAL produced slot，
按逻辑 index 找原 edge 的唯一实际 formal；不是 landing 第0槽，也不是默认第0边。
原 core 的 completion_slots 仍要求每 produced slot 恰好绑定一次。
State/Binding/Protocol、RAISE 或 forwarded Use 都不能冒 literal 新产出。

definition 的互斥 typed variants 是：

- `SourceExpression(SourceReference)`：有版本 span，不承诺 AST Constant；UnaryOp、
  BinOp、容器/格式化表达式的原来源不会因 payload 相同被删。
- `CodeConstant(ProviderFactReference,index)`：fact 定位原 code/const-pool 容器记录，
  index 唯一选择 co_consts 槽。编译器和 flags 等上下文留在原 artifact，不另存
  code registry；没有 artifact/profile replay 就不证明槽或运行 code 对象身份。
- `UnlocatedLiteral(reason)`：未定位，不能解释成没有来源或恒值已证明。

`UninterpretedConstant(reason)` 可附原结果，包括未解的 code/frozenset 编译常量或
运行构造；它不表示精确内容/类型匹配，也不允许用于 ExactLiteralOrigin。
source、code、slot、payload、运行 ObjectIdentity 各有自己的身份；不同 label 或
相同 hash/内容都不能替代原范围和实际执行关联。

## 4. 查询与有限预算

`ProgramIndex.literal_evaluation(site)` 返回原 operation/result、successor/argument、
按原 Operation.uses 排序的 UseSite、可选 row、literal、definition 和具体未证条件。
无附件时保留原结果/producer，并明确缺内容/来源声明，不返回无效果证明。

`ExecutionIndex.literal_evaluation(site,occurrence,budget=4096)` 解析该次 producer，
逐个绑定原 UseOccurrence，返回原 ValueOccurrence 及已有 denotation。INVOKE 只有
实际 NORMAL transfer 才返回该 landing 结果；实际 RAISE 为 NOT_TAKEN，缺 transfer
为明确 gap。缺 result、引用 identity 或 capture 不借相同 payload 的另一 visit/
activation。两次求值可以由原 denotation 声明共享或不同对象；附件不替它选择。

预算只计动态 site/operand/result joins；静态校验/索引、外部快照准备及 detached
copy 成本独立。TRUNCATED 保留完整 canonical 声明、cursor、pending operands。
非法预算在重放前拒绝。结果保留 `producer_and_effects_retained=True`，并始终明确
source_runtime_verified、value_identity_verified、transformation_authorized 为 False。
DECLARED 只表示声明连接成功。

新 exact Data 也接入原 denotation/state-address 和 raw INT count 查询；相等的
数值仍不证明 native 返回槽。Reference-only frame/call 路由继续保持原 producer
边界，不将对象附件改为 LITERAL_REFERENCE。挂起后只有原 saved Use 恢复引用，
不能借内容已知绕过 cut/current/activation 校验。

## 5. Wire 与剩余工作

Program v16 仅由新 exact origin/附件选择；空新表、无新 origin 仍选择历史 v1–v15
能力。v16 用 escaped JSON，payload 的 surrogate 可逆性由 STR_CODEPOINTS 提供。
独立 v15 golden 在改 codec 前从 `13201ad` 保存；旧所有 fixture 保留。Execution
wire 没有为派生查询升版，七处最高 schema 测试与历史版本断言分别保留。

本门是声明接口及原端口组合：不把容器/f/t 的 opaque 边界当内部协议已展开，不
把手工 IR、typed source/fact、编译见证当自动来源恢复。完整 M2 构造、C2/D3、
M3/M4 source/native/运行身份对应及 LeWM 自动建图/化简仍未完成。没有新增优化
规则、backend、重型 workload 或性能数据。完整第一阶段后先停下来讲解的边界保持。
