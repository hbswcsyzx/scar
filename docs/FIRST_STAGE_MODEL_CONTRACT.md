# 第一阶段：完整程序建模与自动恢复验收合同

日期：2026-10-20。状态：**设计与实施合同；第一阶段未完成。**

## 1. 当前任务与停止条件

用户最新要求优先于旧路线：**先完成完整程序建模，再推进图化简。** 第一阶段
既包括设计，也包括从未修改的 LeWM 自动恢复模型的实现和实际验收。旧文件中
“M0–M2 只验收声明接口，自动恢复移到 M3/M4”不再是第一阶段的完成定义。
本文不废除历史协议义务，也不将其全部实现当作端到端集成的串行前置。

本阶段中的模型文件和关系连接用于验证抽象是否成立，不开展候选搜索、化简、
代码变换或性能 A/B。停止点是：自动产物满足下列验收，整理讲解后向用户汇报。
不能用通过多少单元测试、多少 supplied graph、多少 AST 标签来替代这一验收。

## 2. 什么叫完整

每次验收绑定一个 AnalysisScope：入口 argv、cwd、代码/依赖版本、配置及输入
身份、运行模式、进程树、采集起止、软件接口和硬件资源观测层级。首次复现使用
已成功的 LeWM pusht 单 episode 命令，不擅自缩短其预算来宣称全流程完成；其它
配置、未执行分支和潜在依赖在静态部分另列，不能声称已被这次执行验证。

“所有软硬件资源”要求从 Python、原生库到 OS/CUDA 所实际涉及的资源都有身份、
使用者、生命周期及依赖归属；不是只列一张 GPU 型号表。硬件的建模单位首先是
可分配、可调度、可访问、可等待的接口资源，例如设备、内存池、allocation、
stream、文件及进程。SM/cache/磁盘控制器的内部实现若未观测，必须单列为未解析
的物理细化；不能宣称已恢复所有硬件内部活动，也不能因而无限手写驱动解释器。

2026-10-26用户明确深度：软件从最高入口、层层函数和依赖深入runtime API/kernel；
硬件包含CPU/GPU、DRAM及实际涉及的SSD/NVMe等存储层次，不需要机器指令层。
NVMe协议、SSD介质、文件系统和逻辑块设备分别表达；GPU内存不一概标HBM。
实际拓扑、使用关系和来源须核实，不能从路径/设备名称猜测。具体工作和Root自身
验收节点见[FIRST_STAGE_IMPLEMENTATION_PLAN.md](FIRST_STAGE_IMPLEMENTATION_PLAN.md)。

覆盖至少分别报告：

1. **结构归属**：源码/库/事件/资源属于哪里，是否漏项。
2. **依赖连接**：输入输出、读写、控制、异常、别名、生命周期、顺序是否接通。
3. **内部展开**：恢复了内部结构，还是只有带合同的接口边界。
4. **运行对应**：关系来自静态推导、真实观测、库合同还是未满足的条件。

OPAQUE、UNSUPPORTED、未观测和采集丢失都可如实表示，但不计作该项已完整恢复。
接口有模型不等于库内部已展开；一次 trace 不证明全部可能执行。未满足上述
合同的必需项使验收保持 OPEN，不能通过修改覆盖率分母获得 PASS。

### 2.1 必需项与展开层级必须先固定

AnalysisScope 中的每个 obligation 都要有稳定 ID、来源、subject、必需关系集、
required_expansion 和 mandatory；它是验收记录，不新建一套执行图。展开层级为
SOURCE_BODY（内部源操作）、PROVIDER_GRAPH（版本化算子子图）、PROTOCOL_INTERFACE
（库/OS/CUDA 接口）或 PHYSICAL_DETAIL（更细物理实现）。前三层按实际来源选取，
不能事后为了通过验收把源函数体改成无内容外壳。标记接口层时仍须闭合有序输入/
结果、影响的状态与后态、alias/escape、控制/失败、资源及 ready/lifetime 接口。

