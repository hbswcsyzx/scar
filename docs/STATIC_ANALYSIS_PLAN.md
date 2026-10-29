# SCAR 纯静态分析开发计划

## 目标与边界

SCAR 的目标是为合法代码化简建立尽可能完整、可查询的程序模型。先建图，再讨论化简。

本计划只描述静态建模。构建过程中不导入或执行目标源码，不要求 CapturedCode、CodeWitness、trace 或 profiler。

统一沿用 canonical Program IR 及既有源码对应；静态分析结果附着在已有定义、操作、值、Use、状态位置和源码引用上。Execution IR 不作为当前入口或前置。

不创建第二套权威程序图，不以序号或源码名称推断调用、别名或因果，不把“未观察到”解释为“没有”。

静态未知是合法结果。不能推出的关系要保留候选、条件和缺口，不能删掉它们以换取更高完成率。

不收集或保存 Tensor 数值。只推导类型、shape、dtype、layout、device 等有源码依据的描述及其约束。

不增加 backend、detector、benchmark，也不把静态建模与优化选择混在一个阶段。

## 进度状态约定

“部分已有”表示代码已提供可复用的局部类型或算法，但目标范围或语义仍不完整。

“未完成”表示计划能力尚未形成可查询的 canonical 关系，不以存在同名源码文件作为完成依据。

“源码缺失”表示分析所需源码不在选定源边界内，或无法取得；不能归为语法不支持。

“预算耗尽”表示本次受限工作未覆盖剩余输入；不能归为静态未知或安全拒绝。

每个事实须标明来源、原始 ID、推导规则、前提和状态。派生 ID 只能标识事实记录，不代表不同 ID 对应不同运行时对象或不同内容。

静态候选、条件推导、已证明源码事实与运行时证据必须分开。此计划不以运行时证据作为静态建图资格。

## S0：工作区与架构

**状态：root 已完成。**工作目录与职责边界已收敛，现有 canonical IR 为建模基础。

本阶段完成只说明有了受控开发位置和架构方向，不表示源码、调用、状态或字段模型已经完成。

延续现有 `scar/ir/program`、`scar/ir/semantics_v2.py`、`scar/ir/v2` 和查询/codec 机制；新增能力优先扩展这些实体或使用带原 ID 的派生事实。

S0 不设建模覆盖率门槛，不产生额外历史报告或 gate 目录。

## S1：纯静态源目录、词法定义与语言支持台账

**状态：源码目录、词法/编译器作用域及逐入口语言规则/前提台账已实现；全部语言语义展开仍未完成。**
新增 `static_sources` 全源根扫描、`static_lexical` 全 AST/定义目录、`static_program` 并行源码图及 `static_imports` 跨文件候选连接。LeWM 已实际离线构建 582 源文件，登记 12,550 个入口/上下文；581 个 `.py` 有源码图，1 个 `.pyi` 保留为声明。没有运行捕获见证或目标代码。
12,550 个入口均保留规则、producer、前提和具体缺口。隐式 scope 的 symtable 目录已保留，但其语言级语义展开仍未闭合；不能将 `UNEXPANDED` 或 READY_TO_ATTEMPT 写成“支持”。

**实质功能**

- 明确项目根、入口、搜索根、编码和文件边界，读取源码字节并记录 SHA、规范路径与解析配置。
- 建立全部词法模块和定义目录：模块体、函数、方法、类体、嵌套函数、lambda、comprehension、生成器、异步定义及适用版本的 annotation/type thunk；按源码作用域和定义阶段区分同名定义。
- 对每项记录 canonical source/definition 引用、源码跨度、词法父级、定义种类和静态支持状态。
- 遍历所有导入语法并保存本地候选、外部依赖、歧义、动态导入和执行语法等边界；候选闭包不冒称运行时导入闭包。
- 建立逐语言构造支持台账，记录对应 AST 语法、lowerer、已有协议、缺失语义和可查询缺口。
- 给每个目录项明确标记：可进入 lowering、仅有源码、已知不支持、依赖源码缺失或本次预算未覆盖。

