# 整程序静态分析设计

状态：当前设计；已有组件与待实现部分分别列出。本文件不宣称完整自动建图已实现。
模型见 [MODEL](MODEL.md)，展开规则见 [PROGRAM_DECOMPOSITION](PROGRAM_DECOMPOSITION.md)，实施顺序见 [STATIC_ANALYSIS_PLAN](STATIC_ANALYSIS_PLAN.md)。

## 1. 目标和执行边界

给定源码、依赖源码/元数据、语言/平台描述、配置和明确提供的输入材料，尽可能获取所有可静态推导的信息，并建立可递归展开、可跨层查询的图。
目标是程序结构和依赖，不要求理解视频、图像等业务含义。不能使用包名、函数名或变量名的业务特例选择规则。

分析器可以执行，目标程序不能执行：禁止 import 目标、调用用户函数或 descriptor、执行配置/装饰器/模块初始化、unsafe pickle/torch.load、trace/profiler/benchmark 或动态验证。
解析文本/安全数据格式、读取版本信息、构造 AST/symtable 和运行静态图校验属于静态工作。任意数据解析若会运行目标代码，也不得使用。

“尽可能”不等于承诺任意程序的全部精确性质均可判定。要完整表示范围内源码，保留健全的可能关系并持续收窄；不能把未实现的分析称为必需动态获取。

## 2. 分析材料与范围

`AnalysisContext` 是拟增加的上下文接口，不是另一套程序图，明确：

- root/entry specifications、显式 source/dependency search roots 与版本化源码快照；
- Python implementation/version、编译模式/future/optimization、package/namespace 解释；
- 配置/安全数据材料、目标平台/设备能力及环境假设的来源；
- 标准库/原生库/算子语义摘要的版本与适用条件；
- 分析范围、精度策略和预算。

入口规格表达待分析入口，不执行入口。入口未知时可收录全部源码定义，不制造一个真实调用。
范围内文件中的模块初始化、函数、类、lambda、comprehension、annotation/type thunk 等分别登记。未实际执行的 body 也在静态目录中。
依赖搜索不能执行 `setup.py`、目标 import hook、配置工厂或项目插件。源码候选与实际加载结果分开；数据依赖 import/exec 保留表达式、候选及未知外部目标。
只有库源码可得/范围内才展开其内部；否则说明可用声明和缺少的主体，不能将其计作内部已经恢复。

## 3. 编译器式阶段

| 阶段 | 工作 | 主要产物 |
|---|---|---|
| A：材料与源码登记 | 定义边界、版本、命名空间及依赖候选 | 源目录、来源和未解析入口 |
| B：词法/语法 | 复用 tokenize、ast；保留编码/位置/future 与语法诊断 | 源 AST、位置映射、编译上下文 |
| C：作用域和绑定 | 复用 symtable，区分 local/cell/free/global/module/class namespace | 定义、符号、绑定、延迟主体目录 |
| D：语义 lowering | 按语言求值/协议规则生成 Operation/Use/Value、Region、CFG、状态与完成出口 | 规范层次化程序图、源码对应 |
| E：跨过程联合分析 | 目标解析、实参/形参/返回、抽象堆、读写/逃逸/效果摘要 | 调用/值/状态依赖、条件和摘要 |
| F：抽象事实传播 | 常量、类型、范围、Tensor 属性/表示/来源及约束 | 原 ID 上可组合的属性/关系事实 |
| G：静态导出与查询 | 结构/引用/覆盖检查，导出共享定义及分片 | 当前静态图、查询和未决信息 |

词法/语法不重造 Python parser。AST children 的遍历顺序不等于 Python 求值顺序；语义 lowering 必须有逐构造规则。
E/F 相互依赖，需要工作队列迭代；这个表不是一遍不可回访的 pass，也不是先无限展开整树再开始分析。

## 4. 一张规范程序图，多种视图

既有 `scar.ir.program` 继续作为规范核心。源码/语义层给出版本和规则对应，分析事实引用原 ID，包含图、调用图、CFG、数据/状态依赖图是该模型的视图，不各建一套 producer/state 真相。

