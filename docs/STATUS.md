# 当前状态

唯一任务：整程序纯静态分析与建图。唯一工作目录 `~/AAA/scar`、分支 `main`。

## 已实现并用于真实源码

- 纯源根入口 `scar static`：全文件扫描、编码与 raw/decoded SHA、命名空间候选、预算剩余范围；不要求 CapturedCode/CodeWitness。
- 全 AST occurrence、模块/函数/类/lambda/comprehension/注解和类型上下文目录；完整 symtable 及 compiler scope 关系。未知关联保留候选，不伪造真实代码帧。
- 四进程按源码文件构建已有 semantic、source-semantics、CFG 及有限常量事实；所有路径和未执行定义参与。
- 跨文件 import 候选保留原 source reference、alias 序号、控制上下文、模块初始化引用；导出/子模块、stub 与实际源码分别记录。
- 分片当前输出和 `scar static-query`，可查询定义、符号、原操作数、值/绑定及控制图；无第二套 producer/state 图。
- 可在不重建原源码图的情况下细化词法 scope 和 import 索引。
- 全部词法入口的语言规则/前提台账；按原入口 key 精准派工，全部入口继续保留在总目录。
- 静态模块编译来源、mapping frame 与精确 residual source；静态和运行捕获 root 分别编码，不伪造 CapturedCode。
- 模块 BODY profile 接通 heap 写入、If、函数创建/默认值/装饰器和首 docstring 的 `__doc__` 写入；comprehension 的递归目标与局部异常清理已接通，融合 store 按原 compiler 槽位/顺序解析。
- 类使用独立 ClassFrameABI 和 core 31：prepared namespace、外部 closure 与内部 compiler cells 分开。全部 1,183 个类已正式构造：1,138 个无 suite continuation、45 个保留精确 continuation；父级构造与 effects 等仍开放。新 method profile 明确 callable、optional-self 与 boolean selector，NULL 不伪装成 Python None 实参。
- 新 slice capability 连接 combined read/store 和 stepped/tuple slice store；receiver/bounds/RHS、partial 地址、正常/异常清理都有原端点。combined slice 不伪造独立 slice Value。嵌套函数 SOURCE_REPLAY 使用原 SourceReference 选择，不以短名作为身份。

## LeWM 当前实际结果

固定范围为 `../le-wm` 整个源码树，包含两个本地依赖源码项目；尚未把环境中全部第三方库源码纳入闭包。

| 项目 | 数量/结果 |
|---|---:|
| 源文件 | 582：581 `.py` + 1 `.pyi` |
| 原始源码 | 5,718,464 bytes |
| AST occurrence / 词法入口及上下文 | 762,839 / 12,550 |
| 原源码操作 / 源码图关系 | 469,005 / 2,057,190 |
| 计算语义操作 / CFG 节点 | 352,867 / 239,097 |
| 有限常量事实 | 76,788，仍保留原规则/前提 |
| 首轮源码图构造时间 | 388.13 秒，4 个分析进程 |
| 首轮 7,055 个普通函数规范构造 | 1,024.41 秒，4 个分析进程；5,908 个有图、85 个构造错误 |
| 当前已发布有规范图的入口 | 7,922：581 个模块、1,183 个类 suite、6,158 个普通函数；有图不等于完整 |
| 当前已发布规范操作 | 1,100,313 |
| 当前已发布明确不支持 | 417 个 lowerer 不支持，480 个规则 shape 不支持 |
| 当前已发布入口适配缺失 / 未派工 | 3,731 / 0；构造 ERROR 为 0 |
| 原 85 个构造错误复验 | 全部生成带缺口的图；另构造 eval 模块，共 86 个，113.63 秒 |
| 原图分片字节回读 | 3,488 片 stored/decoded SHA、JSON 容器通过 |
| 普通 typed reader | eval.py 的 SG、source-semantics、CFG 解码与交叉结构校验通过 |
| 公开查询 | eval.img_transform 与 solver/cem.py.solve 的原操作/控制记录读回通过 |

