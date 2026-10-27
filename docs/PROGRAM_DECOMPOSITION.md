# 层次化静态图及展开规则

本文规定程序如何进入同一 canonical IR、按语言语义展开并连接依赖。
目标是可用于后续化简和声明实现的程序模型；本阶段不执行目标或实施优化。
模型总定义见 [MODEL](MODEL.md)，推导方法见 [静态分析设计](STATIC_ANALYSIS_DESIGN.md)，
实施顺序见 [静态分析计划](STATIC_ANALYSIS_PLAN.md)。下述规则区分现有结构与待贯通分析。

## 1. 同一程序，两个不同的关系维度

包含关系回答“定义在哪里”：程序 → module → scope/body → Region → Block → Operation。
这是源码和接口的组织层次，不规定所有实体都只能属于一棵简单语法树。
依赖关系回答“依赖什么”：Use/Value、CFG、call、state、alias、resource、order。
依赖可以跨越包含层次；`Region.parent` 不能代替调用边、支配关系或 happens-before。

同一函数 body 只定义一次；多个调用点引用该 body，分别映射实参、环境、结果与状态。
有限的分析 context 是摘要索引，不是复制函数、Operation 或 Value 身份的理由。
递归调用、循环回边、共享对象、callback 和任务依赖使程序必然是非树图。
存储分片、共享源码上下文、派生索引和查询视图不得成为第二份事实权威。

静态定义由准确源码版本、namespace、作用域及编译/语言配置限定。
CodeID、CapturedCode、Invocation、设备活动属于不同身份域；文件名和行号不足以合并它们。
静态 body、未执行分支、调用候选和资源需求不依赖先观察到 CapturedCode 或 Invocation。
动态证据只能按明确版本与主体关系附着，不能删去未观察分支或制造静态闭合。

## 2. canonical 实体及职责

| 实体 | 表达什么 | 不得混同什么 |
| --- | --- | --- |
| Operation | 一次静态动作或控制/语言协议步骤，拥有有序 Use、结果和状态接口 | 动态执行次数、源码物理行、实现标签 |
| Value: DATA | 操作结果、形式参数或常量的值定义 | 内存地址、对象引用、一次内容观测 |
| Value: REFERENCE | 对对象、环境或资源的引用及可能目标 | 对象当前内容；同引用不保证内容不变 |
| Value: STATE | 某 StateLocation 的版本及跨边传递 | Tensor 私有计数器、全程序唯一时钟 |
| StateLocation | 状态域及可细化地址，如 binding、field、element、cell、RNG、外部状态 | 每次读写节点、物理 allocation 本身 |
| Region | 可复用主体、入口 blocks、出口及局部控制结构 | 一次 Invocation、天然无副作用的容器 |
| Resource | 执行/存储等资源定义、需求、使用和位置约束 | 实测设备实例、已分配空间、运行完成证明 |

实体沿用 [program/model.py](../scar/ir/program/model.py) 和
[resources.py](../scar/ir/program/resources.py)，不另设 Action 图替代 Operation。
StateLocation 的 SSA 值、逻辑内容版本、对象身份、storage 和物化是相关但独立的实体。
一次未知数值的读仍可有符号结果；该身份不证明另一次读相同、不同或长期稳定。

## 3. 编译器式分阶段建图

各阶段输出带输入版本和依赖的可检查结果；不靠阶段名称宣称整体完成。

| 阶段 | 输入 | 输出与必须保留的边界 |
| --- | --- | --- |
| 入口与源码闭包 | 源码根、namespace/import 策略、源码版本、语言/provider 配置 | 静态 module/body 集合、未解析 import/生成代码义务；不以运行热度决定存在性 |
| 解析与作用域 | 原源码文本、精确语言版本 | AST、符号表、定义/引用/捕获与源码定位；保未执行分支 |
| 接口预声明 | module/function/class 定义与作用域 | body/Region、参数/环境/返回/completion 端口；允许前向和递归引用 |
| 结构 lowering | AST、作用域、版本化语言规则 | canonical Operation/Use/Value、CFG、初始 state SSA、异常与 cleanup 拓扑 |
| 调用与引用求解 | 调用点、引用来源、属性/环境约束 | callee 集合、实参/形参、receiver、closure、返回/逃逸关系 |
| 状态与效果求解 | 调用关系、points-to、地址与协议摘要 | read/write/mod/ref、alias、allocation、ordering、may-raise 等摘要 |
| 联合收敛与细化 | 上述相互依赖结果 | SCC 固定点、精确地址细分和相应 SSA/摘要更新；保未闭合项 |
| 结构与语义核验 | 图、接口、源码映射、推导前提 | 所有权、支配、类型、端口、completion、state/effect 映射一致性 |
| 后续变换输入 | 已核验图与明确合同 | 可化简候选及所需证明；不在建图时偷做 LICM 或删除未知 effects |