核心结构是 Operation、Value、StateLocation、Region、Resource。输入输出是有序端口；源码来源、效果和抽象事实有独立记录/索引。
层次包含关系组织定义和复合操作；数据、调用、别名、状态及异常边跨层连接，整体可以有环。
一个函数定义/主体共享保存，各调用点保存自己的 Uses/results、目标条件和接口映射，不复制整个 callee，也不为静态上下文创建 InvocationID。

源码身份绑定 snapshot/context/definition/source position；名称和行号只辅助导航。分析条件/上下文可以细化事实，不随事实收窄重建整套结构 ID。

静态编译是语义前端的一部分：`compile(source, filename, "exec", flags=0, dont_inherit=True, optimize=0)` 可产生 compiler CodeType/常量槽、closure 顺序和指令位置，但不执行目标模块、默认参数、装饰器或函数体。
编译单元必须绑定源码快照、namespace、准确 compiler profile 和常量路径。每个主体以源码跨度、词法 qualname、编译位置与常量父子关系机械匹配，歧义不靠函数名猜。
静态来源用独立 `SOURCE_COMPILATION` 记录；不能创建假的 CapturedCode/CodeCapture/Invocation 或冒用原运行 CodeWitnessStore。
源码/编译布局恒定不证明实际加载的 code/function/module 对象相同；读取编译器常量也不证明运行时对象或可变内容相等。

`SourceCompilationCodeRef` 保存原主体引用、definition、编译器 profile、根布局及精确常量路径，不包含 CodeType 或运行 ID。模块使用原 `ModuleUnitSource` 和 initializer、空路径；函数使用原 `SourceReference` 和非空路径。`SourceCompilationFrameRoot` 把该来源接到既有控制 scope 和 ABI：模块用 locals/globals/builtins/world 映射端口，不能伪装成函数形参。静态 class 还缺独立 ABI，不能套用模块入口。
静态模块的 `StaticModuleEntryDeclaration` 与动态 `ModuleCodeWitness` 分开。规范 core schema 30 / source wrapper 9 明确标记静态来源；普通 reader 从保留源码重新编译并核对引用，不能把声明本身当作证明。模块已支持的顺序前缀和仍需展开的精确源码后缀分别保存，部分图不等于完整主体。


## 5. 展开契约

一个复合操作的展开记录必须说明：

1. 被展开的原操作/定义、规则和语言/库版本；
2. 输入及环境如何进入子图，操作数求值和绑定顺序；
3. 每个结果、引用、状态如何从子图返回原结果/出口；
4. 正常、异常、挂起/恢复等适用完成和已发生的部分状态；
5. 内部读写、别名、分配/生命周期、逃逸、外部及顺序效果如何穿过边界；
6. 展开前提、未解析关系及剩余主体范围。

不能因接口中有一个未知属性就停止构造其他结构。反之，只有接口的节点不能计作主体全部展开。
纯 primitive 可由版本化语义规则成为叶子；有源码且范围内的复合主体应继续解析。外部/native leaf 保留已知接口和不完整维度；OPAQUE 不是可以绕过缺主体的业务节点类别。
源码层原操作与细化子图保留对应关系，避免把宏观接口和内部动作误算为两次执行。

## 6. 跨层连接与摘要

跨过程摘要至少包含：候选目标/绑定条件、输入输出依赖、引用/存储关系、可能读写的位置与范围、分配/逃逸、正常/异常等完成、RNG/外部/顺序及必要生命周期效果。
摘要以定义/源码版本/静态上下文为范围，不伪造 `ObservationScope`，不把未观察到写解释为无写。

参数透传可以跨任意层；内层运算读取外层输入的事实沿端口组合。常量只沿受支持且已确定的规则传播，不执行 arbitrary Python 来求值。
返回引用的 alias、返回数据的内容、返回状态的版本分别连接。相同内容不推导对象相同，实际参数名相同也不推导值相同。