当前输出见 `artifacts/current/static/manifest.json`；大图不提交 Git，仅保留这一版 current。
细化另外保留 compiler scope 15,471 项的实际分类，以 manifest.catalog_refinement 为准确值，不把 scope 当运行 thunk。
本轮完整目录细化耗时 462.24 秒，保留 2,906 份原图片、不重建源码图；581 个模块、1,183 个类及 7,055 个普通函数共 8,819 个入口可进入构造尝试，3,731 个其他入口仍缺适配。可尝试不等于已建模。
全批四进程构造已结束并发布：1,767 个入口，耗时 1,639.52 秒；随后按原 key 修复 13 个错误并增量发布（15 项 68.94 秒，最终规则刷新 14 项 62.32 秒），没有重建原源码图。这是分析器建图时间，不是 LeWM 执行时间。
12 个 compiler-owned annotation cell 入口先以 source wrapper 10 接独立前导，后以 wrapper 11 将已知部分拆为真实 macro：cell 分配、code-slot读取、factory、set allocation、namespace store/setup。cell handles 正常经出口交父 frame/后缀、失败逆序清理并保留原 exception/traceback/world；原 entry ABI 不添 closure。deferred child body 仍开放，不能称完整模块。
小批 22 个入口正式发布通过（70.43 秒、4进程），没有重建原源图。七个 ClassSuite：PlanConfig 83、WorldModelPolicy 136、CEMSolver 262、两个 Costable 各74、两个 ConditionalBlock 各63操作，均无 suite continuation；有原 cell/closure/method/annotation factory 关系。另有同名生成 factory/装饰器 CALL 与 application 区分、不支持ABI保留原 stack continuation 的纯静态检查；没有执行这些程序。
全 1,183 类首轮 suite 构造四进程耗时 473.28 秒，替换了整类 3-op 边界；当时有 65 个 continuation。本轮对 42 个 method continuation、156 个 slice lowerer 拒绝、35 个旧 slice shape 项做 233 项增量构造，261.83 秒；随后修复并正式重发 5 个异常清理/协议校验错误，70.62 秒。最终新增 160 个有规范图的函数，20 个类消除 suite 后缀，另 22 个 method 类推进到下一个明确 control/compiler 缺口。当前共 45 个 class continuation、0 个构造 ERROR；没有重建原源码图。上述均为分析器耗时，不是 LeWM 执行时间。
静态 compiler layout 记录 names/flags/参数计数/local/cell/free 表，原索引与空名称均保留；不保存 Tensor 值或地址。body 失败时仍保存已有编译事实，公开 query 将其标为 SOURCE_COMPILATION_FACTS，而非运行观察。

## 仍未完成

**完整静态模型尚未完成。** 原源码图有 69,298 个 opaque 操作、450,176 项语义缺口、16,061 项控制缺口；它们是待分析结构/规则，不能算已完全展开。
12,550 个入口尚未全部完成 canonical lowering。普通函数已全量尝试；模块可构造受支持前缀和明确要求继续展开的后缀，不能把前缀图算成完整模块；类入口已有实际 suite；45 项续接协议、父级 class construction、resumable 和隐式类型/注解主体等仍待展开。
S1 的目录与逐入口规则台账已存在，语言语义完整性仍未闭合；S2 的完整规范子图、S3 调用/别名/效果联合固定点、S4 统一属性约束及 S5 完整导出尚未完成。
第三方源码/声明、动态目标表达式与别名/副作用仍有可继续静态推导的部分，不把这些缺口统称为“只能动态获取”。

### 缺口复审：为什么不能宣称静态分析已经完成

当前 manifest 的 `LOWERED_WITH_GAPS` 由“是否生成规范图”决定，**不是逐主体穷尽推理后的结论**。同样，0 个构造 ERROR 只说明分析器没有报告构造异常。二者都不能用作完整性证明。

- **实现欠账**：当前 417 个 lowerer 不支持项、480 个规则 shape 不支持项；包括 78 项缺唯一 computational record、60 项 nested with cleanup、42 项 target-child BinOp、41 项 comprehension parent cleanup。combined slice/store 的旧拒绝已推进，不能将推进后暴露的下一处实现欠账说成必须动态捕获。
- **入口与内联展开尚未核齐**：3,731 个目录项没有独立入口适配，其中 2,482 个 annotation context、961 个 comprehension/generator expression、235 个 lambda、52 个函数、1 个 stub 模块。部分表达式已经在父图内展开，因此不能把该数字直接解释成同等数量完全缺失的运行帧；仍须逐项核对其实际归属和缺失结构。
- **跨过程推理未完成**：当前 v4 索引只扫描 8,819 份主体产物中的 400 份，另 8,419 份尚未扫描；已消费跨主体 globals/状态接口，但 actual→formal、返回、defaults/cells、别名与 effects 联合固定点尚未贯通。不能将尚未推导的调用关系直接称为语言本身不可知。
- **材料范围不足**：当前包含 LeWM 源树和两个本地依赖项目，没有环境中全部第三方实现的源码闭包。源码缺失与已有源码但未分析必须分别报告。
- **静态边界与结构缺失混列**：例如 module 的常量槽/函数创建结构已经连接，但运行时 code 对象身份仍开放；该身份不应成为“缺少函数体结构”的依据。现有原始 gap 总数还混有这种证明前沿，不能用它衡量结构缺失率。类的前沿还被投影为统一 EFFECT_SUMMARY，查询时须结合原 class frontier 才能知道具体欠账。