**复用与必要接口**

- 复用 `scar/analysis/source_discovery.py`、`program_lowering.prepare_source_text`、`SourceSnapshot`、`SourceReference`、`ProgramInventory` / composition 和现有 codec。
- `prepare_captured_source` 及 `SourceCodeEvidence` 只作可选的后续对应信息，不作为静态定义生成条件。
- 新增的最小接口是 source-root 驱动的静态目录构建/读取入口，以及静态定义状态和语言缺口的表示；不得复制一份独立 Definition 图。
- 为 `source_frontend_worklist` 增加静态目录调度模式，不能从已有运行调用分母推断词法定义分母。

**离线验收**

- 对同一源码字节、根路径和配置重复构建，目录成员、源码引用及身份稳定。
- 每个 AST 定义均有唯一原始源码归属和一项支持状态；嵌套定义和同名定义可区分。
- 用记录的文件数、字节数、定义数、导入候选数和各类边界核对输入分母；预算停止须有剩余范围。
- 检查构建流程没有调用目标 import、执行、动态观察或 CodeWitness 解析入口。

## S2：结构化 canonical lowering、层次展开与跨层端口

**状态：部分已有，未完成。**`program_lowering` 与 `structured_lowering` 已能为有限 Python 子集构造 canonical operations、values、uses、control/completion 和源码链接；当前 CALL 目标、heap/global 写入及部分语言协议仍保留缺口。
首轮全量静态派工 7,055 个普通函数：5,908 个生成规范图（保留缺口），516 个规则 shape 不支持、546 个 lowerer 不支持、85 个构造错误。随后修复这些构造错误并接通模块/类/协议，当前累计 7,922 个入口有图，其中类/前导仍含精确展开义务。其余入口仍完整保留，不把目录或前缀完整解释为主体完整。

三项主体接线已实现：模块的 heap store、If 和 function creation；comprehension 的递归目标解包与局部异常清理；class 的独立 prepared-namespace/closure/cell ABI 与待展开主体接口。均沿原源码 ID 构造规范图。真实 eval 模块已展开全部 17 条顶层语句、18 项含嵌套语句记录、325 个操作，source wrapper 9 / core 30 读回及独立静态重新编译通过；没有运行模块初始化。完整类体及全部 Python 语法仍未完成。
模块使用明确的 BODY profile，在既有 paired exception/world 接口上扩展规则；旧前缀 profile 保留原含义。class body 的 normal payload 与外层 class construction result 分开：前者返回编译器 class cell 或 Python None 引用，后者才产生经 metaclass/decorator 处理的对象。真实入口的 core 31 读回通过；suite 的局部 continuation 与父级 construction 仍分别记录，不能以返回了 class cell 当作已建好最终类对象。

原目录的全模块/类边界批次与融合 store 修复已完成。class suite 与 compiler 前导已实现实际操作展开；全部 1,183 个类首轮 suite 发布耗时 473.28 秒。本轮 method profile 将原 42 个双结果 ABI continuation 推进，20 个 suite 完整、22 个到下一处明确协议，当前 1,138 个无 suite continuation、45 个保留精确 continuation。callable/optional-self/boolean selector 与 Python None padding 明确分开；隐式 self 尚不能直接套普通实参签名绑定。继续沿原 prepared mapping、G/saved-B、closure/local cells 核对未支持协议；父级 class construction 的 bases/metaclass/hooks/decorators 另接原端口。
独立 `SLICE_ACCESS_314_V1` 已用 compound invoke 连接 `BINARY_SLICE`、`STORE_SLICE` 与 stepped/tuple `STORE_SUBSCR` 的原 receiver/bounds/RHS/world、正常和异常消费，不伪造 combined bytecode 中没有独立产生的 slice Value；与既有 `BUILD_SLICE` 合同分开。233 项增量构造和 5 项错误复发已发布，新增 160 个有规范图的函数，ERROR 为 0。模块专用 profile 仍有未接入的新 slice capability 边界，不能把函数实现算成全部上下文支持。模块首 docstring 按编译器的 `__doc__` mapping 写入建图，不能当普通表达式丢弃。
全批及错误修复已发布：12 个模块自有 annotation cell 使用新 compiler profile/source wrapper 10，原 core 30 entry ABI 不变；前导子 Region 与精确布局记录已接上正常/异常 world；新 wrapper 11 又将已知 macro 拆为真实操作，cell handles 返回父 frame/后缀并保持到 frame exit，deferred child 仍待展开。另一个 tuple-key MEMORY 校验已修复。当前构造 ERROR 为 0，不能据此认定语义完整。compiler layout 已作为来源事实保存，后续继续展开已知 prefix 阶段和生成 child，不能永久停在前导边界。

