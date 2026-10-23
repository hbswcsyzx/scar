# 第一阶段交付：自动恢复整个程序及其资源

日期：2026-10-23。状态：**OPEN**。验收标准以
[FIRST_STAGE_MODEL_CONTRACT.md](FIRST_STAGE_MODEL_CONTRACT.md) 为准。
本文件统一当前执行顺序；历史 F 系列组件编号不构成串行开发队列。

## 1. 程序拆成什么

| 层次 | 实体及对应内容 | 必须连接的关系 |
| --- | --- | --- |
| 规范结构 | CodeIdentity；Operation；ValueDefinition；StateLocation；Region；ResourceDefinition/Requirement | 来源版本、有序输入/结果、状态读写、控制/异常、调用、包含、资源要求 |
| 实际执行 | Run、Process、Thread、Invocation/RegionActivation、OperationOccurrence、ValueOccurrence | 哪次执行实现哪个定义，哪个参数/结果属于哪次调用或循环访问 |
| 对象与环境 | ObjectInstance、Function/Module Environment、StateVersion | 引用对象、实际 callable、globals/defaults/cells、位置与前后态 |
| 内容与表示 | LogicalValue、ValueVersion、Provenance、Allocation、StorageRegion/View、Materialization | 来源与版本、alias/重叠、分配代次、物理副本、producer、失效及 ready |
| 执行与承载资源 | ResourceInstance、HandleBinding、ResourceWork、Completion | 使用者、设备/存储/线程/stream、handle 代次、生命周期与异步顺序 |
| 非执行事实 | Effect、Contract、Evidence、Measurement、CoverageObligation | 每个结论的依据、适用范围、未知的具体关系和成本 |

前述规范结构的五个支点并不是“只有五种记录”，也不是五种互斥行为。输入/输出
是端口角色；计算、表示、内存、搬运、状态、控制、等待、外部访问是可组合行为。
一行 `x[i] += f(y)` 会分解为多个操作和完成路径；保存 Tensor、保存视频共用表示、
buffer、资源写入与完成接口，不新造业务类型。

节点为广义操作、边为数据的图是查询投影。值必须是一等记录，才能保留唯一
producer、多 consumer 和重复参数槽。状态、控制、资源及包含有各自关系类型；
Region 可以递归展开。定义、实际发生及外部 provider 图不强行合成同一个 ID。

## 2. 如何机械获取

```text
原命令 + 原项目根 + 环境/输入范围
  → ast/symtable/dis + 编译/code witness：版本化源结构与控制
  → Python call/operand/function-environment 原档：实际调用、引用及入口
  → ETO + profiler/Kineto + dispatch 有序槽：算子、kernel/copy/sync
  → OS 独立记录：文件/设备/进程/线程/pipe/mmap 等资源
  → 共同 capture/run/process 坐标 + 准确来源对应
  → 原图组合、调用/端口/状态/物理关系连接
  → 按独立原始分母验收，保留未覆盖与未闭合项
```

复用现有编译器、profiler、schema 和 OS 证据；不执行额外 forward 猜数据边，
不存每轮 Tensor 数值，不按 LeWM 函数或包名写规则。依赖源码由实际 code 路径
需求触发，使用环境的独立 source root；不扫描整个文件系统或全部传递依赖。

## 3. 已有实际产物与边界

