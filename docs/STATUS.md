# 当前状态

唯一任务是整程序纯静态分析与建图。工作目录为 `~/AAA/scar`，分支为 `main`。第一阶段尚未完成；当前继续接通父级类构造和跨模块属性来源，没有运行 LeWM。

## 当前产物的实际范围

依据 `artifacts/current/static/manifest.json`，SHA-256 为 `48a601517be424356eb28c17f4898a9c93da9663de11fd4b963baab53275acb6`。这是主体发布版本；新的整范围调用索引尚待构建。

| 项目 | 实际结果 |
|---|---:|
| 源文件 | 582：581 `.py`、1 `.pyi` |
| 源根 | LeWM 及其两个本地依赖项目；未包含环境第三方实现的完整源码闭包 |
| 原始源码 | 5,718,464 bytes |
| AST occurrence / 词法入口和上下文 | 762,839 / 12,550 |
| 原源码操作 / 关系 | 469,005 / 2,057,190 |
| CFG 节点 / 边 | 239,097 / 285,316 |
| 有限常量事实 | 76,788 |
| 有规范图的入口 | 8,089：581 MODULE、1,183 CLASS、6,325 FUNCTION |
| 规范操作 | 1,262,346 |
| lowerer 不支持 / 规则 shape 不支持 | 326 / 404 |
| 构造 ERROR | 0；不代表主体或推理完整 |
| 缺独立入口适配 | 3,731；部分已经内联在父图，不能等同于全部缺失 |
| 当前调用关系索引 | 不存在；主体重建已使旧派生索引失效 |
| 已保存 parent ClassConstruction | 1,065：MODULE 内 991、FUNCTION 内 74；不是 suite 执行已连接 |
| 模块精确剩余后缀 | 107 项 REQUIRED_EXPANSION；另有 8 项 deferred-child 展开义务 |

最近按 AST 自动定位 365 个 MODULE、84 个 FUNCTION 父级入口，449 项增量命令耗时 660.282 秒，8 个进程，未重建原源码图。新增类构造推进后暴露一个模块 compiler-cell 能力未被后续 function validator 消费的错误；按明确 compiler profile、真实前导和 allocation 表修复后，仅重发原入口，22.480 秒。原 root 严格校验没有放宽。规则 shape 不支持从 480 降到 404；有些入口推进后遇到下一项 lowerer 缺口，因此 UNSUPPORTED 从 314 增到 326，不是这些入口全部完成。以上均为分析器时间，不是 LeWM 性能；当前静态产物约 1.9 GiB。

`LOWERED_WITH_GAPS` 仅表示存在规范图，不代表主体完整或推理穷尽。manifest 明确记录 `body_expansion_complete=false`、`static_call_links_present=false`、`whole_program_model_complete=false`。

## 第一阶段真正还缺什么

1. **主体与层次结构没有完整接上。** 模块剩余后缀从 418 降到 107 项，另有 8 项 deferred-child 义务。已保存 1,065 个 parent 类构造及共享 suite 编译来源，但 prepared namespace → suite ABI → metaclass 的执行/状态接口尚未连接；不能据此删除 1,183 份独立类体中的原入口前沿。45 个 suite 本身仍有剩余主体；类内那个嵌套 ClassDef 尚未接入新 parent profile。lambda、comprehension、generator/async、注解等仍须核对内联与独立主体。
2. **跨层值来源尚未闭合。** v6 已实现普通 import → 模块 namespace 条件快照 → 属性值、caller 属性覆盖、参数/返回透传及 0 CALL 来源分片。但这还没有在新 LeWM 整范围索引上发布；imported function 的原模块 G/state 到内部 global 读取仍缺状态桥，不能借 caller G。默认参数当前字段/元素、闭包内容、通用 implicit-call/decorator application、ImportFrom/submodule 来源等也未完整贯通。
3. **别名、状态和效果尚未联合推理。** 引用传递不等于内容不变；尚缺完整的 points-to、对象字段/容器/Tensor 状态版本和 may-read/write/escape/RNG/external/order 摘要传播。当前不少关系仍附带尚未消解的条件，不能据此证明整个子图可以移除或外提。
4. **可推导属性与库/资源边界尚未贯通。** 常量推导已有局部能力，类型、Tensor shape/dtype/device/stride、逻辑来源和存储别名还没有在整程序上统一传播。第三方 Python 源码与 native/PyTorch 操作需接入版本化源码或契约；资源要求、潜在分配/搬运/等待应连回原操作和值。静态图表达符号资源及候选实现，不冒充观察到的真实 kernel、地址或传输。
5. **完成度还没有可靠的统一解释。** 原源码视图的 gap 与规范主体前沿不在同一层，不能直接相减。模块来源的需求前沿已按 body/原 Value/精确调用上下文重算刷新，预算中断保留证据，避免旧提示永久累计；其他整程序覆盖仍需继续区分缺结构、缺连接、未实现、缺材料、预算和静态信息不足。非 module 属性的 receiver 未接提示只表示这项特定来源关系尚未确定，不能解释成 ATTRIBUTE 结构缺失。