**已核实的当前实现欠账**

417 个函数 lowerer 不支持项中，78 个缺唯一 computational record、60 个 nested with cleanup、42 个 target-child BinOp、41 个 comprehension parent cleanup、28 个常量槽对应、16 个 target-child Compare。另有 480 个规则 shape 不支持。它们不是已证明的运行时不可判定；不能只修单个函数或把错误转成 UNKNOWN。局部表达式的 source/SG 连接继续补齐，同时推进已有主体的跨过程传递。
3,731 个缺 adapter 项中，annotation context 2,482、listcomp 583、lambda 235、genexpr 210、dictcomp 146、setcomp 22、function 52、module stub 1。目录、内联 scope 和独立主体需要按实际 compiler 布局连接，不可机械地为每个 comprehension 造 Python frame。

**实质功能**

- 为 S1 中每个可支持定义构造其模块/函数体 `ProgramGraph`，保持 Operation、Value、Use、Region、Block、Completion 的原始身份。
- 按词法和调用层次展开可建模的定义体；以 Region 嵌套和已有 body/module composition 表达层次，不扁平复制操作。
- 将源码表达式、实际参数、关键字、返回点、异常出口和状态接口连到各自原 `OperationID`、`UseID`、`ValueID`、completion port 与 `SourceReference`。
- 每个已发现调用都进入 canonical IR；唯一目标尚不能确定时保留候选目标和动态 dispatch 缺口。
- 扩展赋值、属性/下标写入、解包、导入、闭包、descriptor、generator、async 等语言协议时，逐项定义状态与控制语义。
- 结构化 lowering 遇到未实现语法时，保留输入定义、已生成的合法前缀及精确缺口；不静默跳过节点。

**复用与必要接口**

- 复用 `ProgramGraph`、`SourceProgram`、`LoweringMetadata`、`CallTarget`、`CandidateArgument`、`CandidateResult` 和现有 completion/region 验证。
- 继续以原 Use→formal、completion→result 表达 body 接口；不要把 InvocationKey、CodeID 或运行时父子调用当成静态操作 ID。
- 新增必要部分限于静态全目录 lowering 入口、跨模块 body 引用，以及现有 IR 无法表达时的最小语言协议节点/字段。
- 不另建一套 source call graph、值图、control graph 或后端表示。

**离线验收**

- 选取独立源码样例覆盖模块调用、嵌套函数、关键字/默认参数、返回和异常路径；构建和 codec 读回只处理静态输入。
- 查询从原 caller `UseID` 到候选 formal，再从 callee 返回端点回到 caller completion；每条关系可追溯至源码跨度和签名。
- 汇总全部 S1 定义、成功 lowering、部分 lowering 与未支持原因；检查 operation/value/use 映射无悬空 ID。

## S3：调用图、points-to、状态与 effects 联合固定点

