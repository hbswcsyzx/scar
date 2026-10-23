# 第一阶段交付：自动恢复整个程序及其资源

日期：2026-10-23。状态：**OPEN**。验收标准以
[FIRST_STAGE_MODEL_CONTRACT.md](FIRST_STAGE_MODEL_CONTRACT.md) 为准。
本文件统一当前执行顺序；历史 F 系列组件编号不构成串行开发队列。

**最新snapshot边界：** 正式source revision门已通过，active源码图为843/2217，含
218ops新增图和65ops修订图；旧artifact保留，source/code验证不授完整lifetime。
当前完整runtime连接报告仍来自先前842 snapshot，尚未把新body attachments/ports
重派到同Run，不能把两份snapshot的覆盖数字相加。具体见
[SOURCE_BODY_REVISION.md](SOURCE_BODY_REVISION.md) 与
[runtime ancestor设计](SOURCE_REVISION_RUNTIME_ANCESTRY.md)。第一阶段S3/S4仍OPEN。

**2026-10-23纠正：旧FD-table连续性资格撤回。** 原capture的strace6.8只选择
`%file,%process,%memory,%desc`；该版本的`unshare`与`close_range`不属于这四类。
因此旧记录中计数0不能证明未发生；历史35个container→3context和12110个区间候选
均不能据此记为已闭合。原artifact与当次程序exit结果保留，不能用其PASS表述替代
缺失的采集覆盖前提。FD实际数值提取仍有原source回执；container关联、原OFD target
的实际coidentity及kernel availability另列未证。public reader的coverage门和以原R2
（container未知）为基础的显式FD-values-only模式现已修复并通过实际纠错门：exit0、
wall65.15s，12684真实FD端点保留且全部container未知；没有新episode或raw重扫。
依据：[strace6.8 x86_64表](https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/x86_64/syscallent.h)、
[通用表](https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/generic/syscallent-common.h)。

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
| 分片源码图组合与当前调用绑定 | 当前369749正式两body接线gate exit0；100,438调用中6,674 body-linked、88,800 source-only、4,964 unresolved | 76 body groups、591 source-only、150 unresolved；242外部groups/86,688calls只接原定义；不复用旧Invocation，不是完整ProgramSnapshot |
| 分片源码与marker连接 | 79,592 markers/109,288原slot全部保留；79,106条有准确source definition，20,592条body/activation/namespace关联 | 58,514条retained source-linked，6条仅invocation、480条无ancestor；retained ancestor不是direct call；状态/效果仍未闭合 |
| 原参数、返回及环境路由接回 | 817groups/100,438调用、312,812operand与16,403env events守恒；17,022入口参数occurrences、27actual/formal与27completion条件路由、6,223返回root；3,347entry的10,087env ports | 全部只是带原条件的引用/端口连接；100,523条route问题、6,694未定defaults保留；不证明内容、状态、world等价 |
| 更大范围源码归档 | 正式revision后151文件/2217定义，843 active图、784 UNSUPPORTED、590 NOT_ATTEMPTED；65ops旧图被准确修订、218ops新图准入 | 原256MB单JSON失败/旧artifact保留；新图已核source/code/局部tuple失败持有，未授全部normal/outer lifetime；843尚待统一runtime连接 |
| 历史依赖源码准入与当前静态复用 | 原106文件/243groups准入保留；当前要求的105图各读一次，242groups/86,688calls接同版本static witness | 不把旧tool code或14旧calls移植当前；源码、body、effect为不同证明 |
| 原source/body缺口按实际调用投影 | 原817groups/100,438calls逐项守恒；74body-linked、91source-only UNSUPPORTED、260source-only NOT_ATTEMPTED | 只是已保存metadata投影；不是canonical graph重验或新语言协议支持 |
| 同次Tensor物理证据采集与导入 | 新完整LeWM episode成功；79,592 markers、109,288槽，108,682槽接物理epoch | 606槽为带provider ID但无storage pointer的空CPU Tensor；逻辑内容/ready与空表示接口仍OPEN |
| IR分块存储与查询索引 | CPU原档逐条往返PASS；源码SQLite建库/局部查询PASS；完整LeWM联合导入及实档审核PASS，2,259,781记录/195chunks | 42,767条endpoint引用未语义索引；SQLite不是第二个可写IR来源，不代表完整模型通过 |
| 原OS work到资源端点关联 | 35ports/22producer work/13pipe/3executor有限核验完成；root独立134selector及原preimage核对exit0 | 原gate汇总footer错误exit1保留，finalizer0单列；初始container未知由下行精化，source/state/ready仍OPEN |
| FD-table观察context精化与来源自动查找 | 原positive birth/selector证据及实际exit保留；35container→3context连续性资格已撤回，新public reader拒旧v1，无coverage builder拒绝 | 原filter漏unshare/close_range；12110区间候选不授绑定；FD/coidentity/并发状态和完整资源模型仍OPEN |
| 全部既有OS handle的实际FD来源 | 一次8档完整双SHA/lines：82,093,008raw bytes，只解析12,653行，生成12,649新FDports和4birth facts；全部12,684 handle公共codec/非endpoint字段核对通过，原35保留；exit0/wall73.74s | scope是R1已建bindings，未建继承/stdio不因此消失；新12,649个container仍Unresolved，290个creator process=None保留，OFD/offset/ready仍需独立证明 |
| 原调用到图端点统一查询 | 旧/当前Run各27argument+27completion回原GraphIndex/typed body，错误scope/ID/Run均拒绝 | 保留全部条件，callee post-world不冒充caller后态；不证明world/内容/alias等价 |
| 通用解包/Slice语言建模 | 两原静态body118/65ops经CP2/inventory正式发布与当前Run消费，分别900/150calls，prepare0/compile0 | 仅有限source/结构和引用端口验证；tuple异常pending遗漏已由隔离新guard揭示，原图保留，修正图需新producer/artifact；不是完整lifetime或effect证明 |
| 自动source front-end派工 | 全2217 bodies/817groups/100438calls入账；77 metadata candidates自动选12 bodies/4 files，12个编译见证匹配、12个真实UNSUPPORTED | 本window新增graph0；kwargs/comprehension/Try/definition/import等表示缺口继续OPEN，不是优化拒绝 |
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
| D | 同369749正式两body→source→marker→SBA闭环已PASS；后继修正已知tuple failure模型，并补state/world/逻辑来源 | attempt04独立raw读取817/100438，复用准确completed source checkpoint；20-key字节码compile0，wall20:36.46；端口连接与完整依赖闭合分别验收 |
| E | 原命令端到端覆盖报告 | 加载→计算/环境→视频/结束全部必需项无未解释断点；范围与分母固定；S4通过后停止汇报 |

