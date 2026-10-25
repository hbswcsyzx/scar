# 第一阶段交付：自动恢复整个程序及其资源

日期：2026-10-25。状态：**OPEN**。验收标准以
[FIRST_STAGE_MODEL_CONTRACT.md](FIRST_STAGE_MODEL_CONTRACT.md) 为准。
本文件统一当前执行顺序；历史 F 系列组件编号不构成串行开发队列。

**通用入口的最新有限结果：** 原CPU G1八阶段125.90s通过时，基线为0body/271调用
未解析。后继自动依赖门为6组/265调用建立SOURCE_VERIFIED；再后继entry门6.771874s
实际正常lower1entry/28ops，相同SP5的普通source/code reader通过。260只是原调用权重，
尚未publication或新binding；统一 `source-entries` CLI 后继已在同 CPU 采集通过，
7.5152s，自动合并 project/dependency、两份只读 archive，原 9/271 与 6 候选守恒。
后继已对同一原 SP5 完成独立 qualified publication 和普通调用绑定：新 CPU 样例
260 body-linked、5 source-linked、6 unresolved，共 271 次。参数、返回、环境、
控制完成和状态五类动态接口仍各有 271 项未验证；这不是 LeWM 覆盖增量或完整执行图。
见[入口及范围](MODEL_RUN.md)与
[entry实际结果](../artifacts/experiments/source_entry_catalog_gate_20261025/RESULT.md)。
CLI 的精确资格与范围见
[实际报告](../artifacts/experiments/model_run_source_entries_gate_20261025/RESULT.md)。
出版/绑定的两次失败及最终范围见
[恢复结果](../artifacts/experiments/qualified_source_entry_binding_resume02_20261025/RESULT.md)。
该链已接入通用 `model-run --stage source-entry-bindings`，实际 CLI exit0/40.8172s，
自动完成 publication、普通 query、genuine coordinates、普通 binder 四阶段；仍保
同一 CPU 样例的 260/5/6 与上述未连接关系。见
[CLI 门](../artifacts/experiments/model_run_source_entry_bindings_gate_20261025/RESULT.md)。
同CPU后继native门已将516个metadata路径关联实际规范NativeInputRef端口，260正常
调用/2shards；3095路径中2579项仍保frontier。此资格及上述source结果均属于新CPU
样例，与旧LeWM独立；不授Python对象、内容/state或ready，也不增加其覆盖。见
[归档与规范端口关联](NATIVE_TENSOR_INPUTS.md)。
Native scalar V2 后继已在隔离树和主树真实公共路径通过，主树21.6171s：264个输入
中260个 native boxed 内容观测根、4个明确 frontier；新增 decoder 已实际加载。
这是原生层内容，不证明原 Python 类、上游 producer、Tensor 内容或 state/ready。
精确类型、来源交换反例和主树158个真实导入见
[V2 报告](../artifacts/experiments/native_scalar_union_20261025/REPORT.md)与
[主树实门](../artifacts/experiments/native_scalar_union_main_20261025/attempt01/RESULT.md)。

模块顶层也已补独立 mapping-frame 入口：真实源码自动选择原 MODULE initializer，
2 Regions/9 个入口操作及普通 v6/v5 读回通过。内部语句恢复仍为 0，REQUIRED 展开
债务和实际 namespace 绑定缺口保留；不是完整 module body。见
[模块入口及下一步](SOURCE_MODULE_ENTRY.md)。
后继同原 SP7 独立 postflight exit0，首个 import/namespace-store 接口已展开为
4 Regions/19 ops，剩余 10 句及 importer 内部仍 REQUIRED。原构造门的报告变量错误
exit1 保留，丢失测量未重建；主树同一 SP7、旧 SP6/SP5 正常读回通过，未再 lower。
见 [前缀模型](SOURCE_MODULE_IMPORT_PREFIX.md)。
后继 A 类型门已修正模块不能作为 C0 根的模型缺口：新增 core29 FRAME 根、准确
ModuleUnitSource 及单一 entry ABI，旧 source1–7 显式拒新能力。原 SP5/6/7 普通读回
兼容通过；这仅是类型/codec 基础，SP8 正文与实际 frame 对应仍未实现。见
[A 报告](../artifacts/experiments/frame_root_contract_a_20261025/REPORT.md)。

**当前可复核结果（2026-10-25）：** 完整runtime接线仍为843快照；正式静态源码已发布
到858，后继新增body尚未接回原运行。12原图普通ADD的恢复消费实际exit0/651.143247s；
原两次消费失败与更早FAILED_ENV_FREEZE均保留。新增覆盖账本
也已实际终态exit0，完整枚举2217个源码定义及100438次调用。账本发布的是原记录归属
和具体待办，不是依赖已闭合的统一图：其聚合状态仍为OPEN。637个压缩块共
126695719字节，manifest声明decoded4268542417字节；重复定位/规则字段使编码开销较大，
本轮不称其高效。独立复核全部stored receipts及12个公共查询样本通过，没有重解全账本
或证明所有行的语义。实际报告分别见
[账本门](../artifacts/experiments/modeling_scope_retained_gate_20261025/RESULT.md)及
[独立复核](../artifacts/experiments/modeling_scope_retained_review_20261025/REPORT.md)。