**状态：基础类型与局部候选部分已有，联合静态分析未完成。**`CallTarget` 可表达局部条件候选；`effects_v2` 有 effect 维度和 coverage 类型，但现有闭包器面向显式 scope，不能替代静态调用图或静态定义摘要。
source-only linker 已发布 v4 qualified namespace/factory/environment 关系。有界扫描 400 份产物（365 有图），269 份分片实际保存 2,069 个 CALL、41 条有绑定来源的条件目标、123 条跨主体 namespace flow、8 条 qualified factory、76 条环境依赖。123 条 flow 中 5 条经两次真实调用桥，工作队列处理 77 次后在该范围内稳定；8,419 份产物未扫描，不能称整程序固定点完成。未接通真实callee来源的旧声明提示单独保留，不再独立生成目标端口；默认字段初始化依赖也不等同于调用时 formal 的完整传播。
STORE/LOAD/world/CFG、查找优先及中间效果保留明确条件；正常覆盖仅在 mapping 提交输入等 guard 下成立。MAKE 的原 code slot/declaration/正常结果可连共享 body，APPLY 的结果独立，真实 eval.run 的装饰器返回关系仍开放。下一步用通用返回/环境/alias/effect 分析解决这些条件与未知调用，不按名字补目标，也不把当前条件边当成已证明的 must-flow。

**跨主体 namespace 闭环：已实现并在 LeWM 源树的有界产物上发布；完整 S3 仍未完成。** 候选队列已使用 qualified body/value 来源，环境激活会失效并重新求解相关 callee/下游读取。factory 带其原 body，不能拿 module 的 OperationID 到 callee index 中查找。当前实现只求条件 namespace 依赖的有限工作队列，不称为 points-to/effects 联合固定点已经完成。

- 为 namespace 分析增加 `bindings_at(owner, key, operation, world_use)`，查询真实控制点的可能定义，不伪造一次 LOAD。
- 组合原 STORE→外层 CALL 路径、G environment/state-entry 路由及 callee entry→LOAD 路径，产生引用原端点的条件跨主体 namespace flow。module 的 STORE_NAME 写 L、factory 取 G；只有 loader 合同证明 L=G 或保留显式 owner-alias 条件时才相连，不能直接合并两个端口。
- 新环境边激活相关 namespace reads，新 reaching binding 激活目标解析，新目标再传播参数/返回/环境和摘要。按调用图 SCC 与有限符号上下文单调迭代，稳定后发布；不能把当前一次 `_calls()` 后 yield 当作固定点。
- 自验收使用纯源码的 `module 定义 h/f → module 调用 f → f 内 global h 调用`：应真正得到 h 的 qualified factory/body 目标；插入同 key 写入时保留正确覆盖/分支条件；递归必须终止且不循环自证。随后用同一工作队列接 decorator actual→formal→return，以及 defaults 初始化→字段/元素读取→缺省 formal，不另造业务规则。

正常 CLI 纯源码多层链已真正得到 4 条目标边、3 条跨图依赖，最长 3 个调用桥；公开 query 同时验证原 factory/namespace/Use/world/CFG。覆盖反例不再得到旧 factory 目标；递归有种子收敛、无种子不循环自证。预算停止前的有效 CALL 记录保留。旧 metadata/CALLS 中没有实际 callee 来源支持的提示不再独立生成目标端口；真实 nested factory 通过原 parent code path/CodeKey/slot 校验，避免以丢弃合法调用来消除假阳性。LeWM 实际批次的数量与剩余缺口以 current 发布结果为准。

**下一步消费的数据关系仍待实现：** SourceArgumentPort 的 actual→formal、正常 completion 的 terminal→caller landing、decorator application 的 actual→formal→return，以及 defaults 字段/元素→缺省 formal。它们应进入同一 qualified 来源工作队列；不能把 arbitrary computation 的所有输入都当作输出的引用别名。类型/常量/ModRef 分析继续用于消解条件，callee body、shape、地址等属性各自保留已知部分与具体缺口。

这些工作与剩余 S2 语言实现并行推进，不等待所有语法补齐；单纯存在新边或 reader 通过都不等于全程序模型已完成。

**实质功能**

