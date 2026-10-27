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
- 类使用独立 ClassFrameABI 和 core 31：prepared namespace、外部 closure 与内部 compiler cells 分开；suite 仍保留 required expansion，不能算完整类体。

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
| 当前已发布有规范图的入口 | 5,998，均保留原 effects/dispatch 等缺口 |
| 当前已发布明确不支持 | 550 个 lowerer 不支持，510 个规则 shape 不支持 |
| 当前已发布入口适配缺失 / 未派工 | 5,395 / 97；构造 ERROR 为 0 |
| 原 85 个构造错误复验 | 全部生成带缺口的图；另构造 eval 模块，共 86 个，113.63 秒 |
| 原图分片字节回读 | 3,488 片 stored/decoded SHA、JSON 容器通过 |
| 普通 typed reader | eval.py 的 SG、source-semantics、CFG 解码与交叉结构校验通过 |
| 公开查询 | eval.img_transform 与 solver/cem.py.solve 的原操作/控制记录读回通过 |

当前输出见 `artifacts/current/static/manifest.json`；大图不提交 Git，仅保留这一版 current。
细化另外保留 compiler scope 15,471 项的实际分类，以 manifest.catalog_refinement 为准确值，不把 scope 当运行 thunk。
本轮完整目录细化耗时 462.24 秒，保留 2,906 份原图片、不重建源码图；581 个模块、1,183 个类及 7,055 个普通函数共 8,819 个入口可进入构造尝试，3,731 个其他入口仍缺适配。可尝试不等于已建模。
当前正在四进程构造全部 581 个模块、1,183 个类及三个已修复的 comprehension 所属函数，共 1,767 个入口；本段表格是该批发布前的最后已保存结果，终态以原 manifest 为准。

## 仍未完成

**完整静态模型尚未完成。** 原源码图有 69,298 个 opaque 操作、450,176 项语义缺口、16,061 项控制缺口；它们是待分析结构/规则，不能算已完全展开。
12,550 个入口尚未全部完成 canonical lowering。普通函数已全量尝试；模块可构造受支持前缀和明确要求继续展开的后缀，不能把前缀图算成完整模块；类入口已有 ABI，但完整 suite、resumable 和隐式类型/注解主体等仍待展开。
S1 的目录与逐入口规则台账已存在，语言语义完整性仍未闭合；S2 的完整规范子图、S3 调用/别名/效果联合固定点、S4 统一属性约束及 S5 完整导出尚未完成。
第三方源码/声明、动态目标表达式与别名/副作用仍有可继续静态推导的部分，不把这些缺口统称为“只能动态获取”。

## 下一项

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 补齐具体语言规则、模块剩余语句及其他静态入口；把原 caller Use、callee formal、完成/返回端口连成限定命名空间的关系，再推进跨过程联合固定点。
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
真实 eval.run 和 eval_ff.run 分别构造 2,305、2,080 个操作。三个融合 store 的 comprehension 所属函数在修复后离线构造及 source/compiler/core 读回通过（317、108、437 个操作），尚待当前批次正式发布。eval_wm.run 已通过该 comprehension，后续动态 bound 的 BINARY_SLICE 规则仍未实现，准确保留其源码缺口。
Costable 与 ConditionalBlock 两个真实类入口均以原 SG DefinitionID 构造并公开查询 core 31；normal payload 分别为 Python None 引用、class cell 引用。required suite 只有三个边界操作，不能据此声称完整类体已展开。源码的 class header、suite 语句和 compiler cell 阶段保留，但父级 metaclass/namespace 供给仍未连接。
另以真实 CEM 模块检查 docstring 的 __doc__ 写入：192 个操作、11 条语句前缀，仍保留一条 class 后缀；source wrapper 读回和独立静态编译通过。没有执行模块初始化或函数体。

## 跨主体静态关系

`--link-calls` 已实现限定原端点的派生关系与 `static-query --dependencies` 查询。更新主体或目录会废弃旧调用索引，当前正在构造的批次不能沿用旧索引；批量发布后再重建。源码目录登记 47,135 个 AST 调用点，不能用有界 canonical CALL 数代替源码总分母。
已核对 namespace/module mappings、固定 basis、当前 caller/callee 分片 receipts 与 core root，查询同时返回实际 owning Region 和原枚举状态。6 个原 SG 标记 opaque、但规范图已展开的调用，经原 AST/源码锚点/callee Use 核对后作为明确细化保留，不因缺少较粗计算 overlay 拒掉整份主体。
mapping caller 已从原 MappingFramePorts / ClassFrameABI 取得 world，参与相同条件 target/actual/completion 分析，不再仅因 caller 类型退出。真实 eval 模块两处 CALL 目前仍无合格目标：缺少 namespace 写入/读取到函数值的条件关系；run 函数的定向只读枚举有 60 个 CALL、4 条候选边、6 条实参边及 8 条 completion。此结果不是全项目调用闭包，也不能把 decorators/custom mapping 的结果按名称绑定到原函数。
当前关系尚未证明目标集合闭合、函数环境/defaults/cells 投影或 effects/alias 固定点。这是原图之间的条件依赖连接，不能据此授权缓存或其他变换。