由全部源构造、实际调用、原始 provider 活动和独立 OS 清单生成分母；实际出现的
调用或资源必须入账，不能让配置筛选删除。只要必需关系仍未解析，该项 OPEN。
已选为接口层且接口经来源验证完整，可以验收接口覆盖，但报告内部展开数保持 0；
不能把它写成 native 内部已理解。未列为必需的 PHYSICAL_DETAIL 单列，不进入
接口覆盖分母。scope/mandatory 的任何修订须保留差异及理由，不静默降低要求。

## 3. 实体清单：五类核心结构不是所有记录的全部

不再用“只有五种节点”回答整个程序是什么。分清规范定义、实际发生、内容与
物理实现、证据四组身份。以下表格是模型审查清单，不声称所有自动适配器已实现。

### 3.1 规范程序结构

| 实体 | 对应程序的什么部分 | 必须连接什么 |
| --- | --- | --- |
| CodeIdentity | 源码快照、编译/code 版本及位置；不只行号 | 版本化来源、作用域、Operation/Region、运行代码 |
| Operation | 一处求值、调用、读写、import、分配、搬运、等待或外部操作 | 有序 Uses、结果、状态、控制与完成、资源要求 |
| ValueDefinition | 一个定义结果或 Region 参数；数据、引用、绑定、状态与协议值分型 | 唯一 producer、逐槽 consumer；跨分支/循环/调用传递 |
| StateLocation | 可变位置/域：字段、容器槽、buffer、namespace、RNG、文件内容等 | owner、selector/footprint、别名、前后版本及读写 |
| Region | 模块初始化、函数/方法、循环、分支、上下文和库子区域 | 入口、环境、内部结构、全部完成出口；可递归展开 |
| ResourceDefinition/Requirement | 执行或承载能力的身份/要求；不是一次活动 | 使用操作、同/异/从属资源条件、容量与生命周期要求 |

CodeIdentity 是来源身份。Operation / Value / StateLocation / Region / Resource
是规范结构的五个支点，不能因此省略以下独立生命周期和身份。

### 3.2 实际发生与环境

| 实体 | 对应什么 | 身份区别 |
| --- | --- | --- |
| Run / Process / Thread | 一次运行、进程实例、线程实例 | PID/TID 再用需要代次；记录父子关系与采集区间 |
| RegionActivation / Invocation | 一次区域执行/调用；可含多次挂起恢复 | 同一个函数定义不等于同一次调用 |
| OperationOccurrence | 实际发生的一次操作 | 循环每轮/重复调用分别记录，指回规范定义 |
| ValueOccurrence | 某次 activation/visit 的实际值 | 同一个静态 ValueID 不意味着跨轮不变 |
| ObjectInstance / Environment | Python 对象、module/function、globals/defaults/cells 等实际身份 | 同 code 可以有不同环境；引用不是内容 |
| StateVersion | 一个位置在一次读写关系中的前/后态 | 状态版本不是保存了完整状态快照 |
| ResourceInstance / HandleBinding | 实际设备、队列、文件、进程等及访问 handle | 多 handle 可指向同一资源；fd/地址复用不是同一生命周期 |
| ResourceWork / Completion | enqueue、执行、copy、wait 和资源就绪事件 | host 返回、语言完成和 GPU 完成不能混为一项 |

### 3.3 内容来源与物理表示

| 实体 | 含义 | 必须避免的混淆 |
| --- | --- | --- |
| LogicalValue / ValueVersion | 数据 lineage 及其不可变内容版本 | 不依附 StorageID，不根据变量名或样本相等合并 |
| Provenance | 一次产生/变换的实际输入版本、状态依赖及操作来源 | 同来源不等于同内容；缺来源不能伪造 |
| Allocation | 一次内存分配生命周期，含 pool/device/大小 | 裸指针相同不证明同一 allocation |
| StorageRegion / View | allocation 上的 offset、shape、strides、dtype 与覆盖范围 | expand 不必分配；不同 view 可部分重叠 |
| Materialization | 一个逻辑版本在某表示/资源上的可用副本 | copy 与新计算分开；需 producer、有效期、失效及 ready |

这些是已有 core/v2/execution 身份的连接职责，不复制一套可独立修改的 producer、
state、heap 或 def-use 图。相同来源、对象、内容版本、物理副本必须分别查询。
完整 Tensor 数值不默认保存；metadata 和少量样本只用于筛选，不证明版本相等。

