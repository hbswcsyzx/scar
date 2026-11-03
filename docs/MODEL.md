# 程序模型

当前目标是整程序纯静态建模。分析器可以运行；被分析程序及其初始化、用户回调、自定义序列化代码不能执行。模型、图和推导事实不依赖 trace 或实际调用记录。

## 实体与角色

| 实体 | 含义 | 对应程序部分 |
|---|---|---|
| Operation | 有明确规则、操作数、结果及效果的操作 | 调用、绑定、计算、状态读写、分配、物化、IO、等待 |
| Value | 某次静态定义或区域参数产生的值 | 数据、对象引用、状态版本；既有局部绑定/控制令牌保持独立类型 |
| StateLocation | 可读写的位置或抽象状态域 | 对象字段、容器元素、Tensor 内容、module/closure/RNG/文件状态 |
| Region | 有入口、出口和内部结构的程序子图 | 模块、类体、函数体、分支、循环、异常处理、可展开复合操作 |
| Resource | 承载状态或执行操作的资源定义及要求 | CPU/GPU、DRAM/HBM、文件、SSD/NVMe、stream、线程角色 |

输入/输出是端口角色；常量、不变量是有范围的性质；shape/dtype 是属性，不是互斥节点类型。
K/Σ/A/R/Q/M 是正交视角。当前 M 不收集实际测量，Q 保留语言、目标环境和观察边界的明确前提。

## 连接

- 包含关系：模块/定义/Region 的层次归属。它组织代码，不代表值来源。
- 数据关系：结果或参数经有序 Use 连接到消费者；`f(x,x)` 保留两个端口。
- 绑定关系：名称/槽位的定义、读取、实参到形参、返回值到调用结果。
- 控制关系：可能执行的分支、循环回边、调用及正常/异常/挂起等适用出口。
- 状态关系：指定位置和范围的 read/write、前后版本、合流及必要顺序。
- 身份/存储关系：引用指向、must/may alias、view、offset、生命周期与逃逸。
- 资源关系：操作所需的执行/存储资源、潜在搬运及静态顺序约束。
- 对应关系：版本化源码/语言规则/库契约到原 Operation、Value 和 Use。

每条关系应区分必然与可能、路径条件和依据；没有边不能自行解释成没有依赖。

条件本身也是有类型的谓词项：`P(domain, name, subject, operands, ordinal)`。
subject 与有序 operands 都引用原 qualified 端点，ordinal 只表示原有序位置，不编码或
哈希对象 ID。二元关系不能退化为一个无参数的名字：相同 entry 来自不同 factory 的
条件必须有不同身份；不同创建/入口上下文也须分别保留。证据说明为什么有该关系，
不替代谓词参数或参与真值键。只懂一元签名的规则遇额外 operands 必须保持 open。

共同查询导出使用端点引用表保存 operands。当前 dependency walk / value analysis /
region boundary 的导出版本分别为 3 / 4 / 3，context 还显式保存 `unknown_prefix`。
旧报告按原版本解释，不能忽略新版字段来消解条件。原 canonical/source/calls 分片
版本和当前主图不因查询表示升级而改写。

原 SG 已有精确表达式定义和输入/输出，而旧计算 overlay 缺少记录时，应继续由原 AST、作用域、读写角色和原端口展开 canonical IR。不能伪造旧 overlay record，也不能将已知常量或算术结构整块变成 UNKNOWN。具体算术/比较运算符属于操作契约或 DATA 配置，不应伪装成程序另外创建的 Python 字符串对象；自定义比较的结果仍可能是对象，不能预设为 bool。

复合表达式 helper 交出结果引用时，转交既有所有权与释放引用是不同操作：转交不执行 decref、不分配新对象，不应使同一引用在父子两层被重复持有或清理。操作消费输入、异常出口的已消费部分及外层待清理引用须沿原端口组合，不能以“看起来是同一个值”去重引用或放宽清理顺序。

