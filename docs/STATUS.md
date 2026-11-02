# 当前状态

唯一任务是整程序纯静态分析与建图。工作目录为 `~/AAA/scar`，分支为 `main`。第一阶段尚未完成；当前已完成导入/源表达式和引用转交规则的收尾、原入口增量发布，没有运行 LeWM。

## 当前产物的实际范围

依据 `artifacts/current/static/manifest.json`，SHA-256 为 `7a4e61aea1749137c5e976f462213fa8111f093bd3fed739a0c09c0b71715678`。

| 项目 | 实际结果 |
|---|---:|
| 源文件 | 582：581 `.py`、1 `.pyi` |
| 源根 | LeWM 及其两个本地依赖项目；未包含环境第三方实现的完整源码闭包 |
| 原始源码 | 5,718,464 bytes |
| AST occurrence / 词法入口和上下文 | 762,839 / 12,550 |
| 原源码操作 / 关系 | 469,005 / 2,057,190 |
| CFG 节点 / 边 | 239,097 / 285,316 |
| 有限常量事实 | 76,788 |
| 有规范图的入口 | 8,025：581 MODULE、1,183 CLASS、6,261 FUNCTION |
| 规范操作 | 1,179,046 |
| lowerer 不支持 / 规则 shape 不支持 | 314 / 480 |
| 构造 ERROR | 0；不代表主体或推理完整 |
| 缺独立入口适配 | 3,731；部分已经内联在父图，不能等同于全部缺失 |
| 当前调用关系索引 | 不存在；主体重建已使旧派生索引失效 |

682 项增量构造使用 8 个分析进程，耗时 899.31 秒，未重建原源码图，增加了 95 个有规范图的函数并暴露 7 个构造错误。随后按原入口 ID 修复并发布这 7 项及一个 genexpr 算术漏选规则的入口：8 项均生成规范图，4 进程，命令 wall-clock 49.057 秒。当前表格反映修复后的结果。这些都是分析器时间，不是 LeWM 运行或优化性能；当前静态产物占用约 1.9 GiB。

`LOWERED_WITH_GAPS` 仅表示存在规范图，不代表主体完整或推理穷尽。manifest 明确记录 `body_expansion_complete=false`、`static_call_links_present=false`、`whole_program_model_complete=false`。

## 第一阶段真正还缺什么

1. **主体与层次结构没有完整接上。** 581 个模块中有 418 项 `REQUIRED_EXPANSION`，另有 8 项编译器 deferred-child 展开义务。1,183 个类虽已有 suite 图，全部仍有父级 class statement 未连接的前沿，涉及 prepared namespace、bases/metaclass 和相关 hooks；45 个类的 suite 本身也有剩余主体。lambda、comprehension、generator/async、注解等还需逐项核对独立主体与父图内联归属。
2. **跨层值来源尚未闭合。** 参数、正常 reference 返回、qualified namespace 的部分传播已经实现；默认参数的调用时字段/元素、闭包内容、装饰器 application、普通 module 引用到 export attribute 等仍未贯通。`static_calls._import_candidates` 对 `symbol is None` 仍不生成目标；不能把普通 import 的属性调用算成已经解析。v5 独立源码回归不能代替当前 LeWM 全范围链接结果。
3. **别名、状态和效果尚未联合推理。** 引用传递不等于内容不变；尚缺完整的 points-to、对象字段/容器/Tensor 状态版本和 may-read/write/escape/RNG/external/order 摘要传播。当前不少关系仍附带尚未消解的条件，不能据此证明整个子图可以移除或外提。
4. **可推导属性与库/资源边界尚未贯通。** 常量推导已有局部能力，类型、Tensor shape/dtype/device/stride、逻辑来源和存储别名还没有在整程序上统一传播。第三方 Python 源码与 native/PyTorch 操作需接入版本化源码或契约；资源要求、潜在分配/搬运/等待应连回原操作和值。静态图表达符号资源及候选实现，不冒充观察到的真实 kernel、地址或传输。
5. **完成度还没有可靠的统一解释。** 原源码视图的 opaque/semantic/control gap 数量与规范主体前沿不在同一层，不能直接相减或用总量衡量进度。需把缺结构、缺连接、未实现推理、缺材料、预算未处理、静态信息确实不足分开；每项指回具体原实体和关系。

314 个 lowerer 不支持项中，主要阻塞包括 nested-with cleanup 60 项、comprehension parent cleanup 41 项、常量槽对应 28 项，以及多种表达式组合接口。它们是实现欠账，不是必须动态探测的证明。原 7 个 ERROR 是引用所有权/异常清理的组合错误，已沿真实端口修复，没有改名为 UNKNOWN 或 UNSUPPORTED。

两个相关回归通过：`test_static_qualified_value_sources.py` 与 `test_source_expression_lifetime.py`，共 2 项，40.08 秒。覆盖调用上下文隔离、参数/返回、局部覆盖与无种子递归，以及字典/comprehension 结果引用转交、genexpr 算术和 f-string 失败路径。后者有四份公开 STRUCTURE 读回，并拒绝引用篡改和旧 capability 静默升级；目标源码均未执行。这些检查不证明尚未实现的跨层能力。

## 已有能力与当前限制

`scar static` 可纯源根扫描、解析 AST/symtable、登记全部源码定义和编译上下文，并行构造分片源码图和受支持的规范子图。静态编译与反汇编只生成语言/编译器事实，不执行模块初始化。`scar static-query` 可按原定义、操作、Value、Use、控制和来源导航。

核心实体仍为 Operation、Value、StateLocation、Region、Resource。包含关系组织层次，数据、绑定、控制、状态、别名和资源关系连接依赖；实体类别存在不代表所有关系已经构造。函数体共享保存，调用点保留自己的端口与静态上下文，不复制整份 callee。

schema v5 实现按调用上下文隔离的显式 actual→formal、正常 reference return→caller 传播；非空上下文不能退回无上下文并集。它已经过纯源码独立检查，但新的 LeWM 全范围 publication 尚未完成。早先 v4 的 400 份主体有界扫描已经不是当前有效调用索引。

未知必须落在具体字段或关系上：地址不明不妨碍保留已知类型和 shape；不能解析的调用仍须保存 callee 表达式、输入、可能出口和保守效果。已有源码但缺实现的子图不能用 UNKNOWN 叶子计作完整展开。

## 后续顺序

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 继续闭合现有图的结构与跨层接口：接父级 class construction、module export、defaults、decorator 和 closure 传递，再对全部已有主体进行调用/值来源求解。语言剩余项按阻断范围统一修复，避免仅追逐单个函数或局部错误数量。

随后将 points-to、状态、效果与类型/常量/Tensor 属性放入相互反馈的工作队列，补足依赖源码/契约，并核对整范围导出、查询和具体前沿。验收关注可追溯的完整结构与依赖，不能用操作数、图数或零 ERROR 代替。进入化简阶段之前不增加 detector、backend 或动态采集。