一次完整采集只在需要的新字段已共同确定后进行；不为每个小字段重复跑 LeWM。
失败原样保存，优先复用已保留证据。只验证实际剩余风险，不扩展无关测试套件。
新字段或接口实现但尚无实际运行时只能写 Implemented，不能写 Verified。

用户最新提出的大模型存储问题已纳入A：规范IR按图边界保存，原证据分块归档，
SQLite查询索引已实现并通过真实分片归档构建与局部查询：437,228实体/1,172,205
关系，构建418.65s。设计、并行、成本与权威边界见 [GRAPH_STORAGE.md](GRAPH_STORAGE.md)。
这只是现有原图的索引验收，不将缺失的模型关系判成已覆盖。

## 5. 当前最关键的断口

### 已审查并开始实施的下一门（2026-10-23）

**最新实际终态：** `first_stage_source_publication_current_attempt04_20261023` 已exit0，
wall20:36.46、RSS2632476KiB，报告104486803canonical bytes、SHA
`a14a15f8bc7c56288926588c5f0bb04c8f7296c96b21d9c5e7f7f7f08899f7de`，以有限chunks保存。
两个正式body的CP2/reference namespace保留原SourceProgram5实际位置，原840图及150
未改source投影保持；current body groups/calls为76/6674。完整source checkpoint在
attempt02已完成，attempt04重读当前raw并通过原公共接口重新核其scope/855codes/
817groups和完整receipt，不重跑binder；retained220guards不冒称fresh live测量。
已知tuple异常持有缺口独立保留：本门source/结构/端口通过不授lifetime资格。
后继是补已定位的通用语言表示、编译见证及native/core value连接、actual capture
coverage生成；旧条件与S3/S4继续OPEN。