源码构造复用 [program_lowering.py](../scar/analysis/program_lowering.py)，
控制 lowering 复用 [structured_lowering.py](../scar/analysis/structured_lowering.py)。
现有 [source_frontend_worklist.py](../scar/analysis/source_frontend_worklist.py)
提供能力选择和逐 body 构造；动态 catalog 选集不能充当纯静态入口闭包。
编译器式分析必须显式遍历静态可达定义与未解析边，不要求先捕获执行帧。

## 4. 每次展开的统一接口

展开不是附加一串 children 标签，而是把原边界与内部实现精确对应。
每个可展开主体保留原 ID、准确源码主体、namespace 和所用语义规则版本。
接口至少表达以下适用项目；不要求为不适用的 completion 捏造端口：

1. 有序输入 Use：位置参数、keyword、独立 receiver、环境及状态；求值序不能重排。
2. 结果与出口载荷：DATA/REFERENCE、返回值、异常及本次传播 traceback 等原 typed 值。
3. normal、raise、return、break/continue、suspend/resume、cancel/close 等适用 completion。
4. 各 completion 的后继、状态输出、pending/cleanup/handled-context 映射。
5. 读写地址、alias/escape、allocation/lifetime、外部与 ordering effects 的摘要及闭合范围。
6. 外层端口到内部参数/结果/状态的映射，及尚未展开的准确源码 slice 或 callee 边界。

静态实参 Use → formal port 表示语言绑定和依赖，不是两次动态值观测相等。
返回摘要必须带适用分支、调用条件和 completion；多个 return 不能任取一个。
DATA 依赖、REFERENCE alias、STATE 读写、CONTROL 条件和 RESOURCE 需求分别标明角色。
跨计算节点可以继续追输入依赖，但不能把所有输入认成输出的同一值。
源码 slice 按准确 AST 主体和有序语句范围表达；不能以 whole-body 边界冒充剩余后缀。
函数定义、函数对象创建、调用与 body 执行分别保留，闭包环境不能按 code 身份合并。

只完成结构映射，不自动授纯性、无异常、正常完成、内容相等或资源 ready。
已有 [CallEffectExpansion](../scar/ir/program/call_effect_expansion.py)
只适用于其严格支持的原 callee 展开；不能拿它冒充多目标分派集合。
地址细化复用 [StateAddressRefinement](../scar/ir/program/state_addresses.py)，
仍挂在原 state access/Use 上，不平行建立一份读写图。

未知应附着在准确属性或关系：目标集合未闭合、某地址未知、效果上界未闭合等。
保留已知 operand、CFG、结果、状态和源码范围，不能因一个未知属性抹掉整个节点。
确无实现信息时保留类型正确的未展开边界及展开义务；OPAQUE 不是完整性证明。
已知失败、已知写入或已知 alias 不能降成笼统 UNKNOWN 来掩盖矛盾。

## 5. 具体构造的展开规则