**最新native门已通过：** 修正SCAR重复静态图处理后，第三次完整门实际exit0，39796次
dispatch全部接入127接口/156执行分片；111189个Tensor端口中109288项有held对象资格，
1901项未定；107483项有几何资格、3706项缺口。GNU wall28:41.75，peak1091472KiB。
四份原样生产字节已应用到main，准确模型、范围和成本见
[NATIVE_CAPTURE_BATCH.md](NATIVE_CAPTURE_BATCH.md)。没有增加原预算或重新执行目标。
此门只关闭dispatch边界端口接入；全部库内部、逻辑来源、world/state及资源ready仍未闭合。

第一次全门在3182次发现native Tensor不一定有Python held见证；第二次因处理成本在20片后
主动中止。失败和原数据保留，不能把第二次的部分结果当全门通过。第三次实际代码与收据
已存档于`codex/native-scalar-model`的444baadb；没有新优化backend、变换或LeWM加速比。

**source/native有界导航也已实际通过：** 79592条source associations、39796条native
inventory各完整读一次，产出160压缩块约24MB。5个公共查询样本含body-linked、source-only、
invocation-only/零Tensor、native-only及unresolved；最后一种保持null relationship。
查询只连接保留的祖先上下文与准确native invoke/normal Return，不能当direct call、
对象同一性或data/state关系。worker104.289s、peak194844KiB；独立复核全部stored块及
一个派生关系样本通过。见[实际结果](../artifacts/experiments/source_native_context_gate_20261025/RESULT.md)
与[复核](../artifacts/experiments/source_native_context_review_20261025/REPORT.md)。旧scope义务未关闭。

通用kwargs的92/85/217 ops三个原图已按普通ADD_GRAPH正式发布到846静态快照，三项
公共reader实际PASS；原另一项后继已越过JoinedStr、停于comprehension，仍无完整图。该三图原总门因
`_compat_pickle.py`未预冻结而exit1/281.584s，状态FAILED_ENV_FREEZE。metadata
postflight exit0/0.149469s只核已保存产物，不补历史runtime字节资格或改写原exit。
原生成窗口exit1/postflight0及其失败也保留。后继65窗口的12成功原图已普通ADD至846父快照，
经新consumer完成858组合；未重lower12图或执行目标。179calls仅潜在增量，当前runtime
仍843/6699 body-linked calls。原65窗口两个FAILED及后继重试不在这12项发表中。
详见[SOURCE_CALL_MODEL.md](SOURCE_CALL_MODEL.md)。

**2026-10-25 当前实施：** 用户确认先审定模型和声明格式再完成自动接线。
[当前执行计划](FIRST_STAGE_EXECUTION_PLAN.md)对应原S1—S5；
[声明式图规范](DECLARATIVE_GRAPH_STORAGE.md)明确保留原typed IR/codec权威，
SQLite仅为可重建索引。已有native bridge不再是“完全没有producer”：历史16-prefix门
连接13个调用/4接口/27参考、41gaps与内容四表0的记录保留；最新全39796次dispatch边界
门已通过，资格和范围以上述[NATIVE_CAPTURE_BATCH.md](NATIVE_CAPTURE_BATCH.md)为准。
FD namespace临时隔离阻止无证连续性结论，闭包
producer仍待落实。843的fresh联合门已实际exit0，已取代旧842报告成为最新runtime
连接结果。提交与准确实际范围见[当前状态](FIRST_STAGE_MODEL_STATUS.md)。

**联合门现已终态（2026-10-25）：** 新843快照fresh source→dispatch→SBA实际exit0，
wall24:18.35/RSS2226076KiB。817 groups/100438 calls新读且各扫描一次，77 body groups/
6699 calls、590 source-only/88775 calls、150 unresolved/4964 calls；新增图25次、修订图
150次，未移植旧动态身份。此前“842报告仍为最新”的描述仅为启动前历史状态。
报告按chunks保存，root已独立流式复得canonical SHA并核179个参与源码。见
[实际结果](../artifacts/experiments/first_stage_source_revision_current_review_20261025/RESULT.md)。
state/content/ready、全部native及资源依赖仍未闭合，第一阶段继续OPEN。