上述分类是本次读取 current manifest 和实际 lowerer/linker 的审计结论，不是宣称已实现了新的自动缺口分类器。后续应分别闭合结构、跨过程关系和字段事实；未知地址等运行字段允许保持符号化，已有源码中尚未实现的规则继续作为实现欠账。

更关键的未闭环部分是 S2 产生的操作/Use/状态端点尚未充分进入 S3/S4：namespace flow 仍附带 mapping 提交、读取返回绑定及中间 effects 保持等条件，linker 对每个 CALL 都保留 TARGET_SET_CLOSURE_OPEN。缺少把源码上下文、类型/对象来源、返回和状态摘要反复传播以消解这些条件的过程。即使继续补齐局部语法，也不会自动获得全程序依赖图；受支持子集的联合推理应与语言欠账的修复衔接推进，而非等待所有语法实现后才开始。

已查到并修复一个真实消费断口：函数 lowerer 发出 `LOOKUP_GLOBAL`，namespace 分析原来只接收 `LOAD_GLOBAL` 等协议，跳过了已有 G/saved-B/key/world 端点。修复后，从 current 中现有 `eval.img_transform`、`eval.run` 的规范图重新解码并建立 namespace 索引，分别接回 7、32 个函数 global read，原正常结果与两个 namespace owner 均保持；耗时约 0.50、21.64 秒。仅运行静态图 reader/分析器，没有执行函数；此检查没有重发 current 的调用索引，也没有证明跨主体 G 投影或任何缓存合法性。

## 下一项

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 继续默认参数的实际字段/元素读点、装饰器 application 与模块属性传递，推进别名和 effects 联合固定点；并补齐父级 class construction、45 项 class continuation、resumable/隐式入口、target-child expression/with 等语言缺口，随后接统一类型/Tensor 属性。
本轮没有导入或执行 LeWM，没有运行目标样例、trace、benchmark、优化或动态验证。仅运行分析器、解析源材料与读取/校验生成的静态图。

### 新实现与正在进行的 LeWM 实测

schema v5 已将显式实参→形参、正常 reference 返回→caller landing 接入同一 qualified 来源工作队列。求解分别保存原 CALL/目标构成的上下文链：返回时压栈、formal 读取时只沿匹配调用出栈；明确上下文不退回无上下文并集。最终展示可以合并同一静态 CALL，不能拿该并集反向激活目标。新事实会重新调度跨主体的原 requester；context/depth/fact 预算在索引写入前统一检查，拒绝新事实不清除已接通事实。

纯静态独立源码的 14 个 CALL 产生 15 个条件目标、17 条参数来源和 29 条返回来源展示记录；六个 identity/apply/relay 最终调用点均保持 a/b 隔离，31 次队列处理后稳定。其全局唯一事实为 4 条 namespace、28 条参数/返回，不将多处展示的支持关系重复当作新事实。局部 typed facts 复用前后，该同一输入的 clean 分析器链接耗时分别为 93.67 秒和 44.132 秒（各一次测量）；带 cProfile 的 363.12 秒只用于定位分析器重复解码，不作为对照性能。以上不是 LeWM 执行或加速数据。

唯一新增 integration 回归已通过（117.75 秒）：identity、回调、多层返回、局部覆盖写入、无种子递归和非空上下文的公开 query；样例源码没有执行。schema v1–4 严格迁移及字段夹带拒绝检查通过；读取真实旧 v4 publication 时，新值流标为 NOT_RECORDED，不因新 reader 存在而假称旧图已有 v5 证明。独立 public validator 每次仍从原输入验证，局部复用的不是跨输入“已验证”标志。

