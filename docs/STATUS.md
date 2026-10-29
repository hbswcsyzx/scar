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
- 类使用独立 ClassFrameABI 和 core 31：prepared namespace、外部 closure 与内部 compiler cells 分开。新 ClassSuite 已建立真实 namespace/cell/factory/state 操作。全部 1,183 个类已正式构造：1,118 个无 suite continuation、65 个保留精确 continuation；父级构造与 effects 等仍开放。

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
| 当前已发布有规范图的入口 | 7,762：581 个模块、1,183 个类 suite、5,998 个普通函数；均保留缺口 |
| 当前已发布明确不支持 | 547 个 lowerer 不支持，510 个规则 shape 不支持 |
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
当前有图分母仍为 7,762。全 1,183 类的 suite 构造已四进程完成并发布，473.28 秒（1,176 重新构造、7 复用）。1,118 个无剩余 suite 后缀；65 个明确局部 continuation，其中 42 个 method-lookup 双结果 ABI、23 个 class control/compiler protocol。类操作合计 98,992，全规范操作 1,034,767，构造 ERROR 为 0。数字不变但原来的整类 3-op 边界已被实际结构替换；没有把后缀、effects 或父级构造欠账算成完成。调用索引已按最新主体重建。
静态 compiler layout 记录 names/flags/参数计数/local/cell/free 表，原索引与空名称均保留；不保存 Tensor 值或地址。body 失败时仍保存已有编译事实，公开 query 将其标为 SOURCE_COMPILATION_FACTS，而非运行观察。

## 仍未完成

**完整静态模型尚未完成。** 原源码图有 69,298 个 opaque 操作、450,176 项语义缺口、16,061 项控制缺口；它们是待分析结构/规则，不能算已完全展开。
12,550 个入口尚未全部完成 canonical lowering。普通函数已全量尝试；模块可构造受支持前缀和明确要求继续展开的后缀，不能把前缀图算成完整模块；类入口已有实际 suite；65 项续接协议、父级 class construction、resumable 和隐式类型/注解主体等仍待展开。
S1 的目录与逐入口规则台账已存在，语言语义完整性仍未闭合；S2 的完整规范子图、S3 调用/别名/效果联合固定点、S4 统一属性约束及 S5 完整导出尚未完成。
第三方源码/声明、动态目标表达式与别名/副作用仍有可继续静态推导的部分，不把这些缺口统称为“只能动态获取”。

### 缺口复审：为什么不能宣称静态分析已经完成

当前 manifest 的 `LOWERED_WITH_GAPS` 由“是否生成规范图”决定，**不是逐主体穷尽推理后的结论**。同样，0 个构造 ERROR 只说明分析器没有报告构造异常。二者都不能用作完整性证明。

- **实现欠账**：547 个 lowerer 不支持项、510 个规则 shape 不支持项。仅 combined slice 86 项、slice store 70 项、nested with cleanup 60 项就有明确源码和编译语义，缺的是 SCAR 的展开规则，不能归因于必须动态捕获。
- **入口与内联展开尚未核齐**：3,731 个目录项没有独立入口适配，其中 2,482 个 annotation context、961 个 comprehension/generator expression、235 个 lambda、52 个函数、1 个 stub 模块。部分表达式已经在父图内展开，因此不能把该数字直接解释成同等数量完全缺失的运行帧；仍须逐项核对其实际归属和缺失结构。
- **跨过程推理未完成**：当前只处理 8,819 份主体产物中的 80 份；已发布 493 个 CALL。目标闭包、返回、defaults/closure/global 环境、别名与 effects 联合固定点尚未贯通。不能将尚未推导的调用关系直接称为语言本身不可知。
- **材料范围不足**：当前包含 LeWM 源树和两个本地依赖项目，没有环境中全部第三方实现的源码闭包。源码缺失与已有源码但未分析必须分别报告。
- **静态边界与结构缺失混列**：例如 module 的常量槽/函数创建结构已经连接，但运行时 code 对象身份仍开放；该身份不应成为“缺少函数体结构”的依据。现有原始 gap 总数还混有这种证明前沿，不能用它衡量结构缺失率。类的前沿还被投影为统一 EFFECT_SUMMARY，查询时须结合原 class frontier 才能知道具体欠账。