| 构造 | 必须保留的内部步骤和连接 | 不能作的假定 |
| --- | --- | --- |
| 普通调用 | callee/实参按语言顺序求值 → 绑定 → callee Region → 各 completion 的结果/状态映射 | 文件名/函数名就能决定唯一目标或纯性 |
| bound method | descriptor/绑定协议 → 独立 receiver → 显式参数 → 原 function body/环境 | receiver 就是普通 arg0；按参数名猜 self |
| `*` / `**` | iterable/mapping 协议、展开顺序、重复 keyword 与非字符串 key 错误、最终绑定 | call 的 DICT_MERGE 等于 display 的覆盖式 DICT_UPDATE |
| 分支/短路 | 条件求值、truth 协议、各分支 CFG、merge block arguments/state | 未执行路径不存在；两个分支结果天然相等 |
| 循环 | header/body/latch/exit、回边、loop-carried Value/state、break/continue/else | 每次迭代复制 body；不变语法就是 loop invariant |
| 递归/互递归 | 共用 body、递归调用边、SCC 的参数/返回/effect 摘要 | 必须无限内联才能建图；有限展开即完整 |
| callback/高阶函数 | callable reference 的传递/保存/逃逸、候选目标、注册与可能调用接口 | 词法包含就是调用；注册就是已执行 |
| try/except/finally/with | 本次传播 exception/traceback、匹配/绑定、正常/异常 cleanup、pending 替换与继续 | exception.__traceback__ 必为本次传播；绑定失败也应清理未绑定名称 |
| closure/function 创建 | defaults/decorators 的定义时求值、code/body 引用、G/B 与 cell 捕获、调用时读 cell | 捕获 cell 等于提前读取内容；所有函数共享实际环境对象 |
| import/module | module mapping frame、L/G/saved-B lookup、import 协议、alias/store 与残余语句 | exec-mode code 证明 ModuleObject/sys.modules 成员；正常 STORE 证明 custom mapping 已存值 |
| class | class body 的 mapping frame、namespace、bases/metaclass、decorators、类对象构造；实例化另建调用接口 | class body 是函数实例化；class/instance 共用 function ABI |
| 属性/下标/运算符 | receiver/key 求值、descriptor/MRO/特殊方法分派、读取/运算/写回与各失败出口 | getattr/getitem/加法是纯计算；所有输入都与结果 alias |
| AugAssign | owner/key 一次求值 → 读 LHS → RHS → in-place 协议 → 原目标 storeback | 等同纯 add；操作失败前无内容变化；storeback 不会失败 |
| Tensor view | 版本化 provider 的视图/alias 协议、geometry、读写可达状态和共享存储约束 | 共享 storage 就是同逻辑值；未解析的 reshape/布局操作必为 view |
| Tensor copy/clone | 输入 read 版本 → 条件内容来源 → 输出/新物化及 completion/order | schema may-read 就是必然的完整内容复制；同 dtype/shape 或 _version 证明内容相同 |
| IO | 操作对象/内容参数、程序可见资源需求、读写/外部/order 效果和失败出口 | FD/path/inode 是永久内容身份；为建图必须展开 OS FD 表 |
| generator/async | eager 创建输入、lazy body 与 closure、驱动/yield/await/resume/close/cancel 接口 | 创建同步执行 body；await 返回即所有外部工作 ready |

这些规则依赖 Python/CPython 或 provider 的准确版本化语义，不依赖业务名称。
同一 AST 构造可以展开成多个 Operation；一个 Operation 可实现多个数据/状态关系。
特殊方法、custom mapping、import hook、subclass 分派无法闭合时扩大候选/效果上界。
不以默认 builtin 行为替换可能存在的用户实现，也不为常见 workload 写例外。

## 6. 循环、递归、callback 的联合推导

先预声明主体，再建局部图和未解析调用，避免“必须先有 callee 完整图”的循环前提。
callgraph、points-to、返回引用、escape 和 mod/ref 彼此依赖，必须用工作队列联合推进。

1. 用直接定义、常量、参数、环境与已知协议初始化引用/目标约束。
2. 沿赋值、block arguments、容器/字段及调用绑定传播抽象引用与可能别名。
3. 新 callee 加入调用图；把实参/receiver/cells 接到原 formal，返回接原 completion。
4. 按调用图 SCC 联合求返回、读写、逃逸、异常与资源需求摘要，变化重新入队。
5. alias/目标集合变化时重算受影响地址与 effects；必要时更新状态分区及 SSA 映射。
6. 稳定后核验所有边界；未解析目标和外部行为继续保守，不当空集处理。

抽象域必须有明确偏序、join、有限界或 widening；分析 context 和预算截断显式记录。
同一个固定点内约束单调累积；后续精化需重新求受影响结果，不能悄悄删旧可能行为。
loop header 的归并和回边处理来自 CFG；递归深度不靠展开次数猜测。
callback 的调用次数/顺序未知，不妨碍表达可能调用和 effects，也不授某次 runtime occurrence。