| 已实现并实际运行 | 实际结果 | 仍不代表什么 |
| --- | --- | --- |
| 未修改 LeWM 完整原命令采集 | episode 成功并保存视频；最新 100,438 次调用、39,796 次 dispatch | 不是干净性能基准，不代表已闭合全部依赖 |
| 联合运行坐标及资源导入 | 5 进程、252 线程；24,082 条 runtime→GPU 对应；74,574 条内存记录 | 未恢复的 OS 共享/继承、ready 与使用者仍 OPEN |
| 原档逐槽审核 | 79,592 个 marker、109,288 个 Tensor 引用槽均保留 | 保留 480 个祖先缺失、383 个未资格化叶，不能计作直接 Python→ATen 调用 |
| 版本匹配 ATen schema 适配 | 100 schemas、481 形式端口，467,756 个 Tensor 槽接形式端口 | 175,022 个无 schema；effects 均 PARTIAL；不证明纯性或逻辑内容相等 |
| 分片源码图组合与实际调用绑定 | 151文件/840原body组合及外部source attachments正规连接PASS；100,438调用中5,624 body-linked、89,864 source-only、4,950 unresolved | 外部86,702次只接原定义，不伪造body/activation；803非file、14旧源码guard false保留；不是完整 ProgramSnapshot |
| 分片源码与marker连接 | 79,592 markers/109,288原slot全部保留；79,106条有准确source definition，10,992条body/activation/namespace关联 | 50,658条外部source-only，另有6条仅invocation、480条无ancestor；retained ancestor不是direct call；状态/效果仍未闭合 |
| 原参数、返回及环境路由接回 | 817groups/100,438调用、312,812operand与16,403env events守恒；13,872入口参数occurrences、27actual/formal与27completion条件路由、5,173返回root；3,347entry的10,087env ports | 全部只是带原条件的引用/端口连接；100,523条route问题、6,694未定defaults保留；不证明内容、状态、world等价 |
| 更大范围源码归档 | 分片恢复exit0；151文件/2217定义，840原图、787 UNSUPPORTED、590 NOT_ATTEMPTED | 原256MB单JSON失败保留；新归档发布不消除未支持语言与接口缺口 |
| 外部依赖源码准入及精确增量 | 106需求文件全部有snapshot/三图；243 groups/86,702次调用有完整代码来源匹配；增量及独立审核PASS | 仅补27文件、继承原199 witnesses；803次非文件名与14次current source drift保留；不是body/effect完整性 |
| 原source/body缺口按实际调用投影 | 原817groups/100,438calls逐项守恒；74body-linked、91source-only UNSUPPORTED、260source-only NOT_ATTEMPTED | 只是已保存metadata投影；不是canonical graph重验或新语言协议支持 |
| 同次Tensor物理证据采集与导入 | 新完整LeWM episode成功；79,592 markers、109,288槽，108,682槽接物理epoch | 606槽为带provider ID但无storage pointer的空CPU Tensor；逻辑内容/ready与空表示接口仍OPEN |
| IR分块存储与查询索引 | CPU原档逐条往返PASS；源码SQLite建库/局部查询PASS；完整LeWM联合导入及实档审核PASS，2,259,781记录/195chunks | 42,767条endpoint引用未语义索引；SQLite不是第二个可写IR来源，不代表完整模型通过 |
| 原OS work到资源端点关联 | 35ports/22producer work/13pipe/3executor有限核验完成；root独立134selector及原preimage核对exit0 | 原gate汇总footer错误exit1保留，finalizer0单列；35table containers与source/state/ready仍OPEN，不是全ExecutionModel验证 |
| 实际调用协议分类 | 两Run各100,550attempts完整分类；945项目内无握手目标全8个generator codes | 不把OTHER当native，不把生成器创建当同步body进入；尚无创建对象/drive/结果的完整关联 |

详细依据分别在 `artifacts/experiments/first_stage_lewm_dispatch_20261023`、
`first_stage_joined_dispatch_20261023`、`first_stage_native_schema_20261023`、
`first_stage_dispatch_sources_20261023`、`first_stage_full_inventory_plain_20261023`、
`first_stage_full_inventory_restored_20261023`、`first_stage_dependency_sources_20261023`、
`first_stage_lewm_physical_20261023` 与 `first_stage_bundle_storage_20261023`。
所有关系保留原档 SHA、来源和未满足条件。没有新增 LeWM 变换或加速比。

## 4. 当前执行顺序与自验收节点

| 顺序 | 本次具体任务 | 自验收条件 |
| --- | --- | --- |
| A | 分片恢复、151文件/840原body组合、同272038 source绑定及marker连接均已PASS | 真实source/CP定位与namespace已核，保留所有未连接分母；没有prepare/重lower/目标重跑，不与旧54相加 |
| B，与A并行 | 自动准入实际观察到的依赖源码，保留namespace/provider/snapshot/原三图/code witness | 全部entered group仍在分母；相同编译语境的完整descriptor匹配；不以路径归属冒充代码或effect证明 |
| C，与A/B并行 | 完整LeWM物理采集/同capture native+OS导入、schema与分块归档已PASS | 108,682物理槽/37,506epochs实档核验；606空CPU槽、861 OS点process未知，逻辑版本/ready仍OPEN |
| D | 外部source attachments/common resolver与旧272038的原参数/返回/environment接入已PASS；继续同369749源码、状态及资源连接 | 106外部图恰一次/源绑定1355.11s，source→marker433.90s；20键字节码复用attempt编译0，路由2.04s；原条件与缺口仍保留 |
| E | 原命令端到端覆盖报告 | 加载→计算/环境→视频/结束全部必需项无未解释断点；范围与分母固定；S4通过后停止汇报 |

一次完整采集只在需要的新字段已共同确定后进行；不为每个小字段重复跑 LeWM。
失败原样保存，优先复用已保留证据。只验证实际剩余风险，不扩展无关测试套件。
新字段或接口实现但尚无实际运行时只能写 Implemented，不能写 Verified。