上述分类是本次读取 current manifest 和实际 lowerer/linker 的审计结论，不是宣称已实现了新的自动缺口分类器。后续应分别闭合结构、跨过程关系和字段事实；未知地址等运行字段允许保持符号化，已有源码中尚未实现的规则继续作为实现欠账。

更关键的未闭环部分是 S2 产生的操作/Use/状态端点尚未充分进入 S3/S4：namespace flow 仍附带 mapping 提交、读取返回绑定及中间 effects 保持等条件，linker 对每个 CALL 都保留 TARGET_SET_CLOSURE_OPEN。缺少把源码上下文、类型/对象来源、返回和状态摘要反复传播以消解这些条件的过程。即使继续补齐局部语法，也不会自动获得全程序依赖图；受支持子集的联合推理应与语言欠账的修复衔接推进，而非等待所有语法实现后才开始。

已查到并修复一个真实消费断口：函数 lowerer 发出 `LOOKUP_GLOBAL`，namespace 分析原来只接收 `LOAD_GLOBAL` 等协议，跳过了已有 G/saved-B/key/world 端点。修复后，从 current 中现有 `eval.img_transform`、`eval.run` 的规范图重新解码并建立 namespace 索引，分别接回 7、32 个函数 global read，原正常结果与两个 namespace owner 均保持；耗时约 0.50、21.64 秒。仅运行静态图 reader/分析器，没有执行函数；此检查没有重发 current 的调用索引，也没有证明跨主体 G 投影或任何缓存合法性。

## 下一项

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 接通父级 class construction、65 项 class continuation；补齐 resumable/隐式入口及已分类的 slice/with 等语言缺口，在已有条件 namespace/调用关系上推进返回、环境、别名和 effects 联合固定点，再接统一类型/Tensor 属性。
本轮没有导入或执行 LeWM，没有运行目标样例、trace、benchmark、优化或动态验证。仅运行分析器、解析源材料与读取/校验生成的静态图。

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
真实 eval.run 和 eval_ff.run 分别构造 2,305、2,080 个操作。三个融合 store 的 comprehension 所属函数在修复后离线构造及 source/compiler/core 读回通过（317、108、437 个操作），已在全批正式发布。eval_wm.run 已通过该 comprehension，后续动态 bound 的 BINARY_SLICE 规则仍未实现，准确保留其源码缺口。
Costable 与 ConditionalBlock 两个真实类入口均以原 SG DefinitionID 构造并公开查询 core 31；normal payload 分别为 Python None 引用、class cell 引用。新 suite 分别有 74、63 个实际操作并无 suite 后缀，cells、closures、code reads、factories 和 namespace 读写都有原端点；生成 child body 与父级 metaclass/namespace 供给仍未闭合。
另以真实 CEM 模块检查 docstring 的 __doc__ 写入：192 个操作、11 条语句前缀，仍保留一条 class 后缀；source wrapper 读回和独立静态编译通过。没有执行模块初始化或函数体。

## 跨主体静态关系

`--link-calls` 已在当前图上发布 v2 派生关系。读取 80 份主体（77 份有图），118.80 秒；当前发布 493 个 CALL、20 条条件目标、19 条 namespace flow、9 条函数创建关联、37 条实参边、52 条 completion。枚举了 494 个 CALL，最后一项未发布，不能算已保存。仍有 8,739 份主体产物未处理；源码目录总共 47,135 个 AST 调用点，不能把本批视为整程序调用闭包。
关系引用原 owner/key/payload Uses、读结果、world、CFG 与 factory/code slot；按明确 mapping/path/effect 条件成立，不是内容恒等或无副作用证明。三个独立纯静态 case 通过：正常覆盖、分支保留多候选、装饰器结果截断；临时材料已删除，没有执行这些程序。
真实 eval 模块的 run() 已接通一条 STORE→LOAD 条件流，并准确停在 APPLY 结果，保留 DECORATOR_RETURN_RELATION_OPEN；没有伪造原 run body 候选。public query 复核原 receipts、端点和 CFG，并与普通 compiler-prologue core join 分开标记；没有声称查询重放源码或运行目标。
目标集合、defaults/G/saved-B/cells 投影、effects/alias 固定点仍未闭合；这批关系不能授权缓存或其他变换。