每项派生结果依赖准确 source/namespace/provider 版本、CFG、callee/alias/effect 摘要。
这些输入变化，失效沿依赖边传播到相关 SCC 和消费者；索引可删后重建。
不得复用可变图的旧验证布尔值，或将保存的 PASS 当新输入的证明。

公开输入在进入分析时按正常 codec 和图约束核验。
一次分析私有拥有的不可变输入可共享解析与索引，不能每个 body 重建同一源码上下文。
共享不能绕过逐 body 的端口、源码、状态和控制映射检查，也不能外泄可变上下文。
预算耗尽时返回已处理范围与未解决关系；不能把尚未遍历的目标当不存在。

## 7. 跨层连接与展开终点

源码构造 → canonical 操作/Region → provider 实现/声明 → 资源需求，是可细化的路径。
每层通过原 qualified 主体、ports、completion、state/effect 映射连接，不按标签或时间拼接。
跨 fragment 使用准确 namespace、artifact/version 与原 ID；不重命名或合并原节点。

原生边界只能依据准确版本的实现源码、声明或显式协议继续静态展开。
只有声明时仍建立 ordered inputs/outputs、world 与未知效果，不伪造实现内部或执行完成。
源码存在也不自动证明它就是实际加载实现；loaded-code/动态 occurrence 对应另行建立。
GPU kernel 是否运行、哪次 allocation、异步 ready、真实资源竞争都不是静态展开的结论。
程序可调整动作及其依赖是主图范围；不默认扩到机器指令、硬件流水线或 OS 内部表。

资源位置与物化可有多个候选；logical version、view、storage、allocation 分别保原身份。
copy 的内容来源需输入读版本及无干扰/语义条件；输出存储归属不能代替该数据边。
静态 order 只表达语言和协议保证，不等于记录序、墙钟接近或跨线程 happens-before。
对于 async/设备工作，提交、执行、完成、可读分别保留，不能折成一个“调用已返回”。

## 8. 现有复用点与必须补齐的连接

- ProgramGraph、ordered Use、state SSA、callee/completion 和 Resource 接口构成唯一骨架。
- StructuredBuilder、loop、pending/cleanup、resumption 继续实现精确语言展开，避免重写一套解释器。
- [validation.py](../scar/ir/program/validation.py) 的支配、可用值和接口核验是阶段检查；不是分析求解器。
- [environments.py](../scar/ir/program/environments.py) 与
  [resumption.py](../scar/ir/program/resumption.py) 分别复用环境和延迟执行接口。
- [source_subjects.py](../scar/ir/program/source_subjects.py) 将使用 CapturedCode 的 FrameRoot 与使用纯编译来源的 SourceCompilationFrameRoot 分开；模块已接通静态前缀和 BODY profile，类已有独立 ClassFrameABI，但 class suite 仍是带原语句的 required expansion；
  静态定义和模块编译来源不再依赖动态 descriptor，其余入口也必须遵守这一边界。
- 静态 frame 需准确静态 code/source 主体；function/module/class ABI 分开，再另接 loaded-code 关系。
- [constants_v2.py](../scar/analysis/constants_v2.py) 的有限常量推导可复用；不等于 CFG 执行边上的通用 SCCP。
- [effects_v2.py](../scar/analysis/effects_v2.py) 能组合显式摘要；尚不能替代目标发现和 points-to/mod-ref 联合求解。
- 必须贯通纯静态入口、跨过程约束、SCC 固定点与失效；不能以已有 schema 或单 body 成功代替。

## 9. 完整性与下一步边界

结构完整：声明范围内每个语句/表达式、分支、body 和边界都有准确主体与接口。
连接完整：值、引用、状态、控制、调用和资源依赖没有靠名称/观测缺失补成的虚假边。
语义闭合：每项需要的目标/alias/effect/completion 摘要在其前提下闭合；未知项逐项可查。
三者分别判断；未知不阻止建已知结构，但对应未解义务不能算完成。

下一步先完成纯静态入口到联合固定点的可运行闭环，并使未执行路径同样参与分析。
然后才依据完整依赖和合同决定常量传播、外提、复用、删除等变换的合法性。
本设计不要求重建完整 Python 编译器、逐 primitive 重证所有引用生命周期或先采全量动态日志。
它要求复用精确语言协议、保留真实实体关系，并明确每一条尚未解决的静态依赖。