### 3.4 一行代码不是一种实体

`a[i] += f(x)` 包含引用/索引求值、读取、调用、运算、写回及其失败出口；不能
给整行贴 COMPUTE 就算建模。注释/空白保留在来源快照，不制造虚假的执行操作。
函数定义还涉及定义时求值、环境/函数对象和未来调用的 body，三者分别表示。
import 包括解析/加载、初始化、模块缓存和绑定变化；保存 Tensor 与保存视频
统一分解为表示处理、buffer/搬运、目标状态写及完成/关闭，不引入业务节点类。

### 3.5 非执行事实

Effect 描述操作的 reads/writes/allocates/releases/aliases/escapes/RNG、异常、
外部与顺序接口；Contract 指定保留目标；Evidence/Measurement 记录来源、适用
范围、时间和成本；CoverageObligation 记录尚缺的事实。它们有类型与引用，但
不是凭空新增的执行步骤。未知必须落到具体位置、端口或状态域，不笼统结束。

## 4. 如何组合成整个程序

规范模型保存实体和 typed relations；“操作节点—数据边—递归展开”是其投影：

```text
Region(entry / module / function / loop / provider subregion)
  Operation --ordered Use--> ValueOccurrence/ValueDefinition
      |                          |
      |                      producer / provenance
      +--reads/writes--> StateLocation + StateVersion
      +--requires/uses--> ResourceDefinition / ResourceInstance
      +--controls/completes--> successor / caller / cleanup
      +--realized by--> host/native/kernel/copy/wait occurrence
```

必须分别连接：有序数据 use、状态前后态、控制与异常、区域包含、调用 actual/formal/
return、alias/view、来源与物化、资源使用与生命周期、异步 happens-before、来源证据。
包含不是调用，调用不是数据依赖；时间相邻不是因果；同一个对象不是值不变。
来源结构和实际执行分别存储、显式对应；本阶段不建立 Optimization Graph。

## 5. 自动实现：静态分析与动态证据互相补全

入口只要求原始命令/源码与环境/范围，不允许提供业务函数名单或手工 IR：

```text
命令、配置与版本
  → 静态模块/作用域/构造与依赖候选清单
  → 从进程启动到退出的 Python / Torch / OS / CUDA 证据
  → 按来源身份连接定义与 occurrence
  → 有序端口、状态、值来源和资源适配
  → 对比独立清单，报告未归属项/断开的关系
  → 只对实际阻塞项作通用补全，自动重建与复核
```

| 信息 | 优先复用的来源 | 自动化时的边界 |
| --- | --- | --- |
| 全部 Python 源构造、作用域与编译位置 | ast / symtable / dis、现有 source/inventory 前端 | AST 清单不是 CFG/效果已恢复；保留未执行分支 |
| 实际 import、动态加载、调用与返回 | 现有 call recorder、sys.monitoring、loader/code 快照及 Python audit | CALL 回调不提供任意完整参数栈；不得声称仅靠它恢复全部值边 |
| Tensor/module 与算子输入输出 | 已有 ETO、profiler event tree，已有 FX/Export 图按范围导入 | 不在 live 程序偷偷重跑 forward；不把变换后图冒充原执行 |
| mutation/alias 与 Tensor 状态 | 版本匹配的 ATen schema、实际输入输出、外部 alias 写入证据 | `_version` 或函数名后缀不是通用变化判据 |
| CPU/GPU 工作、实际 copy/sync | torch.profiler / Kineto 原始活动和 correlation | 不按 `.to()`/expand 或邻近时间猜物理活动 |
| 文件、mmap、pipe、进程/线程、动态库和设备 | OS 事件及本进程树 /proc；必要时 strace 作独立对照 | 快照无法排除短生命周期资源；Python audit 不是全 OS syscall tracer |
| stream/context、allocation、显存与就绪 | 版本固定的 profiler/runtime 可用字段 | utilization 抽样不等于资源实例或生命周期模型 |