call graph、points-to/abstract heap、effects 和属性共同求不动点：

```text
源定义及初始操作
→ 候选调用与输入绑定
→ callee 摘要/返回对象传播
→ 别名和状态影响细化
→ 类型/常量/形状等事实更新
→ 重新派发受影响任务，直到当前抽象域稳定
```

递归调用使用调用图 SCC；循环使用回边、block parameters 和 state joins，不无限展开。
必要时使用上下文敏感摘要；上下文未区分的输入应安全合并，不能借一次调用的精确事实推断其他调用。
已解析区域可用 may/must 读写、alias 和 ModRef 查询排除无关状态写；粗 world 只是保守起点。

首个静态 linker 使用 `StaticCallSite/StaticCallTarget` 记录原 caller/callee 的 artifact 命名空间、Use→formal、各返回站点和 completion→landing 关系；它们不是新的操作、值或 Invocation。目标来自原调用候选、函数创建和 reaching/alias/import 关系，单一候选也不提升为真实目标。callee 的粗 world 与 caller world 通过显式接口映射，不能按相同 LocationID 或标签认作同一状态域。defaults、closure cell、G/B 与细粒度 effects 未连接时逐项保留 frontier。
关系分片与原图共处一个 current root。固定 source-basis receipt 只保存输入身份和原分片声明，解决 manifest 更新后旧 SHA 的自引用问题；后续更新 body 或源码目录时废弃这些派生关系，重新计算。源程序调用总数、已枚举 canonical CALL 与已发布关系分别计数，预算中断不能解释为没有消费者。
较粗源视图的 OPAQUE 不阻断已证明的规范展开：原 SG 操作、SourceAtom/AST Call 与 canonical callee Use/invoke 端口都准确匹配，而计算 overlay 确实缺失时，记录明确的 source-view refinement，继续保留规范依赖；不能伪造旧计算记录。查询的 caller 是保存图的命名空间，实际操作所属 Region 从原图推导，不能误读为观测到的调用帧。

## 7. 属性事实与约束

拟增加的分析事实层复用既有 ValueID/UseID/OperationID/LocationID/RegionID，不形成第二个 ValueGraph。
事实记录 subject/property、程序位置与上下文、抽象值、依据、依赖和前提；符号依赖也回指这些 ID。

属性域可使用精确常量、符号表达式、候选集合/区间/约束以及 top（不确定）。各属性组合；shape 的已知维度与未知维度分别保留，并保留跨属性/跨值的关系约束。
不可达的 bottom、尚未计算的工作状态与 unknown 不混同。NOT_APPLICABLE 不伪装为未知；冲突事实需检查前提/来源，不任意挑选。
分支合流保留共同必然事实和各分支条件关系，不能把某一分支事实变成无条件事实。

Tensor 首批属性包括类型/shape/dtype/device/layout/stride/offset、符号存储与范围、alias、内容来源和相关状态版本。
只解析标准算子语义或已解析实现；`.to()` 不自动成为物理复制，`expand()` 不自动成为完整分配，`.eval()` 不自动成为无状态函数。
不记录完整 Tensor 数值或强行比较样本元素。数学内容可由符号表达式/常量表示；shape 相同不是内容相同的证明。

未知物理地址不阻止 alias/范围推导；源码可证明的无相关写即可支持不变性推理，不要求运行时 epoch。
shape/内容可变时，事实绑定原状态版本及读取点；原位写、resize、可能共享外部写分别使相关事实失效或合并。
分析缓存按源码、规则、前提和输入摘要版本失效；不得复用已经改变的依据。

## 8. Python 和原生边界

默认参数、闭包、模块/类 namespace、descriptor、运算符分派、kwargs 展开、隐式迭代、清理与 finalizer 都可能跨层影响数据和状态，需明确语言规则。
函数/生成器创建不等于执行 body；async/generator 的创建、驱动和恢复是静态协议结构，不能虚构已发生的动作。
import 值恒定可由依赖图推导；删除初始化操作还需要其 effects/可达依赖分析。常量事实不能代替这部分分析。