**最新snapshot边界：** active静态源码图为858/2217、151文件；原846父快照新增12原图，
consumer实际exit0，12 ordinary-reader及公共根/lineage检查完成。原URI/namespace及严格
compiler origin保留；769 UNSUPPORTED、590 NOT_ATTEMPTED，新CP2 construction仍Unknown。
原publisher消费396.750s顺序失败和resume01的140.046s文本pool失败均保留，只改consumer，
不重publisher/lower。consumer compile/load/match0不冒称又做一次原publisher编译见证。
见[实际结果](../artifacts/experiments/source_frontend_remainder_composition_resume02_20261025/RESULT.md)。
当前完整runtime连接报告仍为已通过的843 fresh门；不能把旧842或后继静态发布数量
混入其attachments/ports。具体见[SOURCE_CALL_MODEL.md](SOURCE_CALL_MODEL.md)、
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
| 分片源码图组合与当前调用绑定 | 当前843快照fresh gate exit0；100,438调用中6,699 body-linked、88,775 source-only、4,964 unresolved | 77 body groups、590 source-only、150 unresolved；不复用旧Invocation，不是完整ProgramSnapshot |
| 分片源码与marker连接 | 79,592 markers/109,288原slot全部保留；79,106条有准确source definition，20,592条body/activation/namespace关联 | 58,514条retained source-linked，6条仅invocation、480条无ancestor；retained ancestor不是direct call；状态/效果仍未闭合 |
| 原参数、返回及环境路由接回 | 当前843门保留817groups/100,438调用、312,812operand与16,403env events；17,097入口参数occurrences、27actual/formal与27completion条件路由、6,223返回root；3,372entry的10,162env ports | 全部只是带原条件的引用/端口连接；100,523条route问题、6,744未定defaults保留；不证明内容、状态、world等价 |
| 更大范围源码归档 | 最新静态151文件/2217定义，858 active图、769 UNSUPPORTED、590 NOT_ATTEMPTED；12原图普通ADD的恢复消费651.143s/exit0，12普通reader通过 | 旧两次消费失败及更早FAILED_ENV_FREEZE保留；完整runtime仍843，179calls不加6699，两个string失败/后继重试未纳入本12ADD，lifetime和全阶段继续OPEN |
| 历史依赖源码准入与当前静态复用 | 原106文件/243groups准入保留；当前要求的105图各读一次，242groups/86,688calls接同版本static witness | 不把旧tool code或14旧calls移植当前；源码、body、effect为不同证明 |
| 原source/body缺口按实际调用投影 | 原817groups/100,438calls逐项守恒；74body-linked、91source-only UNSUPPORTED、260source-only NOT_ATTEMPTED | 只是已保存metadata投影；不是canonical graph重验或新语言协议支持 |
| 同次Tensor物理证据采集与导入 | 新完整LeWM episode成功；79,592 markers、109,288槽，108,682槽接物理epoch | 606槽为带provider ID但无storage pointer的空CPU Tensor；逻辑内容/ready与空表示接口仍OPEN |
| IR分块存储与查询索引 | CPU原档逐条往返PASS；源码SQLite建库/局部查询PASS；完整LeWM联合导入及实档审核PASS，2,259,781记录/195chunks | 42,767条endpoint引用未语义索引；SQLite不是第二个可写IR来源，不代表完整模型通过 |
| 原OS work到资源端点关联 | 35ports/22producer work/13pipe/3executor有限核验完成；root独立134selector及原preimage核对exit0 | 原gate汇总footer错误exit1保留，finalizer0单列；初始container未知由下行精化，source/state/ready仍OPEN |
| FD-table观察context精化与来源自动查找 | 原positive birth/selector证据及实际exit保留；35container→3context连续性资格已撤回，新public reader拒旧v1，无coverage builder拒绝 | 原filter漏unshare/close_range；12110区间候选不授绑定；FD/coidentity/并发状态和完整资源模型仍OPEN |
| 全部既有OS handle的实际FD来源 | 一次8档完整双SHA/lines：82,093,008raw bytes，只解析12,653行，生成12,649新FDports和4birth facts；全部12,684 handle公共codec/非endpoint字段核对通过，原35保留；exit0/wall73.74s | scope是R1已建bindings，未建继承/stdio不因此消失；新12,649个container仍Unresolved，290个creator process=None保留，OFD/offset/ready仍需独立证明 |
| 原调用到图端点统一查询 | 旧/当前Run各27argument+27completion回原GraphIndex/typed body，错误scope/ID/Run均拒绝 | 保留全部条件，callee post-world不冒充caller后态；不证明world/内容/alias等价 |
| 通用解包/Slice语言建模 | 两原静态body118/65ops经CP2/inventory正式发布与当前Run消费，分别900/150calls，prepare0/compile0 | 仅有限source/结构和引用端口验证；tuple异常pending遗漏已由隔离新guard揭示，原图保留，修正图需新producer/artifact；不是完整lifetime或effect证明 |
| 自动source front-end派工 | 全2217 bodies/817groups/100438calls入账；77 metadata candidates自动选12 bodies/4 files，12个编译见证匹配、12个真实UNSUPPORTED | 原window新增graph0；后续kwargs原图另批发布，JoinedStr/comprehension/Try/definition/import等缺口继续OPEN，不是优化拒绝 |
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