- 从 AST、源签名、导入事实、函数值和既有 CALL operation 推导零个、一个或多个静态目标候选。
- 沿 canonical caller actual Use、callee formal Value、返回/异常 completion port 建立跨过程条件接口；参数重排、默认值和变长参数按签名规则展开。
- 建立保守 points-to / alias 集：用静态分配站点、构造表达式或外部输入作为抽象 token，挂回现有 Value/Use/Location；token 不是运行时身份。
- 精确局部绑定可强更新；堆位置还需证明抽象位置唯一且非多实例 summary。属性、全局、容器、闭包及可能逃逸位置按别名/基数采用弱更新或保守约束；单一分配站点不自动代表单一对象。
- 汇总 may-read/write/allocate/free/alias/escape/raise/external/order 等 effects，并沿调用候选在递归 SCC 上做单调固定点。
- 把每个状态位置、别名关系和 effect 目标连回原 `StateLocation`、slot、operation、signature 和源码事实。

**复用与必要接口**

- 复用 `CallTarget`、source formal/return interfaces、`BindingRead` / source semantics、现有 state slots 与 `effects_v2` 的 effect 维度和 coverage 表达。
- 如需静态 scope 或 summary，明确标为 source-definition 与源码版本；不能伪造运行 `ObservationScope`、Execution instance 或“观测为空”的证明。
- 仅新增可重算的静态候选、points-to 和定义级 summary 事实，引用 canonical IDs；不产生替代 program/dataflow authority。

**离线验收**

- 用相互调用、递归、别名、属性写入和逃逸样例验证固定点收敛、单调性和边界保持。
- 查询跨过程参数、返回、读写目标和别名时，返回原 canonical IDs、来源和条件。
- 插入无法解析的动态调用后，相关边/summary 变 UNKNOWN 或保守开放；不得因为缺项推导为 pure、无写入或无消费者。

## S4：常量、类型与 Tensor 描述的抽象事实和约束

**状态：局部推导已有，跨过程统一描述未完成。**`constants_v2` 和 `import_values_v2` 能对受支持的 builtin/local binding 或导入路径推导有来源的事实；它们不是完整 Python 类型、对象或 Tensor 抽象解释。

**实质功能**

- 在 S3 的值/别名与调用接口上推导常量、类型集合、可能值、整数区间、Noneability 和必要的约束。
- 对能由源码或已证明规则推出的 Tensor 描述记录 shape、dtype、layout/stride、device、稀疏/标量等属性；属性有明确 producer/input/constraint 引用。
- 沿构造、view、reshape、索引、算术和调用摘要传播描述；对于动态输入或未知 kernel 保留未知维度和约束，不猜固定值。
- 严格区分 Python 引用别名、逻辑内容、Tensor 描述和物理 storage/materialization；相同引用或 shape 不证明内容相同、storage 相同或可替换。
- 不保存 Tensor 数值，不从静态 shape 推出运行时 ready、设备完成、normal return 或无副作用。

**复用与必要接口**

- 复用 `StaticValueID`、source values、`ConstantReport`、`ImportValueFact`、canonical Value/Use/StateLocation 和现有 Tensor metadata 类型。
- 只有现有 canonical IR 没有字段时才增加带有来源、规则版本、条件与 UNKNOWN 状态的 typed abstract fact，并由原 Value/Operation 引用。
- S4 可反向改进 S3 的目标、别名和 effect target；S3/S4 必要时按单调规则交替迭代到稳定，不要求一次性线性 pass。

**离线验收**

- 对常量、带类型参数、简单 Tensor 构造和形状变换样例核对推导值与约束来源。
- 对未知维度、外部函数、用户自定义运算和可能 alias 的样例确认未知分量保留，其他可证明字段仍可用。
- 检查 facts 可通过原 Value/Operation/Use 查询；不出现按相同 shape、名称或裸地址合并的等价关系。

## S5：LeWM 与独立静态源码的完整离线建图、导出和查询

**状态：尚未完成。**局部 source/native/effect/value 模块不代表 whole-program 静态覆盖。S0 完成不改变本阶段未完成状态。

