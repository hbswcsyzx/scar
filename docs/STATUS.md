# 当前状态

唯一任务：整程序纯静态分析与建图。唯一工作目录 `~/AAA/scar`、分支 `main`。

## 已实现并用于真实源码

- 纯源根入口 `scar static`：全文件扫描、编码与 raw/decoded SHA、命名空间候选、预算剩余范围；不要求 CapturedCode/CodeWitness。
- 全 AST occurrence、模块/函数/类/lambda/comprehension/注解和类型上下文目录；完整 symtable 及 compiler scope 关系。未知关联保留候选，不伪造真实代码帧。
- 四进程按源码文件构建已有 semantic、source-semantics、CFG 及有限常量事实；所有路径和未执行定义参与。
- 跨文件 import 候选保留原 source reference、alias 序号、控制上下文、模块初始化引用；导出/子模块、stub 与实际源码分别记录。
- 分片当前输出和 `scar static-query`，可查询定义、符号、原操作数、值/绑定及控制图；无第二套 producer/state 图。
- 可在不重建原源码图的情况下细化词法 scope 和 import 索引。

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
| 原图分片字节回读 | 3,488 片 stored/decoded SHA、JSON 容器通过 |
| 普通 typed reader | eval.py 的 SG、source-semantics、CFG 解码与交叉结构校验通过 |
| 公开查询 | eval.img_transform 与 solver/cem.py.solve 的原操作/控制记录读回通过 |

当前输出见 `artifacts/current/static/manifest.json`；大图不提交 Git，仅保留这一版 current。
细化另外保留 compiler scope 15,471 项的实际分类，以 manifest.catalog_refinement 为准确值，不把 scope 当运行 thunk。

## 仍未完成

**完整静态模型尚未完成。** 原源码图有 69,298 个 opaque 操作、450,176 项语义缺口、16,061 项控制缺口；它们是待分析结构/规则，不能算已完全展开。
12,550 个入口尚未全量 canonical lowering。已有 7,055 项普通函数可进入现有 source-only adapter 尝试，其余入口/阶段仍缺静态连接；“可尝试”不证明其内部构造都支持。
S1 的精确语言规则/前提台账、S2 的完整规范子图、S3 调用/别名/效果联合固定点、S4 统一属性约束及 S5 完整导出尚未闭合。
第三方源码/声明、动态目标表达式与别名/副作用仍有可继续静态推导的部分，不把这些缺口统称为“只能动态获取”。

## 下一项

按 [唯一计划](STATIC_ANALYSIS_PLAN.md) 补齐静态 entry/语言规则台账，沿原目录驱动 canonical body 展开，解决静态主体仍受运行见证限制的接口，再推进跨层实际/形式端口和联合固定点。
本轮没有导入或执行 LeWM，没有运行目标样例、trace、benchmark、优化或动态验证。仅运行分析器、解析源材料与读取/校验生成的静态图。

## 当前离线检查

582 项源目录重复扫描身份稳定，保留源码指纹与原文件一致。将文件预算设为 2 时，准确保留剩余 580 项，没有从分母删除。
458 个 SCAR 源文件语法解析通过，文档本地链接无缺失，LeWM Git 工作树仍干净。生成的 import 索引 receipts 通过，索引构造问题为 0；外部源码、导出和 namespace 候选仍是明确 frontier，未据此声称 import 已全部解析。
规范 body 路径已对现有 source_motion 源码作一次纯静态构造：函数生成规范图，模块入口明确 UNEXPANDED；该源码没有被导入或执行。未将此局部结果提升为全 LeWM 主体覆盖。

## 规范主体静态展开

已增加独立 `SOURCE_COMPILATION` 证据：按固定源码与 compiler profile 仅 compile、不 exec；准确匹配定义位置/词法 qualname/父级常量路径/装饰器首行，不创建假的捕获见证。
已有 call-expansion、try/with、nested function、lambda/comprehension、constant 等 lowerer/validator 共用编译布局接口，动态旧证据保留原含义；模块 frame 的原 CapturedCode 接口仍待解耦。

增量 `--expand` 按文件复用原4源片、一个sealed lowering session和一份静态编译布局；规则明细单独保存在原unit的rules分片，body容器只引用共享源片。已知失败/未派工入口保留，缓存键包含源输入、规则、编译条件与相关producer，不是运行时memoization。

真实 `eval.py:img_transform` 的首次纯静态规范构造通过：3.41秒、92操作、157值、1 Region，normal codec读回通过；32项原effects/dispatch等缺口保留。公开query可同时投影canonical端口、Value→source、原控制图和具体规则/shape缺口，分别标明哪些只是结构校验。这里没有执行该函数。
详细台账和全7,055个普通函数的规范构造正在按同一目录推进；当前单例成功不代表全量完成。