原生实现可使用已有源码、接口 schema 及明确版本化语义摘要。schema 声明的 alias/mutation 与实际内容等价是不同事实，不能过度推导。
摘要/声明必须保留范围、完整性和前提；未知维度不得默认空效果。后续补源码或规则只细化相关边界，不全盘重建。

## 9. 静态资源层

静态 ResourceDefinition/Requirement/Use 表达 CPU/GPU、DRAM/HBM/pinned memory、文件/SSD/NVMe、stream/线程角色的约束和依赖。
硬件规格可由目标平台描述提供；具体物理地址、allocator 实例、kernel 选择、实际复制和完成时刻可保留符号/候选，不为建静态图而启动探测。
文件内容、位置/游标和 RNG 等作为状态；读写/等待是操作。媒体载荷不同不新增基础实体类别。
只展开程序可表达/调整的接口和必要依赖，不重放完整 FD 表、OS 内核结构、机器指令或默认采集 cacheline/性能计数器。

## 10. 输出和效率

当前没有新的存储格式或数据库要求。优先复用既有 codec/ID 引用，以源码单元/定义为结构分片，摘要和上下文事实单独索引；source text/schema/资源定义共享。
循环/递归保存结构模板与约束，不枚举动态实例或所有路径。查询按需展开相关片；建图任务可以按模块/独立 SCC 并行，跨边界由显式接口合并。
所有分析在一个正在开发的代码版本上运行。拟实现的输出只保留 `artifacts/current/static/` 当前发布结果，不创建日期归档或大 JSON 单文件。

预算受限时输出准确停止位置、受影响范围及精度原因；不能以缩小分母、漏路径或不完整摘要声明整图成功。

## 11. 可查询的完成标准

应分别回答：哪些源码/定义已登记，哪些主体已展开，哪些跨层端口已连接，哪些效果已闭合，哪些字段/关系已确定或符号化。
对每个未知回答 subject/property/relation、具体原因、影响范围和已尝试的静态推导；将缺输入、缺源码/语义、未实现和预算限制区分。
所有可得材料的图中结构、关系及依据可追溯；运行记录不是分母或完成条件。
第一阶段不生成优化许可、不修改目标源码、不运行正确性或性能实验。

## 12. 已有基础与方法来源

已有纯源码入口 `prepare_source_text`、结构化 lowering、有限 builtin/import 求值及规范 IR 校验可复用；完整静态目录、自动跨过程 effects/alias 固定点和统一事实层尚未贯通。
本设计借鉴编译器方法，不要求改用某个外部框架，也不将这些框架的局部能力写成 SCAR 已实现：

- [Python AST](https://docs.python.org/3.14/library/ast.html) 与 [symtable](https://docs.python.org/3.14/library/symtable.html)：前端语法/作用域基础。
- [MLIR DataFlow](https://mlir.llvm.org/docs/Tutorials/DataFlowAnalysis/)：抽象域、合流与迭代传播。
- [LLVM Alias Analysis](https://llvm.org/docs/AliasAnalysis.html) 与 [MemorySSA](https://llvm.org/docs/MemorySSA.html)：读写、别名和状态依赖。
- [MLIR Side Effects](https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/)：效果、资源和可移动性的独立建模。

## 13. 主体增量构造

已保存的 source/semantic/source-semantics/CFG 是主体构造的共享输入。增量步骤按文件解码一次并核原 descriptor，构造一个私有 prepared/sealed session，再按完整词法目录逐入口派工。
每个 canonical body 使用单独容器引用上述共享源片，保存原规范图及 metadata/interface/structured/language；不把全份源码图复制进每个函数。
缓存键包含源片、精确 entry、规则/能力/编译条件、实现 producer 和预算；成功缓存只能用于这些条件未变的原主体，不能升级为运行时 memoization。
未支持、准备失败和未派工的入口仍保留在整个目录分母。模块/类/async/generator 的静态 entry adapter 必须明确实现，不能通过伪造运行 frame 使它们进入已完成集合。
