# 第一阶段：纯静态整程序建模与建图

## 目标与现状

第一阶段只做一件事：不运行目标程序，从源码、配置、依赖实现、语言和库契约中取得可静态确定的信息，建立可展开、可查询、跨层依赖接通的程序图。之后才讨论化简。

当前**未完成**。已实现共同跨分片依赖接口、首版值推理和区域边界查询。尚无新版整范围调用索引；完整状态/alias/effects 联合推理、依赖和资源映射均未闭合。最新事实和数量以 [STATUS](STATUS.md) 与 current manifest 为准。

按本计划自行验收，结果回写现有 STATUS，代码使用 Git 管理；不新增历史目录、worktree 或一套 gate 报告。

## 当前最高优先级：把已有子图组成同一逻辑依赖图

AST 是输入，局部 canonical 已有 CFG/SSA/状态图。原结构性缺口是跨主体关系缺少共同导航；
该接口及首版消费者已实现，见 [程序分解 §3.4](PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

按以下顺序推进，自行核查后写入 STATUS，不等待用户逐项审批：

本轮先修两项源码阻断（compiler prelude/import 和编译期 Global），完成 v8 初始化状态域、
无 artifact 按需派工及预算计量；短核验完成后做一次整范围调用发布。真实两份模块的新
重建已推进至 AnnAssign；其后将继续该通用注解协议与 class SETUP_ANNOTATIONS，而不为
样本文件写规则。当前已发布图的旧主体不因此自动算新覆盖。

当前立即执行的三个修复单位：①同一 live task 继续全范围 calls 发布，先确认越过已定位的
大主体缓存热点，不因观察超时重启；②原 BRANCH 谓词闭合后按证据重算值路径，保留原图；
③复用原生声明工具补 native 接口与共同导航，下一步补真实 Python binding/参数转换到
完整 overload 的连接。②③已有短核验；①运行中，③的整程序连接仍未完成。之后再恢复
AnnAssign/主体覆盖和联合状态推理，不跳到 detector/backend。

新增明确修复项：计算 normal result0 只传到原 NORMAL landing，不能因 RAISE 也有
slot0 就复用；TRUTH 从原协议合同识别，并按已知 builtin literal 表示推导正常 bool，
原异常/效果和外部 guard 保留。原编译器折叠的 `if True/False` 无对应 bytecode 时，目前
前端仍保持 REQUIRED_EXPANSION；需补静态折叠/零指令语法展开，不能列作必须动态观察。
producer/current 冻结结束后与 AnnAssign 一起推进。

绑定状态独立 domain 与原 read guard 证明已实现；不动点收敛/原 scope 完整分开。
接下来的共同推理任务是：把原 JUMP/RETURN 等 source occurrence 的必要入口条件接到
同一值队列，而不是只识别 BRANCH 的选择。查询原 Use owner 的 exact entry-necessity
关系，并沿 controller 继续追踪；普通 postdom/MAY 影响不能作路径前提。跨 frame、恢复/
外入口、未证 guard 和预算保留范围，所有候选路径被确证反证时才可标 infeasible；不另
建 solver/图、不删原 source edges，也不按源码行或业务 label 推 reachability。

1. **共同依赖图（已实现，完整覆盖待核对）**：qualified 原端点、上下文、typed 关系、原证据、
   共享只读加载；接局部、call/env/G、class provider 和控制依赖，公开遍历。
2. **首版共同分析（已实现）**：原操作 cut 的字段级边界；跨参数/返回/绑定的有限常量、
   builtin 类型和定义来源工作队列。覆盖赋值不能借用旧值，预算不能抹掉已知字段。
3. **真实全范围接线（class 已枚举发布，calls 待发布）**：核对公开共同图穿越真实
   parent/provider/suite，再发布新版 calls。任务运行与成功发布分开，不重启仍推进的长任务。
4. **消除推理欠账（持续）**：module 初始化 L/G 已有 v8 条件地址域与通用验证；继续补 binding/容器字段及
   逐地址状态关系，将 alias/effects、类型/常量/Tensor 属性接入同一固定点；不能从一般
   依赖直接推身份，不能通过删除条件让 CANDIDATE 伪装成 EXACT。
5. **恢复覆盖推进**：成组补主体结构和按需依赖/native/资源契约，再核对整范围，
   不以小型接口检查或局部固定点代替第一阶段完成。

暂停重复扩大材料是为了先接通已有图，原覆盖分母和所有欠账继续保留。以下完整验收和
实施步骤仍有效；本轮不做化简、detector、backend 或目标运行。

## 验收到底看什么

模型需要同时满足四项，不能用其中一项代替其它项：

- **实体**：程序中的操作、值、状态位置、区域和资源，以及具体的端口、绑定、控制与完成类型，有明确表示。
- **关系**：输入来源、调用、返回、正常/异常、状态读写、别名、逻辑来源和资源依赖能跨模块、函数和实现层追踪。
- **推理**：已有事实继续传播，相关读写使事实失效或合流；不能已知源码可推导却永久保留一个待补规则的 UNKNOWN。
- **覆盖**：输入范围、已处理范围、未知字段与缺失结构分别可核对；目录存在、有规范图、零 ERROR 都不是整程序完成证明。

地址、运行实例、确切 kernel 选择等未确定时保留符号、候选或条件。已知 shape/dtype、操作数、控制和状态关系仍须保留。缺实现、缺材料和预算未处理不能伪装成静态不可知；不可达、不适用和未知也必须区分。

## 当前欠账

| 层次 | 当前不足 | 对建图的实际影响 |
|---|---|---|
| 输入材料 | 当前含 862 份源码/声明文件；已送前端 280 份外部材料，依赖实现、配置事实、原生算子契约仍未完整接入 | Python 调用之后还不能完整追到库、runtime API/kernel 接口和资源 |
| 主体展开 | 107 项模块后缀、45 项 class suite 后缀、326 项 lowerer 不支持、404 项规则形态不支持；3,731 个入口适配项待核对独立/内联归属 | 一些已知源码仍未形成完整规范子图 |
| 跨层连接 | 共同接口已接 parent/provider/suite 和条件 G/state；class 已全批枚举发布且缺口显式，calls 未发布，初始化 L/G 已实现条件域但新版真实 calls 待发布，defaults/容器和隐式协议仍不完整 | 已有子图仍不能组成完整的数据与状态依赖图 |
| 联合推理 | 首版 scalar/type/定义来源已消费共同图；完整 points-to、逐位置状态、effects 与容器/Tensor 属性尚未联合求解 | 条件无法充分消解，已知局部性质无法贯穿整程序 |
| 全量交付 | 新版调用索引未发布；长任务已有 PID 身份、进度和终态记录，须完成全批发布与公开读回 | 局部回归和进程内计数不能证明整范围完成 |

3,731 个缺适配目录项中有部分已在父图内联，不能机械地理解为缺少同等数量的 Python frame。库摘要可以作为有版本、来源、接口和效果范围的抽象边界，不能以一个没有内容的 OPAQUE 计作库内部已经恢复。

## 实施顺序

### 1. 固定输入与缺口，确保每次运行可核查

沿现有 static_sources/static_imports 建立程序所需的源码、声明、配置和库契约清单，记录版本、来源、外部边界与未提供项。按实际引用扩展依赖，不能把整个环境里无关的包全部展开，也不能把范围永久缩在某轮文件清单。

以原实体/端口为锚点整理缺口：缺主体、缺连接、缺推理规则、缺材料、预算未处理、静态信息不足。一个节点可以有若干已知字段和某个未定字段，不用一个笼统标签覆盖整节点。

完善分析任务的阶段、进度、退出原因与结果位置记录。先解释上次为何结束，再决定重试或修复；不把消失的进程说成仍在运行，不反复启动没有可核查结果的整树任务。

**自行验收**：输入清单、剩余范围和缺口均能定位；当前唯一已发布图与临时任务明确分开；每次任务均可知道处理了什么、保存了什么、为什么结束。

### 2. 自顶向下接通已有子图

首先完成跨模块函数的 G/state 桥，再接标准 builder 的 prepared namespace 与共享 class suite；随后统一隐式调用、decorator、当前 defaults/元素和 closure 内容传递。每项都以现有 Operation/Value/Use、frame ABI、world 和正常/异常出口为基础，不按业务名称补目标，也不复制 callee 图。

G/state 桥须区分函数引用来源与调用时内容：`fn=p.f; p.a=p.b; fn()` 中 fn 来自旧读点，G 的 a 却在真实 CALL/world 查询。`p.f=q.f` 时 globals 归属由实际 factory 确定；setter 消费其当时的 payload，不能重新读取未来的 b。不制造 caller 中并不存在的 dict Value。

类体的 L 必须来自 prepare 正常结果或实际 mapping allocation；G、saved B、closure 和 world 按 body-call 位置连接。suite 的 cell/None 不是最终类对象。未知 builder/descriptor 等保留有条件接口和可能分支，已知 header、factory 和端口继续展开。

**自行验收**：从真实入口向下查询，可以跨边界追到输入、环境、状态读点以及返回/异常出口；赋值覆盖和不同调用上下文不混淆。用通用源码证明规则，再在 LeWM 原源码链上核对；只新增类型或数据表不能算接线完成。

### 3. 按共同原因补齐结构与语言组合

围绕实际剩余范围，成组补齐模块后缀、nested-with/cleanup、comprehension/lambda、generator/async、annotation/type scope、表达式与 compiler 前导组合。先核对已内联和独立主体的归属，预声明接口以支持前向引用和递归，不无限内联或逐迭代复制子图。

保持 Python 求值顺序、部分写入、正常/异常/挂起等适用出口。SourceGraph 已有信息时应使用原 AST/作用域/端口继续构造；旧 overlay 缺记录不等于源码未知。只展开对程序重组和正确性有用的层次，OS FD 表和机器指令不作为目标。

**自行验收**：范围内每个源码构造有规范结构或明确的外部/符号边界；有源码却缺 lowerer 的区域仍列未完成。剩余源码和未处理项不能通过缩小分母消失。

### 4. 联合推理值、状态、效果、属性与资源

复用现有 qualified 工作队列，扩展为调用目标、值来源、抽象堆/别名、状态、effects 和属性相互反馈的固定点。循环使用回边/合流，递归使用有限摘要及明确精度策略；新事实必须唤醒所有相关任务，包括没有 CALL 的主体和未返回的值。

逐位置记录 read/write、allocation/free、alias/escape、RNG、异常、外部和 ordering；未知效果不填 NONE。逻辑来源、对象引用、内容版本、storage/view 和物化分开，不能由引用/shape 相同推出内容相同。

传播常量、类型集合、符号范围、Tensor shape/dtype/device/layout/stride/offset 及其约束；源码与安全配置能确定的继续推导，不保存 Tensor 数值。重定义、原位写和可能共享写只使相关事实失效。

通过有版本的 Python/PyTorch/native 契约连接分配、搬运、IO、enqueue/wait 与执行/存储资源，覆盖 CPU/GPU、DRAM/HBM、文件/storage/SSD/NVMe、stream/线程角色。表示可静态确定的要求、候选和依赖；实际地址、传输是否发生、确切 kernel 和完成时刻不伪装为已观察事实。.to() 可能不复制、expand() 可能是 view、eval() 不证明纯性、推理也不默认关闭梯度。

静态 native 材料已定点核对，后续直接复用安装包提供的 ATen `*_ops.h` 与
`torchgen/packaged/ATen/native/native_functions.yaml`，不自行编造算子语义。当前材料声明
版本为 2.13.0+cu132（不是目标运行观测）；材料需由 dist-info RECORD/源码 git/schema
指纹定位，operator key 必须包括 overload。先从已解析 callable 接到有条件的 ATen overload、
native 候选符号和符号资源要求，再谈 kernel 选择；不能按函数名相同直接认定身份。

`to/copy_/empty/expand` 的少量原 header/schema 已核对参数、默认值、SymInt、alias/mutation
和 dispatch 候选；自动抽取、canonical NativeBoundary 接口及其共同声明导航已实现，
已有 6 个实际 overload 的静态核验。它们尚未发布到 current 整程序；Python callable
绑定和具体 native 实现仍缺连接。schema alias 是允许共享的声明，不能
推出相同对象；`empty_cuda` 不是实际 cudaMalloc，`.to` 不是传输，`expand` 不表示完整分配。
设备/stream、实际 kernel、物理地址和搬运等未绑定信息保留在准确字段与契约条件中。
只在 `-I -S`、原文件收据和受限工具导入链下执行 torchgen 的纯 schema parser，
作为分析器工具复用语法；不导入 torch、运行生成器/目标初始化或执行默认值，不把 native
stub 当作已展开 kernel 主体。Python binding 需分别沿真实方法表/函数体、参数转换、
C++ wrapper 与 `_ops` 声明建立有条件关系；只有 stub/未展开生成规则的地方明确列缺材料。

已核对的通用输入材料包括 `torchgen/packaged/autograd/templates/python_variable_methods.cpp`
的真实方法表/手工 binding，`torch/include/torch/csrc/autograd/utils/python_arg_parsing.h`
的参数规范化，以及 `torch/include/ATen/core/TensorBody.h` 的 `_ops` 调用。模板占位与实际
函数体分开；安装包材料只支持条件化构建来源，不自动证明当前 native binary 的运行绑定。

C++ 源码输入层优先复用 [Tree-sitter](https://tree-sitter.github.io/py-tree-sitter/) 与
[C++ grammar](https://github.com/tree-sitter/tree-sitter-cpp)，不另造词法器。项目已在
`.venv/native-source` 隔离安装 0.26.0/0.23.4，约 19 MiB，LeWM 环境未改。
实际 template 可解析；当前组合的 `Point.row` 属性访问可崩溃，使用原 byte offsets 与
换行索引推导位置已两次完整遍历一致，准确复验证据保留在当前 query。不能把这次工具
API 失败写成源码不可解析。CST occurrence/SourceReference 是源输入层，最终程序仍由
现有 canonical IR 表达；不把未知 C++ 表达式强填为 ReferenceValue 或 DataValue。
整张显式方法表→callback/wrapper 表达式→原定义候选→body 调用/参数/条件的 source
reader 已实现；模板孔、预处理条件、overload 和缺 body 逐字段保留。无损的单位内规范化
存储/读回已核对。下一步接 native header/接口契约；C++ 类型/绑定/实参转换仍需继续分析，
不能把 SOURCE 候选边直接升级为 canonical 值或实现等价边。

**自行验收**：每项已推导字段及关系有来源、条件和失效依赖；不同对象/调用/状态版本不被错误合并。沿真实 LeWM 的加载、预处理、规划/模型调用到输出/保存路径能查到已知的值、状态、库接口与资源依赖，而不只是查到一串 Python 名称。

### 5. 全范围构建、读回与交付

对完整输入清单构建当前图。先验证局部规则和边界接线，再做整范围验证；相关检查只围绕新增语义与真实失败，避免堆积重复测试。预算、失败和未支持项逐项保留，不能把抽样或局部固定点说成全程序完成。

唯一大图输出仍为 `artifacts/current/static/`。沿用强类型记录、ID 引用、按源码/主体分片和共享定义；不引入另一个权威图、数据库或历史输出目录。查询可递归展开，并跨分片追踪原端口和事实；保存图和公开读回需一致。

**第一阶段结束条件**：依赖范围已明确并覆盖；该范围内已知源码的结构和跨层关系完成；可用材料支持的分析规则已执行并传播到稳定；库/资源边界有实际接口和契约；剩余未定信息是带理由的字段/关系而非被隐藏的实现欠账；全图可构建、存储、查询并核对处理范围与分析耗时。未达成则继续第一阶段，不进入化简或优化。

## 工作边界

保持唯一正在开发的 checkout，保护外部 LeWM 与环境。模型和图沿用现有 canonical IR；新关系引用原 ID，不创建业务特例、假 Invocation 或一套平行事实权威。

本阶段不增加 detector/backend、不改写目标程序，不运行其 import、初始化、回调、trace、profiler、benchmark 或动态验证。分析器自身可以执行、静态编译、查询与校验；采集和测量的后续需求另行安排。