优先检查本机已有接口及已归档证据；不新写 CUPTI、不引入完整解释器、不按
LeWM 函数名补规则。资料依据见 [工具调研](TOOLING_SURVEY.md) 和
[集成设计](MODELING_INTEGRATION.md)；本机适配器是否接入必须另有运行证据。

自动范围是可追加的：静态发现给候选，实际 loader/call/code/OS 证据发现动态
依赖后补入范围，再重新分析。达到预算只报告具体剩余工作，不称收敛或完整。
必需的输入/结果/状态/资源边不能用时间戳和同名猜接。

## 6. LeWM 压力验收：从加载到输出

下面是外部测试期望，不是 SCAR 内部的分支规则。实际资源由采集自动发现：

| 全过程 | 必需表达与连接 | 独立核对来源 |
| --- | --- | --- |
| 启动/import/配置 | module 初始化、loader、namespace/环境变化、代码和 native 依赖 | 源构造/加载清单、call/code/audit、动态库 |
| 模型/数据加载 | 路径/文件身份→read/mmap→反序列化→对象/参数/CPU materialization | OS 文件活动、输入/模型身份、Python/Torch 结果 |
| preprocessing/搬运 | raw→transform→Tensor→view/copy/device materialization | 有序 producer/use、metadata、copy/correlation |
| CEM/推理 | 区域、循环轮次、样本/RNG、distribution 更新、模型状态、score/action 依赖 | 静态控制、真实调用、ETO/算子、kernel/work |
| 环境交互/render | action consumer、环境状态版本、render 输出、CPU/native/GPU 资源 | 调用/输出、进程/线程、设备活动 |
| 结果/视频保存与结束 | 表示/编码→buffer/pipe/file→flush/close，失败/cleanup 路径 | 外部写、编码进程/线程、输出身份及生命周期 |

CPU、DRAM/pinned、GPU/显存、queues/streams/events、filesystem/storage、文件/mmap、
进程/线程/pipe、动态库/driver、渲染/编码和实际出现的其它端点都要有资源归属。
未出现的项目不能记为已覆盖：有范围内的排除依据记 NOT_APPLICABLE，否则记未观测。
不能因为本次 pusht 没走另一环境，就声称其它 LeWM 配置已被真实验证。

## 7. 第一阶段内部验收顺序

| 检查点 | 交付 | 通过条件 |
| --- | --- | --- |
| S1 设计收敛 | 本合同、现有模型差异及自动采集映射审计 | 所有必需实体/关系有职责与来源；无重叠规范事实；范围不偷换 |
| S2 原入口自动清单 | 可复现命令、源码/库/执行/资源的独立分母与缺口列表 | 不手选函数；发现预算/漏采/未尝试可见；不以清单冒充完整模型 |
| S3 自动连接 | 现有 source/call 与 provider/OS 证据接同一模型，保存可复核对应 | 必需端口/状态/资源/生命周期无未解释断点；来源/执行范围分别可查 |
| S4 LeWM 全流程验收 | 未修改目标的一次完整模型产物、复建检查及覆盖报告 | 上表逐项有实际证据，必需项 OPEN=0；不能用 supplied IR 充数 |
| S5 汇报停止 | 实体及关系讲解、自动流程、完整性依据与剩余物理细化 | S4 通过后才称第一阶段完成；停下来汇报，不自动推进化简 |

只有妨碍上述端到端路径的缺口才进入下一项实施。现有 F20 等协议计划保留为
历史待办；未证明阻塞真实模型覆盖前不继续串行扩张。保留既有测试和实现，但
测试范围按具体修改选择；不为报更大的通过数重复全仓耗时检查。

## 8. 起点事实与当前优先项

代码审查已确认：公共 inventory 默认仍是 BOUND_FRAME_V1；structured profile
只在独立 model-program 可选；现有 ETO/FX 集成设计尚不等于已接入；资源 sampler
只给 utilization/memory 抽样，不能提供文件/GPU/线程实例的完整模型。因此第一
阶段当前为 OPEN。下一项是原入口自动覆盖审计和集成，不能以新手工协议样本推进。

当前审计和执行记录统一更新 [FIRST_STAGE_MODEL_STATUS.md](FIRST_STAGE_MODEL_STATUS.md)。