326 个 lowerer 不支持项中，主要阻塞包括 nested-with cleanup 60 项、comprehension parent cleanup 41 项、常量槽对应 28 项及表达式组合。另已定位无 docstring 的模块 compiler 前导与首条 future import 源位置重合时，import-plan 扫描尚未排除前导的具体规则欠账。它们不是必须动态探测的证明。

四项相关回归通过，170.13 秒：qualified value sources、module attributes、expression lifetime、class construction。模块回归覆盖 import/属性/参数/局部绑定/返回/最终调用、覆盖后仅选择新值、0 CALL 常量来源、公开 fresh 查询及 selector/receiver/world 篡改拒绝；随后需求前沿刷新复验通过，127.74 秒，故意 Timeout 继续抛出并保留旧证据，成功重算仅清除该精确上下文的旧提示。最后 class 回归加入 compiler-cell + ClassDef 后 function 的组合，4.48 秒。没有新增大规模测试或执行目标源码。

## 已有能力与当前限制

`scar static` 可纯源根扫描、解析 AST/symtable、登记全部源码定义和编译上下文，并行构造分片源码图和受支持的规范子图。静态编译与反汇编只生成语言/编译器事实，不执行模块初始化。`scar static-query` 可按原定义、操作、Value、Use、控制和来源导航。

核心实体仍为 Operation、Value、StateLocation、Region、Resource。包含关系组织层次，数据、绑定、控制、状态、别名和资源关系连接依赖；实体类别存在不代表所有关系已经构造。函数体共享保存，调用点保留自己的端口与静态上下文，不复制整份 callee。

schema v6 继续保留 v5 的上下文隔离参数/返回来源，同时保存 import、属性值和覆盖写的原端口关系；schema 1–5 严格迁移，旧 wire 不得夹带新表。语言 overlay V3/模块 wrapper 12 保存 parent ClassConstruction 与真实 ImplicitCallPorts，没有伪造 ast.Call/CallID；旧版也严格拒绝新表。新的 LeWM 整范围 publication 尚未完成。

未知必须落在具体字段或关系上：地址不明不妨碍保留已知类型和 shape；不能解析的调用仍须保存 callee 表达式、输入、可能出口和保守效果。已有源码但缺实现的子图不能用 UNKNOWN 叶子计作完整展开。

## 后续顺序

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 对全部已有主体重建调用/值来源索引，核对真实范围、读取错误、预算、保存关系及公开查询。随后接 imported function 的模块 G/state、标准 builder 的 prepared namespace/suite 绑定、defaults、decorator/implicit-call 与 closure。语言欠账按共同阻塞原因修复，不按 LeWM 名称或单个函数补丁。

随后将 points-to、状态、效果与类型/常量/Tensor 属性放入相互反馈的工作队列，补足依赖源码/契约，并核对整范围导出、查询和具体前沿。验收关注可追溯的完整结构与依赖，不能用操作数、图数或零 ERROR 代替。进入化简阶段之前不增加 detector、backend 或动态采集。
