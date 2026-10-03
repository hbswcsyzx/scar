# G7.2：值来源、替换差量与可重验的证明

状态：实施中。G7.1 已归档；本节点只分析并生成证明记录，不修改目标程序。

## 连接模型的决定

SG 保留定义、控制及可能的数据连接；source semantics overlay 保留有序计算和
逐次 binding。overlay 可作为 IRBundle 的独立可选图，与 EEG 和动态 ValueGraph
并列。静态表达式不是动态 LogicalVersion；替换使用 StaticValueSubstitution，
其 producer、source span、可选 binding 必须连接到实际 overlay。

Operation 是语义定义，invocation 是执行实例。region 可以包含并递归展开这些
节点。region inventory 继续只描述原程序及 NO-OP；后续替换计划不回写这份证据。

## 不能在边界处丢掉连接，也不能假装连接精确

import、attribute、call、index、重绑定与控制边界记录为 SemanticBoundary：
kind、scope、block、position、operation 和 source。边界后的读取可保留
conditional_reaching，但仍是 UNRESOLVED，绝不升级为 EXACT。

ImportSpec 明确 import form、请求模块、实际绑定模块和本地名称：
`import a.b` 绑定 `a`，`import a.b as x` 绑定 `a.b`；from-import 还需要导出名。
本地 source module 是 loader 候选而非已观测加载结果。

跨模块 resolver 沿这些类型化连接追踪 immutable 值、导出和 re-export，生成
逐跳来源和具体 loader/cache/lazy attribute/namespace 条件。无法支持的边界列出
原因。初始化效果不随常量值路径消失：替换值与删除 import 是两个独立差量。

## 证明账本与验收

四类规则固定必要义务：constant、dead、reuse、motion。账本绑定实际差量、源码、
图、Q、region 和 scope；读取 JSON 后从相同规则重新推导，不信任保存的 PROVEN。
局部 constant 只检查被替换操作；dead 必须关闭消费者并核对必须保留的效果。
reuse/motion 的输入及状态版本、RNG、输出 ownership、autograd、控制、异常、
ordering 和 lifetime 未满足时列出缺项，不以重复出现充当证据。

验收顺序：

1. 严格 schema 迁移和静态替换的真实 cross-reference join。
2. 条件来源、边界和 source replay 的独立反例。
3. 任意自建包的 import→re-export→attribute→index 路径与初始化分离。
4. 固定规则义务、差量边界、伪造/过期/缺项/循环证明的拒绝。
5. 定向测试、整仓回归、报告及实现/验收两次提交。

若某家族只有拒绝路径，记录为未完成正向能力，不能据此宣布 G7 总门通过。
G7.3 才集成精确修改指导，G7.4 才运行外部压力；成本选择留给 G8。

当前实现的验收分成 G7.2a 与 G7.2b。a 检查上述静态连接、import 来源、
CONSTANT/语义 DEAD 正反例和四规则的固定证明义务；b 仍需补齐 REUSE/MOTION
正向所缺的状态、输出 ownership、autograd、target-entry 与控制证明。
`gates/g7_2a.json` 明确只接受 a，不能把负例通过作为 b 或总门通过。

## 分工

三个 Luna max 子代理分别负责静态 OIR/schema、import provenance、proof ledger。
主代理负责边界和条件 binding 模型、source extractor、独立反例、集成与验收。
文件范围独立；任何名称特判、目标 import 执行、新 backend 均不在本节点范围内。