以下三份设计已由主agent逐项审查，开始实施；文档中的Proposed描述设计来源，
不构成实现或验收结果。原停止条件、S3/S4和所有未解决分母保持不变。

1. [SourceProgram5正式发布](SOURCE_LANGUAGE_PUBLICATION.md)：将两个已保存且独立
   验证的真实body通过显式CP2/分片2/composition3准入，保留原图实际namespace、
   compiler witness origin、未变source/component及旧失败检查点。构造成本缺失为
   UNKNOWN，不把节点数当lowerer执行成本。正式publisher输出后才进入当前Run绑定。
2. [当前运行消费](SOURCE_BODY_RUNTIME_ADMISSION.md)：提取原单origin准入规则；
   公共orchestrator自己读一次当前raw frame/operands，并在其内部让binder/SBA共享
   owned reader结果。不能接受外部dataclass或validated=True替代原始输入校验。
   相同已保留Run的原source membership证明只按完整receipt复用，历史guard不冒称
   本次live测量；新端口/activation及计数从实际reader结果重新推导。只做一次联合
   实档门，保存producer冻结、原输入与产物SHA、实际exit、time/RSS及所有frontier。
3. [OS来源自动查找](OS_SOURCE_LOOKUP_REVIEW.md)：从既有R2端口及coordinates机械
   生成birth需求，以原R1 public selector/resolver核准确positive witness，准备
   明确新producer的证据封装再调用原FD consumer。候选位置只用于查询；未命中不
   证明不存在。零/多个pre-exec witness的旧consumer限制仍显式保留。独立实际门
   验证helper→prepare→原builder/public reader，不再手填actor或ordinal。

前两项共同负责源码/当前调用连接；第三项负责资源关联自动化。均不新增
detector/backend，不执行新LeWM，不通过存储发布或局部PASS提升整体验收状态。
下一次采集仍须等必需的新字段共同确定后统一进行。

- 依赖源码：历史106外部source已归档，当前242groups/86,688calls已通过共同resolver
  接同版本静态定义；大部分仍source-only。模块初始化、genexpr/lambda、延迟annotation
  及完整库接口仍需各自正确的定义与区域、effects和状态连接，不能把知道来源当内部展开。
- 跨调用数据：源码 body、调用帧和 native Tensor 引用已有局部连接，但 actual/
  formal、return、function environment 及可变状态必须逐槽接入。
  已核96,481条无握手分为88,176 OTHER、40方法、7,320项目外函数与945项目内
  generator-target calls，不能把它们都按普通Python函数入口处理；详见
  [调用协议审计](CALL_PROTOCOL_FRONTIERS.md)。原GAP/问题不靠重命名消除。
- 统一模型的依赖闭合：当前source/marker/SBA已与369749物理/OS同Run；只复用guard
  通过的旧静态证明。接下来仍需跨片实际state/world、逻辑值来源/写失效、控制与资源
  ready/lifetime边，不能因同Run或统一查询成功就称已形成完整ExecutionModel。
- 源body内部：新增`first_stage_body_frontiers_20261023`只读投影确认，原项目实际有
  2,902次调用的body为UNSUPPORTED，260次为NOT_ATTEMPTED。按原理由，优先审查
  通用unpacking/heap writes、GeneratorExp、Slice及comprehension-local解析，不能
  根据业务函数名增加特例。完整分类、原locator及1.56s实测见该实验README。
  两个新静态body现已作为新checkpoint/inventory正式接入；后继修正其已发现的tuple
  异常pending遗漏并补其它入口构造，保留原artifact和受限证明，不手改旧CP或调用事实。
- 物理表示：allocation 记录不等于 Tensor→allocation 的证明；物理副本不是
  LogicalValueVersion。host 返回不能证明 GPU ready。
- 外部资源：OS handle/事件清单仍有共享、继承、mmap、设备和完成关系未闭合；
  不能用“有文件/线程节点”代替使用者及数据依赖。

因此第一阶段仍 OPEN。其后的化简、修改指导和成本选择均不在本轮执行范围。
整体集成的身份、world/state边界及原档反例见
[COMPOSITE_MODEL_CONNECTION.md](COMPOSITE_MODEL_CONNECTION.md)；不能将多个局部图
按ID文本直接合并，也不能用空ProgramSnapshot冒充整个程序。

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