LeWM 新一轮链接已启动，输入仍为 current 中的完整源边界，尝试全部 8,819 份主体产物，不再限定前 400 份；时间上限 7,200 秒，其他上下文/事实/输入预算仍明确保留。每完成一个源 unit 就处理已接通的队列，后来的来源继续触发重算，避免只枚举到耗尽时间才开始传播。输出采用原子发布；运行结束前，上面的 LeWM v4 数量仍是最后已发布结果，不能将独立样例的 v5 数量冒充 LeWM 结果。本次全量尝试结束后必须核对实际处理范围、剩余项、构造/读取错误和公开查询；即使覆盖全部现有主体，也不等于剩余语言入口、第三方源码、points-to/effects 和类型属性已经完成。

## 当前离线检查

582 项源目录重复扫描身份稳定，保留源码指纹与原文件一致。将文件预算设为 2 时，准确保留剩余 580 项，没有从分母删除。
SCAR 源文件语法检查和所选图的普通 typed reader 均通过。生成的 import 索引 receipts 通过，索引构造问题为 0；外部源码、导出和 namespace 候选仍是明确 frontier，未据此声称 import 已全部解析。
已修复真实源码触发的六类构造错误：lambda 声明未绑定出口、增强赋值的 Store-context 读取资格、tuple 的 traceback ABI、lambda 地址交接、空 return 的控制流来源、generator 常量 payload 来源。修复后全部原 85 个 ERROR 入口经过纯静态构造，未放宽 core validator 或改成 UNSUPPORTED。

## 规范主体静态展开

已增加独立 `SOURCE_COMPILATION` 证据：按固定源码与 compiler profile 仅 compile、不 exec；准确匹配定义位置/词法 qualname/父级常量路径/装饰器首行，不创建假的捕获见证。
已有 call-expansion、try/with、nested function、lambda/comprehension、constant 等 lowerer/validator 共用编译布局接口。模块使用 SourceCompilationCodeRef/SourceCompilationFrameRoot 和静态 declaration；动态证据保留原含义。

增量 `--expand` 按文件复用原4源片、一个sealed lowering session和一份静态编译布局；规则明细单独保存在原unit的rules分片，body容器只引用共享源片。已知失败/未派工入口保留，缓存键包含源输入、规则、编译条件与相关producer，不是运行时memoization。

真实 `eval.py:img_transform` 的首次纯静态规范构造通过：3.41秒、92操作、157值、1 Region，normal codec读回通过；32项原effects/dispatch等缺口保留。公开query可同时投影canonical端口、Value→source、原控制图和具体规则/shape缺口，分别标明哪些只是结构校验。这里没有执行该函数。
全普通函数首轮构造与错误复验已结束。真实 eval.py 模块已用静态 source wrapper 9 / core 30 生成 325 个操作，17 条顶层语句、18 项含嵌套语句记录全部展开，没有剩余源码后缀；普通 reader 独立重新编译保留源码后往返成功，公开 query 检查 6 份 receipts。它仍有 49 项原 namespace/effects 等前沿，完整语句拓扑不等于完整导入、调用或效果分析。
真实 eval.run 和 eval_ff.run 分别构造 2,305、2,080 个操作。三个融合 store 的 comprehension 所属函数在修复后离线构造及 source/compiler/core 读回通过（317、108、437 个操作）。eval_wm.run 现在生成 3,216 个操作并接通两个 BINARY_SLICE；同一已发布 payload 的独立整图 SOURCE_REPLAY 已通过。其 `ep_id` comprehension 词法候选关系先前受字典插入顺序影响，现按原 SlotID 规范化，编译器 name/local/cell/free 表仍保留原顺序。另两个真实 slice 函数分别以 75、241 个操作通过完整重放；没有执行函数。
Costable 与 ConditionalBlock 两个真实类入口均以原 SG DefinitionID 构造并公开查询 core 31；normal payload 分别为 Python None 引用、class cell 引用。新 suite 分别有 74、63 个实际操作并无 suite 后缀，cells、closures、code reads、factories 和 namespace 读写都有原端点；生成 child body 与父级 metaclass/namespace 供给仍未闭合。
另以真实 CEM 模块检查 docstring 的 __doc__ 写入：192 个操作、11 条语句前缀，仍保留一条 class 后缀；source wrapper 读回和独立静态编译通过。没有执行模块初始化或函数体。