import 返回的 module 引用、module namespace 和初始化状态分别建模；对象不是其 dict，源码 initializer 定义也不是一次已经发生的初始化。module 属性、decorator 隐式调用和 defaults 字段/元素应连接各自原操作、Use、状态与读取位置，不能靠名称跳过中间关系。

属性访问使用原 receiver Use、字段选择器、world、正常结果或赋值 Use 表示；属性名是协议配置，不要求程序另外创建一个字符串对象。原 AST/SG 已能确定字段时，即使旧 core 没有精细地址声明，也可保留这部分已知接口；已有地址声明必须与原接口一致。引用绑定令牌可出现在来源路径中，但不因此成为 Python 对象引用。跨层 module 属性来源由真实 import 结果、所选源模块正常出口的 reaching binding，以及 consumer 的原控制路径组合；属性覆盖同时记录写入端口和 receiver 来源。所有这些关系附带加载、lookup、写入提交、上下文及效果保持条件，不是缓存许可。没有 CALL 的属性读取同样保存关系。

`IMPORT_FROM` 也是原 Operation，不转换成虚构的 Attribute AST。`StaticImportFromRequest`
记录原 name/level/fromlist Use 和 fromlist 的 `CodeConstantSource`；`StaticImportFromRead`
记录原 receiver/key/world、成员序号及 normal result。两者只是描述原端口的强类型关系，
不新增执行节点。依赖路径复用同一 module flow 表，以 read 联合类型区分协议。
[Python 导入契约](https://docs.python.org/3.14/library/functions.html#import__)
区分 plain import 的顶层返回与非空 fromlist 的完整模块返回；实现还须从保存源码独立
编译，核对原 CodeRef、常量槽和成员 CFG 顺序。读取命名空间绑定只是其中一条条件路径，
不证明 hook/cache、动态属性或 submodule fallback 已被排除。新版关系 wire 为 v9，旧
v8 的 plain-import 解释保持，旧记录不能夹带新请求、读取或条件。相对 package 上下文
及尚未适配的作用域必须明确列出，不能从同名文件猜导入身份。

类声明与共享类体分开。父级构造保存装饰器求值、builtins 中的 builder 查找、类体 code/factory/closure、name/bases/keywords、builder INVOKE、逆序装饰器 application 和当前 frame 的绑定写入。隐式调用有自己的真实输入/normal/raise/world 端口，不伪造 AST Call 或 CallID。共享 suite 的编译来源引用只证明对应哪份代码；prepared namespace 必须由 prepare 调用或明确的 mapping allocation 产生，不能从一个派生关系中凭空创建。suite 的 cell/None 正常 payload 不等于最终类对象。

## 跨分片共同依赖接口

`scar.ir.program.dependencies` 的端点由原 artifact namespace、原 typed ID 和静态接口栈组成。
跨层只是边跨过 namespace/接口，不是创建一份 callee 或运行实例。关系保留原条件、依据和
EXACT/MAY；EXACT 表示在所列条件下关系准确，不表示条件已被证明成立。

上下文是静态接口选择，分三种知识状态：

| 表示 | 含义 |
|---|---|
| `None` | 没有已选的接口栈；外层未知 |
| 闭合 tuple，包括 `()` | 已选的完整接口栈；空栈表示未选 caller |
| `OpenDependencyContext(suffix)` | 任意兼容的未知前缀＋已核的非空接口后缀 |

开放前缀可能为空，但不能被认定为空。Open 与同 frames 的闭合 tuple 不相等；类不提供
普通迭代/切片，统一通过 context helpers 处理。push 保留开放性；精确 pop 弹尽已知后缀
得到 `None`，匹配失败另有显式标记，不能从未知前缀猜补帧。Frame 全来自原调用/实现接口，
不创造 Invocation。一个上下文族也不表示同一个动态对象或数据版本。

Local/Class 可沿已核后缀追踪；旧 call publication 的闭合 state witness 不能因后缀
相同就适用于 Open。值字段仍保留已知 literal/type/绑定状态，当前证明规则对未闭合入口、
guard 和完整来源族保持具体前沿，不把整个节点的其它字段抹成 UNKNOWN。

`ProgramDependencyGraph` 提供共同的邻接、遍历和 cut；`ProgramDependencySession` 共享有界
只读原图与关系缓存。调用、class、环境、状态和局部图由 provider 适配到同一端点类型，
分析只沿适用关系转移事实：一般 OPERAND/STATE_INTERFACE 依赖不等于值/对象身份相同。
绑定 token、其 payload、scalar 内容和引用定义来源是不同字段。

完全声明的本地同步调用可按原 result slot、normal terminal 集合与精确上下文闭合值传递；
只找到候选 completion 不足以闭合其它正常路径。未知字段必须在工作队列中继续传播，
例如 `未知 int ∪ 7` 的内容不能变成确定的 7，而类型可仍为 int。

已实现的值分析目前只覆盖有限 scalar/type/定义来源规则；区域边界只列接口与知识状态，
不证明效果闭合。字段未知、未实现、缺材料、未发布关系和预算分别保留。相关入口和覆盖见
[程序分解 §3.4](PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

## 身份和版本

源码身份包含源码指纹、命名空间/编译上下文及定义位置，不能只用函数名或行号。
静态定义不要求真实 InvocationID，也不能伪造 CapturedCode 来创建定义。
静态编译的 CodeType 是分析器产生的编译产物，不是观察到的运行对象。其布局 key/常量路径必须通过独立 SOURCE_COMPILATION 来源绑定编译器 profile、源码和原定义；只能支撑编译语义，不支撑实际加载身份。
编译器的参数计数、flags、local/name/cell/free 表是可保存的静态事实。表项按编译器索引保留，不能按名称集合去重或合并；相对导入的 name 表可以有空字符串。compiler-owned cell、入口 closure cell、namespace 中同名绑定是不同角色，不能仅凭拼写相同建立别名。
没有直接 AST 语句的编译器前导用原编译来源、常量路径和 offset 描述，不伪造源码行或函数定义。它通过独立 Region 的正常/异常 world 端口接到原模块主体之前。已知 cell allocation、code read、factory、namespace set/store/setup 现在有各自的操作和 world；owned cell handles 通过 normal ports 返回父 frame，继续传给后缀，并保留到 frame exit。deferred child 等尚未展开部分仍明确标记，不算完整建模。

DATA、REFERENCE、STATE 分开：局部引用绑定未变，不代表其对象内容未变。
State SSA 表达静态读写依赖；循环/分支版本是符号版本，不是运行观察到的时间戳。

逻辑来源、对象、存储、表示/物化不合并。分配站点加符号调用/迭代上下文表示潜在对象；同一站点的不同实例不自动相同。view 可共享存储而有不同几何范围。
物理地址不是逻辑值身份。确切地址未知时仍可推导符号基址、偏移、别名和范围。
复制保留什么、变换产生什么，由具体操作规则决定；相同内容不证明对象相同。

## 函数创建与调用环境

函数的源码定义、创建操作产生的函数引用、调用者当前使用的 callable 引用，以及共享函数体的环境端口分别建模。重复执行同一个 factory 可能产生多个实例，不能因 code 相同合并其默认值或闭包状态。

跨主体关系引用原 body namespace、factory 正常出口、原输入 Use/Value、call 的 callee Use/world，以及 callee 已存在的 EnvironmentInterface member。关系本身不创建新的调用、对象、Value 或状态位置。

- `REFERENCE_BINDING` 表示在明确的目标/创建来源条件下，函数对象或 globals 等引用如何进入被调用环境；它不证明 namespace 内容不变。
- `FIELD_INITIALIZER_DEPENDENCE` 表示创建输入对 defaults/keyword-defaults 初始字段的依赖。一个 scalar 默认参数不是 defaults tuple 的别名；若要将初始值传到调用时，仍须跟踪 packing、字段修改与实际读取点。
- saved builtins 来自函数创建时的选择，不能直接借用 caller 当前 builtins，也不能等于当前 globals 中的同名项。
- 捕获的是有序 closure cell 引用；cell 引用一致不证明内容版本一致。类在 factory 之后写入的 closure/default 字段，要沿后续状态操作连接，不能假称 factory 已携带这些输入。

这些条件依赖是静态图中可继续分析的关系，不是缓存许可。原端点/来源校验通过、条件由后续推理消解、最终效果闭合，是三件不同的事。

此前发现的接线欠账是：环境关系主要在 CALL target 已知后建立，但分析函数内部全局
读取又需要该环境。现已将 module/class/nested 的原创建证明抽成共享 extractor；默认
Session 按当前 unit 的原词法 owner、DefinitionID、CodeRef 路径及 factory 端口自动配对，
不再等待实例方法 dispatch。没有调用 publication 时，原 manifest 与源码碎片也足以
构造/独立核对 SourceDefinitionReference，无需另写 basis。范围和实际核验见 STATUS。

factory-entry origin 规则分开处理三件事：

| 关系 | 可以表达什么 | 不能据此推出什么 |
|---|---|---|
| 原 factory 的捕获端口 | 产生函数时捕获哪个 globals 引用 | 该 dict 的内容保持不变 |
| 原 body 的环境 formal | 若进入函数来自该 factory 产物，formal 对应哪个对象引用 | 已经发生调用、只有这个来源、所有 factory 实例相同 |
| entry world 上的 namespace read | 指定 key 在此位置有哪些 reaching writes | 创建时 world 等于调用时 world |

前两项只传引用来源，不需要伪造 caller CALL 或 Invocation；代码来源、factory 正常完成、
entry callable 选择及字段保持条件必须显式保留。相同 code 可由不同 globals 创建，也可
被装到别的函数对象上，不能按 CodeID 合并其环境。saved builtins 还涉及创建时选择，
不能直接借用 creator/caller 当前 B。第三项继续走实际状态关系；无已知 caller 时的初始
namespace 替代路径需要单独状态前提，不准把一个捕获引用边升级为内容证明。

class 的创建捕获与 provider 的当前字段读取也分开：原 body-function factory 的 G Use
通过 `CURRENT_FUNCTION_GLOBALS_EQUALS_FACTORY_CAPTURE` 条件，连接到原
READ_FUNCTION_FRAME 的正常 G 结果；条件绑定 body function、捕获 Use、读取 world 和
读取结果。此前的任意准备 callback 不能被跳过。此边是 MAY/REFERENCE，不连接 parent B，
不传递 namespace 内容，也不新建 world。后续再经原 EVAL_SUITE 输入映射进入 class G。

## 跨主体值来源与名称绑定

跨图的 ValueID、OperationID、UseID 始终附带其原 body namespace。外层模块的 factory 即使成为深层函数的调用目标，仍在原模块图中读取、校验和保存；不能拿深层函数的 index 查外层裸 ID，也不复制被调函数体。

名称状态的跨层来源由原 STORE、原控制路径、真实 CALL 的环境/状态接口，以及下一层 entry 到 READ/CALL 的路径组合。多个调用桥可以串接；中间层的同 key 写入必须参与覆盖判定，不能仅沿 globals 引用跳回最初模块、忽略中间状态。module 的 L/G 与函数的 saved builtins 仍分别处理，未证明的 owner alias 必须作为显式条件。

写入失败可能已改变状态，异常路径不能视为未发生写入；正常提交、查找优先级和中间 effects 保持等条件仍保留。递归需求由有限工作队列求解，不能由环自身生成来源；预算和未解析入口单独报告。

源码目录中的声明、旧 CALLS 关系及按同名声明生成的 metadata 只能提供搜索提示。只有与本 CALL 的真实 callee Value、绑定路径和编译来源接通后，才生成目标参数、状态、返回或环境端口。提示没有接通时仍保存在原 metadata/明确前沿中，不能绕过已经发生的覆盖写入，复活旧 factory。

调用目录枚举是否完成、处理范围内的 namespace 队列是否稳定，以及整程序 points-to/effects 是否闭合分别记录。范围内队列稳定不证明所有入口、所有目标和所有属性已经确定。

从外部模块取得的函数可以拥有 caller 图中根本不存在的 globals 引用。此时通过原模块状态、函数创建环境、真实调用的 world 和 callee 环境端口连接依赖；不能借用 caller 当前 G，也不能为了满足某个桥的字段要求制造 caller 中的 namespace Value。`ModuleGlobalsDependencies` 已实现条件状态投影及专项求解/公开读回；现在也由共同依赖接口投影到原 qualified 端点。完整逐地址状态/alias/effects 联合推理与模块初始化 L/G 对应仍未闭合。

新版 v8 的标准 import 初始化投影携带
`SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT`：在该明确条件下，以原 G 为查询点、
用精确的原 `{L,G}` 端口集合统一选择 reaching writer 和处理覆盖。源码 `STORE_GLOBAL`
与 `STORE_NAME` 因而按同一条件地址域的实际控制/world 顺序合流，而不是分别读取再合并。
这仍是条件，没有运行来证明 import hook/loader/cache/后续效果。任意 `exec` 不获此条件，
原 L/G 各自查询互不覆盖。v7 及更早记录保留原 L-only 语义和未知别名，不自动授予新条件；
带新条件伪装成旧 wire 会被拒绝。相应规则、kill 集合及重放必须使用同一个明确 owner 域。

模块 `global` 是编译期作用域声明；原 AST、符号表和编译来源足以确定时，保留源码展开
记录而不制造运行时 Nop。编译器前导与源码 import 共用位置时，必须沿已验证的 compiler
profile/offset 分界，不能按 source span 把前导误认为 import，也不能任意跳过未知指令。

模块 AnnAssign 也不等于普通赋值：默认 3.14 的 annotation registration 与延迟 child，
future 模式的原字符串槽与 `__annotations__` 更新分别表示。RHS/store 成功后才能登记；
实际 namespace lookup 的结果才是更新 owner，同名 compiler cell 不能替代它。原索引、
正常/异常的引用消费、world 和源码见证独立核对；未展开 child 不因顶层完成而消失。

该状态桥区分：`fn=p.f; p.a=p.b; fn()` 的函数引用来自早先的 `p.f` 读点，G 内容却在真实 `fn` CALL/world 查询；`p.f=q.f` 后所选函数的 G 属于实际 factory 的 q，不能按表面 receiver p 判断；`p.a=p.b; p.b=other` 中 a 的来源是赋值当时的 payload/读点，不是未来的 b。callee 内同 key 的 STORE_GLOBAL 先参与覆盖，只有 entry binding 仍可到达 READ 的路径继续向外层状态查询。新版初始化条件域已有通用静态验证并随 v8 调用索引发布；当前真实索引的 module globals flow 仍为 0，完整接线不能由专项样例推定。

实参、形参和正常返回的引用来源必须按调用上下文连接。`StaticCallContext` 引用原 caller、CALL、callee Use 和所选目标，不代表一次运行调用。沿返回结果进入 callee 时压入该上下文；从 formal 回到 actual 时，只能消费栈顶匹配的原调用，再回到其 caller 上下文。已有明确上下文而缺少来源时，不得退回无上下文的候选并集。否则 `identity(a)`、`identity(b)` 或多层 callback 的返回值会错误混合。

求解器分别维护各上下文的关系，导出时才合并同一静态 CALL 的展示记录；展示并集不能反向激活目标。参数/返回引用边不证明内容不变、逻辑版本相同或无副作用。默认参数还需要函数当前 defaults 字段、容器元素和读取时状态，初始化输入不能直接当作缺省 formal 的引用。

分析会话中的原图、原 metadata/document 和源快照只读；传播新增关系和属性事实，不能原地改写这些原输入后继续复用派生记录。主体重建产生新的 artifact receipt/namespace。内部有界缓存可复用原 typed 记录和按明确输入派生的关系，不跨输入保存“验证已通过”的布尔标记；独立 public reader 仍从原输入重新核验。

## 属性事实与未知

事实锚定已有实体/Use ID、程序位置、状态版本和分析上下文，包含依据及成立条件。
每个属性可为精确值、符号表达式、受限候选/约束或未知；这些状态分别传播。
尚未分析、已分析但不确定、缺材料、未支持和预算截断分开记录，不伪装成程序事实。
不适用的属性不填 UNKNOWN；不可达也不等于未分析。

地址未知不影响已知 dtype；shape 未完全确定仍可保留每个已知维度和维度等式。
读取或修改引起的失效只传播到相关事实；不能因为一项未知就将整个节点或子图标为未知。

已知内容现在分别进入 `scalar_constant` 与 `immutable_tuple`，后者只允许递归不可变的
builtin literal，不表示 Python 对象身份、storage 或 Tensor 内容。原 tuple 构造、参数/返回、
绑定和索引按原 AST/Opcode/Use 及上下文传播；未知索引、mutable 元素、覆盖和越界保留
精确前沿。编译常量只在原源码、CodeKey、constant path、frame 和 LOAD_CONST 对应后读取
静态编译产物，并附 `ACTIVE_CODE_MATCHES_SOURCE_COMPILATION`，不冒充运行 code 对象。

EnvironmentInterface 成员与 ControlPort 目的地也已有声明导航，使用结构边和原记录
locator。环境 state domain 不是 points-to，声明的控制目的地不是一次实际 transfer；
结构不能被值引擎当作等值传递。具体运行绑定和协议转移仍有独立前沿。

原 BRANCH 的 CONTROL_CONDITION 是可推理依赖，而不只是 CFG 展示信息。只有一次完整
有限固定点得到无 unknown/MAY、无未消解外部 guard 的一致 builtin bool 后，才冻结该
上下文的 successor 选择，并从原 seeds 重算受条件限制的值传递。原图的两个分支与边
仍保留；`branch_proofs` 引用原 branch、谓词 Use、常量依据和所选 ordinal。不能凭临时
单值、未收敛循环或 INVOKE 的正常/异常 ordinal 筛掉另一条路径。这不是代码变换。

控制影响与必要路径前提分开：postdom 控制影响可能是 MAY；原 successor edge 对入口
可达性的支配，才支持“若从该入口执行到此处，必须经过该选择”。共同图保留两类原依据，
必要性查询覆盖非循环区域，每个 block 仅保留最近必要选择，再沿 controller 递归查询，
不物化全部传递祖先。exact 必要关系仍受原入口范围限制，不证明调用结束，也不抹去
挂起/恢复、外部入口及效果前沿。普通 CONTROL 不能直接用作值传播的路径筛选条件。

值事实的 `occurrence` 字段独立记录进入原位置所需的选择及入口范围。结构 ownership
边只把 producer/block 的发生条件交给原结果/Use，不传递内容或引用身份。固定点后若
均匀 branch proof 与必要选择冲突，可记录原 route 的反证；原边保留，派生值从 seeds 重算。
完整原正常返回族全部被反证才允许标无正常值；缺来源、MAY、未知目标或范围未完成不允许。
保存的 Python candidate frame 尚不自动获得原同步入口证明，继续保留字段级 open。

source role 和人类标签也不等于操作合同。例如源角色为 EXPRESSION 的操作仍可有原
TRUTH 协议；分析必须消费准确协议/端口及来源，而不是按 label 或 role 猜行为。

已知端口结构也不是待消解的运行条件：`CompletionResult.index` 通过原 successor.arguments
记录和目标 block argument 直接核对，并保存精确证据 locator；不再把槽号塞进 guard。
值转移同时核 normal kind、原 producer、实际 mapping、ordinal 和同一 namespace/context，
不能因异常出口也有 slot0 就复制正常计算值。TRUTH 合同可对闭合 builtin literal 的表示
推导 normal bool（含浮点/complex 位模式、tuple 长度），不执行目标对象协议；原 world、
异常出口、effects 和输入条件继续保留。绑定是否 BOUND 是独立状态性质，已知 payload
或可行 normal 路径不能替代 definite-bound 证明。

绑定状态现有独立 `BindingStateField`：BOUND/UNBOUND alternatives 带原条件、证据、
前提和 EXACT/MAY，另有 unknown paths 和不适用。UNKNOWN 更新不能借用旧 token，
payload 已知与否不决定 boundness；旧 `binding_states` 只是便利投影。原 BindingRead
输入在同一上下文中所有来源均确证 BOUND 后，才能给出 `BindingReadProof`；原 guard
和边保留。MAY、缺种子、未枚举、预算与循环的未知沿同一队列传播。

有限不动点收敛与输入覆盖完整也分开。`worklist_stable` 表示当前已表示约束和 UNKNOWN
传播已稳定，`exhausted`/导出的 `query_scope_complete` 继续描述查询范围是否完整处理。
无关未枚举区域不能把其它已闭合字段和证明一并拒绝；受其影响的字段仍必须保持未知。
步数/求值早停未收敛时不冻结新证明。这个区分不是整程序完成或变换许可。

NativeBoundary/provider 也按原声明进入共同导航：native/core-only 输入、正常/异常
出口的全部原 Use、representation ownership 和来源映射都有精确记录 locator。它们是
STRUCTURE，不是值传递、ABI 等价、must-alias 或已选实现。共同遍历默认排除结构含义，
区域 cut 也不将其当成输入/消费者；不能仅根据关系 kind 判断是不是数据依赖。

静态 native 材料复用安装包的 schema parser 作为分析器工具，在隔离进程中解析原
ATen header/YAML，核对版本、完整 overload、文件/字节/行与 parser 收据；不导入 torch，
不运行目标、生成器或默认值。结果能构造现有 ProgramGraph/NativeBoundary 的接口，
保留 opaque native world 和正常/异常端口。Tensor/List/Optional 端口不展平为虚构 ABI；
alias/write/dispatch 仍是原 schema 声明，不提升为物理资源或已选 kernel。材料接口、
Python callable 绑定、native 实现主体、当前整程序发布是四个分别核查的层次。

C++ 输入层也保存原 occurrence，而非将 CST 当成最终程序 IR。SourceAtomID 引用被原
source receipt/SourceReference 限定，函数完整 declarator、表项 callback/wrapper、call 的
有序参数、原条件与模板孔形成 SOURCE/STRUCTURE 图；同名 overload 为不同原定义候选。
没有类型/ABI 证明时，不把 C++ 表达式伪造为 canonical DataValue/ReferenceValue。物理
保存按源单位分片，source path/hash 和原 occurrence ID 表只存一次，其它边使用单位内
整数引用；索引只是存储坐标。读回恢复原强类型记录，不改变 source/program 身份。

## 效果

至少保留 reads/writes/allocates/frees/aliases/escapes、RNG、may_raise、external、ordering，以及必要的生命周期和完成语义。效果可多标签，不互斥。
未知调用的可能效果不能写成 NONE；已解析源码和契约应继续推导，而非永久放弃。
整体 world 状态可作保守起点，别名/ModRef 查询负责排除无关写，不无限细分 OS 内部。

## 完整性的含义

分别报告源码/定义覆盖、结构展开覆盖、跨层连接、效果覆盖及属性精度。
缺函数体不能用一个 UNKNOWN 叶子顶替后计作已完整展开；地址未知也不能让已恢复函数体退出结构覆盖。
静态分析保留范围内全部可能路径，包括未实际执行的定义与分支。
一般程序的全部行为无法静态精确判定；目标是健全的结构与关系表达及尽可能精确的可推导事实，不宣称任意程序的唯一最优实现。

具体流程见 [静态架构](STATIC_ANALYSIS_DESIGN.md)，展开规则见 [程序分解](PROGRAM_DECOMPOSITION.md)。