用户最新提出的大模型存储问题已纳入A：规范IR按图边界保存，原证据分块归档，
SQLite查询索引已实现并通过真实分片归档构建与局部查询：437,228实体/1,172,205
关系，构建418.65s。设计、并行、成本与权威边界见 [GRAPH_STORAGE.md](GRAPH_STORAGE.md)。
这只是现有原图的索引验收，不将缺失的模型关系判成已覆盖。

## 5. 当前最关键的断口

- 依赖源码：71,368 次旧未绑定调用来自项目边界，70,565 次对应源码实际存在；
  不是整体不可理解。现在106外部source已归档并有86,702次代码来源匹配，但尚需
  经正式共享定义resolver接入现有图。模块初始化、genexpr/lambda、延迟annotation
  仍需各自正确的定义与区域接口。
- 跨调用数据：源码 body、调用帧和 native Tensor 引用已有局部连接，但 actual/
  formal、return、function environment 及可变状态必须逐槽接入。
  已核96,481条无握手分为88,176 OTHER、40方法、7,320项目外函数与945项目内
  generator-target calls，不能把它们都按普通Python函数入口处理；详见
  [调用协议审计](CALL_PROTOCOL_FRONTIERS.md)。原GAP/问题不靠重命名消除。
- 同一次运行：已验收source composition/bindings固定272038，最新物理capture为
  369749。两组动态事实不能拼成一个完成模型。当前两项source接线原档验收完成后，
  必须把源码定义/完整compiler witness与当前运行事实分开，通过明确的跨运行版本
  检查接入369749；只允许复用相同版本的静态证明，不复用旧Invocation/ValueOccurrence。
- 源body内部：新增`first_stage_body_frontiers_20261023`只读投影确认，原项目实际有
  2,902次调用的body为UNSUPPORTED，260次为NOT_ATTEMPTED。按原理由，优先审查
  通用unpacking/heap writes、GeneratorExp、Slice及comprehension-local解析，不能
  根据业务函数名增加特例。完整分类、原locator及1.56s实测见该实验README。
- 物理表示：allocation 记录不等于 Tensor→allocation 的证明；物理副本不是
  LogicalValueVersion。host 返回不能证明 GPU ready。
- 外部资源：OS handle/事件清单仍有共享、继承、mmap、设备和完成关系未闭合；
  不能用“有文件/线程节点”代替使用者及数据依赖。

因此第一阶段仍 OPEN。其后的化简、修改指导和成本选择均不在本轮执行范围。

## 6. 本轮连接的实际验收状态

各门独立验收，不能把其中一门PASS解释成第一阶段完成：

1. `first_stage_source_attachments_20261023/attempt02`：原272038的106份依赖源码经
   共同限定定义resolver接source bindings与marker，PASS；保留historical compiler
   proof与guard差异。原attempt01在runner输入路径处退出，未运行源码连接，失败保留。
2. `first_stage_partitioned_operand_routes_20261023`首轮完成20键编译及原74body读取，
   在原issue线性去重处耗764.42s仍未完，被明确中止；SIGINT原栈确认在成员比较。
   4行保序set索引修正后，`first_stage_partitioned_operand_routes_attempt02_20261023`
   只读复用原字节码，原分母守恒、完整连接/归档PASS；routes2.04s、整体time5:26.17、
   peakRSS1,833,420KiB。不是LeWM性能A/B，不能将中止耗时算成精确目标加速比。
3. `first_stage_os_interface_work_20261023`：369749的全部原OS记录通过公共CLI导入，
   原152,564条旧FD子集外接口有work记录，新增typed work以bounded chunks保存；
   CLI exit0/PUBLISHED：4,309,455 records/681chunks，10,778,976,676decoded bytes、
   260,737,882stored bytes。audit03已exit0：全部chunk/row/count及全部work原点/身份/
   Run/process/thread/UNKNOWN wire关联核过；实际101结构分支的101submission/
   94outcome代表codec通过。全ExecutionModel语义仍OPEN；共享FD-table、VM、
   source/native effects和ready仍须独立连接。

路由的独立端口归档审核另以2.64s核全部141个report chunks和74原CP收据，并核
13,872入口参数、27+27路由和10,087env端口的原ID/namespace/端口归属；不重prepare、
compile、扫描raw或执行全report codec。失败和修正日志保留，未修改原连接产物。

实现与每次运行保存独立producer、原输入SHA、脚本、time/RSS、失败和验收报告。
新模式没有执行新LeWM episode、优化、detector/backend或全仓测试套件。