## 跨主体静态关系

`--link-calls` 已在当前图上发布 v4 派生关系。扫描 400 份主体产物（365 份有图，依赖来源另按需读取），链接与发布 521.93 秒；269 份关系分片经普通 typed reader 全量读回，共实际保存 2,069 个 CALL、41 条有来源支持的条件目标、52 条同主体 namespace flow、29 条本地 factory、8 条 qualified factory、123 条跨主体 namespace flow、20 条实参边、85 条 completion、70 个 normal return 和 76 条函数环境依赖。预算停止前已验证的 CALL 全部保留，不再丢弃末尾 10 项。另 8,419 份主体产物未扫描；本批 source call 目录涉及 95 个文件、4,710 项，整树为 47,135 个 AST 调用点，不能把该批视为整程序调用闭包。
跨主体 flow 中 118 条经过一个原 CALL bridge、5 条经过两个；77 次工作队列处理后在本次范围内稳定。它们实际连接外层 STORE、环境/状态接口和内层 READ/CALL，不是仅计数未消费的环境边。当前 41 条有绑定来源的条件目标，与前一版混合提示的 92 条统计口径不同；本版另有 51 项未接通 callee 来源的声明提示，保留为 SOURCE_TARGET_HINT_UNCONNECTED，不生成目标端口。不能只用目标数量变化判断优化损失或加速。
真实 `profile_phases.py::run` 的同一 CALL 已通过公开 dependencies reader：1 个有来源目标、1 条双桥 flow、1 个 qualified factory，stored schema 4、v4_dependencies_checked=true。路径是原 module→main→run，最终 factory 回到同文件模块中 `build` 的原 code slot `[3]`；原 namespace、factory normal/code Use、environment owner routes 与 CFG 全部读回核对。此查询耗时 89.033 秒，仍偏重，是当前效率限制；它不是目标程序执行时间，也不是优化性能数据。
正常 CLI 纯源码链 `module→f→g→h→leaf` 实际产生 4 个目标、3 条跨主体依赖，最长 3 个调用桥；公开 query 验证原 factory/namespace/Use/world/CFG。覆盖 `h=9` 后旧 factory 不再成为目标；正确 nested factory 仍可产生目标，被 shadow 后无目标。低层编译 verifier 支持任意深 parent code path，真实早期 body 缺少 layout 字段时从本次静态 compile 重建，不丢整图或假称旧数据曾保存该事实；原 CodeKey/source/namespace/compiler 字段仍全部严格核对。
默认参数初始化依赖另有纯源码端到端正例；不等同于 defaults 字段/元素到调用时 formal 的完整传播。旧 v1/v2/v3 wire 严格迁移并拒绝夹带 v4 字段；错误 namespace、factory、constant slot 及已覆盖 alias 路径均有拒绝验证。公开 query 的原端点核验不等于独立源码语义重放，条件仍保留。
stub 候选先前错误地中止 `_config` 中两个正常函数的 CALL 枚举；现保留 IMPORT_DECLARATION_ONLY 并继续其它候选，两函数分别保留 3、4 个 CALL。最终发布只保留 stub 声明边界和预算前沿，没有 CANONICAL_BODY_UNREADABLE；没有把 `.pyi` 当作已构造的运行主体。
关系引用原 owner/key/payload Uses、读结果、world、CFG 与 factory/code slot；按明确 mapping/path/effect 条件成立，不是内容恒等或无副作用证明。三个独立纯静态 case 通过：正常覆盖、分支保留多候选、装饰器结果截断；临时材料已删除，没有执行这些程序。
真实 eval 模块的 run() 已接通一条 STORE→LOAD 条件流，并准确停在 APPLY 结果，保留 DECORATOR_RETURN_RELATION_OPEN；没有伪造原 run body 候选。public query 复核原 receipts、端点和 CFG，并与普通 compiler-prologue core join 分开标记；没有声称查询重放源码或运行目标。
这份已发布 v4 的目标集合、actual/formal 与 return 来源消费、defaults 读点、saved-B/cells 及类后置字段初始化、effects/alias 联合固定点仍未闭合。新增 v5 已接入显式参数/返回引用，独立验收与 LeWM 全量尝试状态见上文；其他欠账继续沿同一 qualified 队列推进，不从 arbitrary computation 的任意输入猜输出别名。这批条件关系不能授权缓存或其他变换。