**实质功能**

- 对固定版本的 LeWM 源码树及独立纯源码样例运行 S1–S4 静态 pipeline，覆盖全部所选边界内的模块、定义、操作、调用候选和字段事实。
- 对缺失源码、外部依赖、动态 import/dispatch、未支持语法和预算耗尽分别保留完整 frontier、输入范围与原因。
- 提供可从模块/定义进入 Region、Operation、Use、Value、state/effect 与 abstract facts 的稳定查询；查询可返回原 ID 与限定源码引用。
- 导出 canonical IR 和必要的压缩 catalog/索引，数据可重建，schema 版本明确，source SHA 可核验。

**输出约束与验收**

- 当前唯一输出位置为 `artifacts/current/static/`，已实现分片发布与查询；整程序完整导出仍未完成。不要新增日期报告、历史 gate 或第二个“current”输出。
- 报告准确区分源码目录总分母、建图成功数、部分项、缺源码、语言缺口和预算未处理项；不把样例通过宣称成 LeWM 全程序完成。
- 离线读回后验证 ID、source SHA、引用闭合、query 导航和所有 UNKNOWN/frontier；全过程无需导入或执行 LeWM。
- 只有 S5 覆盖、导出和查询范围达到事先声明的源边界，才可报告该边界的静态建图完成；完成不等于化简合法或收益已证。

## 当前执行：S2 主体与跨层连接

纯静态目录和 source-root 调度已落地，目录成员不再由捕获调用/CodeWitness 决定。
已有整个目录驱动规范 body 构造。当前补齐模块、类、generator/async 等静态入口和具体语言展开，修复真实源码触发的构造错误；同时将原调用 Use/形参/完成端口接到原主体命名空间，随后推进 S3 的联合分析，不以存在同名函数代替目标解析。

**优先接通已有结构的静态传递，而非仅继续增加局部 lowerer。** 已核实的连接欠账按以下依赖推进，均不需要目标运行身份：

1. 函数 `LOOKUP_GLOBAL` 的 G/saved-B/key/world 与 namespace 读分析衔接；不能因 producer 和 consumer 协议拼写不同漏掉现有端点。保持真正缺键才回退 builtins 的条件。
2. 原 factory 的 function-globals、默认值/关键字默认值、closure Uses → 函数状态 → 被调用环境/缺省形参。状态可能后改时保留读点/版本和条件，不直接断言创建时值永远不变。
3. 已有 decorator application 的 callable/argument/normal result → 通用调用与返回传递。源码可见的恒等 decorator 应通过 actual→formal→return 推出关系；不能无条件跳过 decorator。
4. import module value → namespace/export attribute → callable 候选。对已有源码继续按导出和状态规则传播，不能因为不是 `from ... import ...` 就停止；缺源码和动态 import hook 另保留边界。
5. 分解 namespace flow 的路径、mapping、fallback 和中间 effects 条件；能由类型/对象来源及 ModRef 证明的逐项消解，其余条件保留。不得删除条件假装已经证明。

以上不是已实现的联合固定点。当前 bounded resolver 对每个 CALL 仍报告 TARGET_SET_CLOSURE_OPEN；修复一条协议消费断口也不意味着跨主体 G 投影或整程序调用闭包已经完成。

首个交付包括：固定源根与配置、逐文件 SHA、逐模块/定义 canonical source ref、词法父级、定义类别、导入候选和逐项语言/缺失/预算状态；全部结果继续引用现有 source/definition IDs。

S1 停止条件：输入边界和预算明确；边界内每个解析文件和词法定义均有唯一目录项或具体解析缺口；导入候选与动态/外部边界可查询；重复静态构建的目录身份稳定；入口不调用目标代码，也不以 CapturedCode/CodeWitness 筛除定义。

达到这些条件即可开始 S2。未覆盖的源文件必须作为预算或缺失 frontier 留在目录中，不能删去或改写成“静态未知”。
