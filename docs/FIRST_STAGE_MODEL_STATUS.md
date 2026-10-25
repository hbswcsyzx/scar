# 第一阶段建模：实际状态与下一项

日期：2026-10-25。**OPEN：完整 LeWM 自动建模未验收。**

当前交付与下一项统一见 [FIRST_STAGE_DELIVERY.md](FIRST_STAGE_DELIVERY.md)，
实体和完整性定义见 [合同](FIRST_STAGE_MODEL_CONTRACT.md)。以下是按日期保留的
实施记录；其中“进行中”仅指该条写入时状态，不作为当前进程存活证明。

### 2026-10-25：函数入口局部参数接线已接主树

隔离门 actual93681 exit0/38.8904s；主树普通兼容 consumer actual66781
exit0/3.5341s，566 个 typed 参数观测与原 SP5 均读回，520 个对应原正式端口，
11 次入口保留 frontier。参数按原名字/slot 查找，不按编译器与源码不同的顺序盲目 zip。
主树 core29 的兼容读回不重授原 core28 live session 的资格；该 CPU 样例不计入 LeWM。
caller actual-expression、return、environment、state 和 ready 尚未因此连接；
原五项各271的未连接记录仍保留。提交 0d5d7e10，见
[接入报告](../artifacts/experiments/callee_entry_routing_applied_20261025/REPORT.md)。

### 2026-10-25：通用 FRAME 根与旧 source 能力守卫 A 通过

Root45676 actual exit0/3.4203s，22项 typed/codec 和5项历史 wrapper 守卫核对，
原真实 SP6/7 普通只读回读通过；无新 lower/compile/target。七份原样源码已接入，
main71621 actual exit0/5.3365s，SP7/SP6/SP5 均保持原 wire；ModuleUnitSource 下移
后仍为同一 re-export class。新 core29 只表达静态 frame/code/source/ABI 关系，
不证明 actual activation/namespace/import 进入，也不代表 SP8/body 已完成。
后继继续通用 namespace 与 C0/C1 source producer；见
[A 准确报告](../artifacts/experiments/frame_root_contract_a_20261025/REPORT.md)。

### 2026-10-25：源码入口出版/绑定已接通用 CLI

Root session71666 actual exit0/40.8172s，四阶段机械完成，260 body-linked、5 source-linked、
6 unresolved，总271/9groups；原 SP5 不重新 lower，readonly1load/2matches/compile0。
全部366冻结源码前后不变。项目自有 SP5 的 publication adapter 当前仍明确 BLOCKED，
旧 success-membership 只在已验证1/1兼容情形接受，不静默筛选成功/丢失来源。
本门不是完整数据流或 LeWM 覆盖提升；参数/return/env/control/state 五类仍各271未验证。
见 [真实命令与边界](../artifacts/experiments/model_run_source_entry_bindings_gate_20261025/RESULT.md)。

### 2026-10-25：模块首个 Import 接口独立读回并接入

同原 SP7 的 postflight session73659 actual exit0/2.3181s；首句接口1、4 Regions、
19 ops，namespace 访问尝试2、存储内容证明0，准确保剩余10句及 importer REQUIRED。
原构造窗口因 runner 变量遮蔽 exit1，旧 counts/activity/runtime 清单保持 OPEN，
不倒改为 PASS。主树 session63891 actual exit0/5.2259s，原 SP7、SP6、SP5 三格式
均普通读回，无新 lower。下一完整语句模型还需解决非函数 frame/control 根主体的
真实类型缺口，不能伪造 module SourceAtom。见 [模型与边界](SOURCE_MODULE_IMPORT_PREFIX.md)。

### 2026-10-25：外部 qualified body 出版与普通调用绑定通过

Root session22541 actual exit0/36.7671s；消费同一原 SP5/publication，不重新 lower
或出版。原调用文件 536684B/585 行完整扫描，260 body-linked、5 source-linked、
6 unresolved，9 groups/271 次/271 exits，orphan0。静态 CP2 构造成本仍 UNKNOWN。
原总门因 seed metadata/当前扫描预算混用而失败；首恢复因 direct-admissions 缺少
continuation 专属字段而失败，两次均保留。独立预算和显式来源分支已修，旧 v1–3
报告及 SBA 资格不变。五类动态接口仍各 271 未验证；旧 LeWM 的 858/843/6699 不变。
见 [准确结果与剩余关系](../artifacts/experiments/qualified_source_entry_binding_resume02_20261025/RESULT.md)。

### 2026-10-25：统一 source-entries CLI 实际通过

Root session48967 actual exit0/7.5152s；自动核对原项目、依赖与两份只读 archive，
catalog 保原 9 groups/271 calls、6 candidates，正常 lower 1 body/28 ops 并完成普通读回。
项目 module 的入口缺口明确保留；没有伪造函数定义或 project fi/bi。365 冻结源码
前后不变；未重依赖准入、native/OS、目标或全 LeWM。publication/binding 仍为 0，
正式 source858/runtime843 不变，下一项是同一个原 SP5 的 qualified 独立准入与接线。
见 [CLI 实际结果](../artifacts/experiments/model_run_source_entries_gate_20261025/RESULT.md)。

### 2026-10-25：模块 mapping-frame 入口实际通过，内部仍待展开

candidate04 actual exit0/4.3214s，原源码 95 atoms/92 definitions/45 CFG nodes/56 edges
核对通过，返回 2 Regions/9 个入口操作；普通 v6 reader 与只读编译根见证通过。
主树同一 v6 及旧 v5 读回 actual exit0/4.1948s，原 worklist AST 节点全部保留。
内部语句恢复 0、REQUIRED expansion、实际 namespace/activation/state 均保留缺口；
原两次 producer 失败和主树 harness 失败均归档。source858/runtime843 不变，见
[模块入口](SOURCE_MODULE_ENTRY.md)。

### 2026-10-25：通用entry正常lower及普通读回1项通过，尚未出版

同CPU依赖门6组/265源码对应之后，entry门session67217 actualexit0/6.771874s，
保6候选/9groups/271calls；按权重选1entry，正常lower实际28ops，同原SP5的普通
STRUCTURE/source与独立code reader通过。readonly1load/2matches、compile0；未重做
raw、dependency/native/OS或prepare_source。260是权重，不是新增runtime。
live owner随进程结束失效；原SP5可再独立准入CP2未知成本，无需重复lower。
publication/binding未运行，正式858静态/843runtime和第一阶段OPEN不变。见
[结果](../artifacts/experiments/source_entry_catalog_gate_20261025/RESULT.md)及[入口](MODEL_RUN.md)。

### 2026-10-25：12原图普通ADD的恢复消费完成，source858/runtime843

root确认resume02 session20761 actual exit0/651.143247s，peak1494132KiB；12个ordinary
reader实际返回，7份归档文本按准确body snapshot singleton消费。按actual changed-body
顺序核发生，再以唯一(fi,bi)查原plan的ref/namespace；公共根/lineage及严格compiler-origin
保持。当前静态858/2217定义/151文件，769 UNSUPPORTED、590 NOT_ATTEMPTED；CP2新增
construction仍Unknown，header unknown18/totalNone，不用图大小代替成本。

原publisher gate20197在保存12ADD后exit1/396.750s（active追加顺序），resume01 gate18536
exit1/140.046s（多文件pool违反单module exact-cover）均保留。只修consumer、消费原
publication，不重publisher/lower12图；新consumer HEAD3423c9bf与原producer字节分列，
CodeWitness compile/load/match均0。没有新raw/binder/target或额外外部typed-reader循环。

完整runtime仍843/6699 body-linked calls；179次是潜在可接权重，不直接相加。原65窗口
两项FAILED及其后续重试没有纳入本12ADD，历史记录不倒改。组合根17MB及12原program
local-only，Git小metadata不能当自包含模型包。总I/O计费、scope债务、collector assumption、
内容/state/ready/lifetime与第一阶段继续OPEN。见
[实际结果](../artifacts/experiments/source_frontend_remainder_composition_resume02_20261025/RESULT.md)
及[准确收据](../artifacts/experiments/source_frontend_remainder_composition_resume02_20261025/terminal-receipt.json)。

### 2026-10-25：原生输入metadata的新保留路径实际回读通过

新opt-in profile在同一次owned profiler DFS保留TorchOp输入metadata。独立CPU实验43行/
22块已完整回读；原probe预期异常类型假设错误导致exit1保留，离线postflight exit0，
没有第二采集。三文件原样从3b16c0d2接入。它尚未纳入普通membership/ETO端口绑定，
不授旧1901端口或逻辑内容/ready资格；见[NATIVE_TENSOR_INPUTS.md](NATIVE_TENSOR_INPUTS.md)。

### 2026-10-25：65项普通函数窗口全部实际处理

root确认exit0，outer174.766s/worker144.349s；65终态为12成功、51不支持、2失败，
分别关联原运行179/1501/33次调用。12图共1111 graph ops；该窗口结束时未计入source846/runtime843，
后继普通ADD消费结果见上方source858条目，调用权重仍不作为runtime增量。
两个失败是字符串校验器漏收Call结果hold，窄修已应用，原失败保留；12图不重lower。
CodeWitness compile0；真实rchar430228980不包含gzip解码，总I/O计费仍OPEN。
完整结果及下一实际frontier见
[批次报告](../artifacts/experiments/source_frontend_remainder_attempt02_20261025/RESULT.md)。

### 2026-10-25：五类采集器注册及保存CPU运行绑定通过

可选collector来源profile已接入。唯一CPU采集CLI exit0/26.105s；原总门在schema标签
映射处失败，修正consumer后离线postflight exit0/1.570s，坐标与原保存字节完全相等，
issuer-generation反例明确拒绝。六文件从222b32aa接入；旧LeWM scope不升级，持续无篡改、
PID birth join、内容/state/ready与第一阶段仍OPEN。详见
[来源证据](COLLECTOR_EXECUTION_WITNESS.md)。

### 2026-10-25：字符串通用恢复越过原前沿，完整body仍未返回

真实单body门exit0/9.882s，partial construction634 ops，下一实际缺口为comprehension
作用域接口；没有返回canonical graph。33ops fixture的局部字符串验证通过不替代真实
body完整图的AST/compiler/pending验证。准确四文件已从817481c7接入主树；没有新body、
全运行接线、优化或加速结论。见[SOURCE_CALL_MODEL.md](SOURCE_CALL_MODEL.md)。

### 2026-10-25：kwargs三原图已发布；原总门FAILED_ENV_FREEZE

普通ADD_GRAPH发布已在原843父快照上保存92/85/217 ops三个原图，新正式静态快照为
846 active bodies/2217定义/151文件，781 UNSUPPORTED、590 NOT_ATTEMPTED。原artifact
URI与namespace保留、parent准确指843，严格compiler-origin保留，新CP2 construction cost仍Unknown。
publisher/composer完成，三个公共结构/AST/CodeWitness reader实际逐项PASS；没有重lower、
compile或执行目标。

原门actual exit1/281.584s/peak1246608KiB，最后participant审计先报告标准库
`_compat_pickle.py`未预冻结，状态为FAILED_ENV_FREEZE。原freeze、失败和exit不改；
完整历史runtime清单及字节证明仍OPEN，不能以事后新hash追认为执行期证据。
最小metadata postflight actual exit0/0.149469s，stored29214490B、decoded metadata326576B、
核383文件，只查小headers/引用/原三PASS日志/源码freeze及stored SHA，没有重新解
composition或三图，也未重跑publisher/composer。它通过不把原总门改称PASS。

完整runtime仍绑定843快照；旧6699次body-linked调用及source/native导航根未自动升级。
后续汇总增量接线，保JoinedStr、完整cleanup/outer lifetime、内容/state/ready、旧scope
义务和collector provenance assumption，第一阶段仍OPEN。详见
[kwargs模型](SOURCE_CALL_MODEL.md)、[实际边界](../artifacts/experiments/source_call_kwargs_publication_20261025/postflight01/RESULT.md)
及[准确receipt](../artifacts/experiments/source_call_kwargs_publication_20261025/postflight01/receipt.json)。

### 2026-10-25：source/native有限组合查询实档通过

新导航门实际exit0/outer104.434s，79592条source associations与40个native inventory
chunks/39796条sequence各完整读一次。输出160压缩块24179311B，5个公共样本通过，
其中seq4保CONTEXT_UNRESOLVED和null关系；其它只声明RETAINED_SOURCE_CONTEXT。
每个样本读取1 index+2 data+1原EEG chunk，原association/invocation流不重扫。
准确source definition/namespace及native invoke/normal Return保留各自限定引用。

独立审查核全部160 stored块、五报告输入/导航/旧scope绑定，以及一个source派生chunk
的双phase行SHA/ordinal/namespace；没有验证全部39796跨片语义。historical collector
执行源码缺证assumption、logical/state/ready及旧scope欠账全部保留。导航不是自包含包，
clone查询仍需原metadata及命中native模型/EEG依赖，不能隐式迁移原URI。详见
[结果](../artifacts/experiments/source_native_context_gate_20261025/RESULT.md)及
[复核](../artifacts/experiments/source_native_context_review_20261025/REPORT.md)。

### 2026-10-25：全39796次dispatch端口门终态通过

root持有的第三次完整门已确认exit0：127静态接口、156执行分片、39796次dispatch全部
接入，没有dispatch frontier；111189个Tensor端口，held对象资格109288、未定1901，
几何资格107483、缺口3706。9项native-only/producer反例及fresh错序候选均实际拒绝，
包括真prepared路径，不能用scope hash替代独立ABI检查。

runner1720.893s、GNU28:41.75、peak1091472KiB，private index3973341184B、final report前
published4337031496B。原1800s/4GB index/2GiB RSS/8GB输出预算未提高。没有新LeWM
episode；这是原真实运行的离线接入，不是干净benchmark或目标加速。

原样四份生产字节已应用main，其他265个冻结依赖一致。源码与实际小型交付在隔离分支
444baadb；模型关系和使用边界见[NATIVE_CAPTURE_BATCH.md](NATIVE_CAPTURE_BATCH.md)。
全部native内部、实现代码身份、logical value/state/alias/ready和跨片依赖仍OPEN。
source/native的有界retained-context查询与通用kwargs协议正各自进入有限实档验收；
第一阶段整体未完成，不进入优化。

### 2026-10-25：覆盖账本完整source/call归属门已通过，整体仍OPEN

公共v2 producer已完整读取保留的2217个源码定义和100438条调用，生成102655个成员、
102661项必需义务（另六项为未枚举领域的集合欠账）。实际exit0，worker wall694.39s、
SELF peak114576KiB；637个压缩块stored126695719B、manifest声明decoded4268542417B。
这是计入重复来源/规则字段后的真实成本，不据压缩比宣称查询或建模高效。

独立审查核全部637个stored chunk及准确根SHA；十个原公共查询、LOWERED和UNSUPPORTED
各一个原源码样本通过。未重解全量4.27GB或验证每行依赖，不能将样本说成全语义验证。
record/transport2、六输入根和四producer源码绑定ScopeRevision。全部依赖、内部展开、
运行语义仍OPEN；源码构造、dispatch/native、OS、physical等六域继续单列未访欠账。
见[实际门](../artifacts/experiments/modeling_scope_retained_gate_20261025/RESULT.md)和
[独立审查](../artifacts/experiments/modeling_scope_retained_review_20261025/REPORT.md)。

原生全量门首次实际失败于第3182次调用：有原生Tensor端口却无Python held Tensor
见证；不能把两种身份强行绑定或伪造对象。V2将端口/对象/几何/内容四项资格分开，
保留准确原始位置和未证身份。第二次完整门已完成全39796次枚举/127接口和20分片，
root因每片重复静态图处理的成本主动中止，exit130；仅5120次调用的分片通过，余34676
未构建，不能称全域PASS或frontier。有限产物和实际停止原因在31198ff9存档；后继先修
SCAR处理成本，保动态验证和原预算，再另跑完整门。
未运行新LeWM episode、变换、backend或性能A/B。接下来仍补原图之间的实际连接，
不能以这份覆盖账本替代完整ProgramModel。

### 2026-10-25：843快照与完整保留运行的fresh统一接线通过

`first_stage_source_revision_current_20261025` 已实际exit0，GNU wall24:18.35、
maxRSS2226076KiB。与旧842门分开：本门新读原raw，source binder实际1次、旧checkpoint
resume0；frame/operand/environment各扫描1次，原855 codes、817 groups、100438
entries=exits、312812 operands、16403 environment events均保留。

当前843快照的77 body groups/6699 calls，590 source-only groups/88775 calls，
150 unresolved groups/4964 calls。新增218ops图接25次调用，修订65ops图接150次，
其余准确active namespaces接6524次。79592 markers/109288 slots守恒；retained
body/source/invocation关联分别20592/58514/6，480未解；它们不是direct-call证明。

入口参数17097；27 argument+27 completion条件路由、6223返回root；3372 entry的
10162环境ports。100523 route issues、6744未定defaults等原缺口保留。原坏65只作
历史accounting，不被重新typed准入；所有新formal/return/environment引用从新snapshot
重派。ANCESTRY_V2 private factory、安装及公共消费在本门实际运行，原compiler inventory
严格相等，ancestor depth2且两个parent各parse1次；仅复用静态membership/原guard，
不复用旧Invocation/activation，原guard也不冒称fresh live源码测量。

CodeWitness compile0、load20、descriptor matches227，prepare/lower/publish/target均0。
SBA报告104798011 canonical bytes、SHA
`2f8d567e658eb23a77272975ff2e0c4dd7e6179b09485de9f3be977d9e363d4a`，
按有限chunks保存。root独立流式复原全部canonical字节并匹配SHA，核179实际参与源码
及归档copy，exit0/4.35s；没有重新读raw、解源码图或运行binder。

完整结果见[联合门报告](../artifacts/experiments/first_stage_source_revision_current_review_20261025/RESULT.md)。
此门是实际source/引用端口连接，不是内容、world/state、alias、ready或完整lifetime闭合。
全dispatch桥接和覆盖账本在隔离工作树实施；S3/S4及第一阶段整体继续OPEN。

### 2026-10-25：恢复后固定声明/存储职责，提交已冻结跨层连接

声明式规范图、归档编码和查询索引分别承担职责。现有 ProgramGraph/
ExecutionModel/ValueGraph/EvidenceGraph 与公共 codec 保留为事实来源；SQLite
只是可删除重建的索引，不决定实体或关系，也不是新的必需主存储。具体设计见
[声明式存储](DECLARATIVE_GRAPH_STORAGE.md)，当前 S1—S5 的执行和自行验收见
[执行计划](FIRST_STAGE_EXECUTION_PLAN.md)。旧组件分母中把自动建图推到后续的范围
已明确为历史，不能缩小当前完整建模要求。

恢复后核对原 LeWM HEAD/工作区仍未改。三个冻结单元已分别审查并提交：

- 366dd09c：精确 source membership ancestor；实际 depth2 查询、重复查询及
  错祖先拒绝已验，原140 artifact receipt与两源码逐字匹配。没有重读raw或构造
  private proof factory；843快照的统一 current-source/dispatch/SBA 门尚待执行。
- 1e262f80：FD namespace 临时隔离；selection coverage 合格不能代替连续性。
  实际负例门 exit0/0.72s，无raw打开或资源创建；FD数值独立保留。资格producer
  尚未实现，不能把安全拒绝写成资源模型已完成。
- 0678db92：native/reference→core bridge及独立ABI顺序检查。最终真实门为
  attempt03，exit0/19.26s、GNU maxRSS660880KiB；16个选中dispatch中13个ATen调用、
  4静态接口、27个Tensor参考denotation、0validation issues、41gaps。逻辑内容四表
  仍0，完整state/alias/ready未闭合。其余39780个dispatch尚未访问，不算已覆盖。

native交付独立只读审计复得新seal的错排候选，确认真实拒绝是NativePortOrderError
而非旧scope hash；最终107项收据、六源码及三轮producer匹配。112文件交付含
4个新审计小文件；旧失败、attempt02缺独立顺序证明和三条历史可变路径差异保留，
没有改写旧收据。复核未重跑目标或gate，不能当作又一次实际运行。

新843 source snapshot 的 fresh raw 联合绑定已实际启动，root持有session40820，
Python PID1193139；原坐标公共校验及owned raw读取已通过，正在fresh source binder。
此为启动时状态，终态另记，不凭此文字推断进程仍活着。未执行新LeWM/GPU或A/B；
S3/S4仍OPEN。

并行[实现审计](DECLARATIVE_MODEL_AUDIT.md)已完成21组实体映射及564个原dataclass
字段清单；root独立核316项源/文档receipt无差异。这是代码审查，不是564种程序
行为均已自动恢复。审计确认统一AnalysisScope/CoverageObligation持久化账本仍缺，
现有source/provider覆盖条目不能替代它；现有typed格式优先保留，补自动producer。
[全dispatch方案](NATIVE_CAPTURE_BATCH_PLAN.md)也已完成：一次owned来源获取和原档
索引、全静态catalog、共享Snapshot及有界execution shards。该方案尚未实测；
后继代码在独立工作树实现，主联合门参与的producer保持原freeze。

### 2026-10-23：新模型快照正式新增218ops并修订65ops

通用显式body revision已实际通过一门：exact parent/checkpoint/namespace/digest CAS、
旧body ACCOUNTING_ONLY统计、新body正常source/code准入、active接口/structured引用
保序替换及全部计数减旧加新。旧ADD API仍拒绝覆盖已有graph，未知capability不静默接受。

`first_stage_source_body_revision_20261023` actual exit0，wall153.76s/RSS994884KiB。
正式source snapshot现在843 active graph bodies、151 files/2217 static bodies；
core ops66513、values106442，known construction99929、unknown3/totalNone；
checkpoint positions1627不变。修订不是又执行一次lowerer，图大小不当构造成本。
compile0/load2/matches4、prepare0/lower0/raw0/target0，stale expectation实际拒绝。
原坏65ops图只用于核过receipt的raw/core计数，不再授它新的source/lifetime合法性；
新65/218图通过正常公共reader，原artifact/store全字节不变。参见
[SOURCE_BODY_REVISION.md](SOURCE_BODY_REVISION.md)。

新source快照尚未重派同Run的body attachments/activations/ports。先前842快照的
6674 body-linked calls仍是先前冻结门结果，不能混入843当作新测量。后继采用正规
ancestor receipt链仅复用原静态source membership，保持compiler origin严格等式；
当前raw必须独立读取，新body引用从新快照派生，禁止resume旧source checkpoint。
整体state/content/ready与lifetime义务保持，S3/S4仍OPEN。

### 2026-10-23：通用OS实际launch/归档/selection资格端到端通过

`scar trace --os-capture-root ...` 已实现工具自己拥有strace Popen启动边界、native intent/
双nonce关联、closed launch receipt、原lossless归档及一次最终coordinate/profile发布。
旧capture无新声明时不添加字段或授资格，原Run seed不引入新profile hash循环。

首个自有CPU门在Torch import时因原profile钩子的逐事件getpid日志触发64MB预算：CLI241、
owned provider-15，原失败和64MB本机raw保持，未发profile或冒称目标成功。只把无记录
动作的事件/不在范围的帧过滤提前，真正动作仍核实时PID；全局hook/monitoring mutation
检测、原return清理、fork防混和完整calls/operands范围保留，没有加入较小采集profile。
一个必要guard行为门核项目外1000calls无PID查询、正常/异常return、项目外hook修改及
真实fork防混；exit0。它不证明完整调用协议或目标加速。

第二独立CPU门保持同64MB/120s，CLI与runner均exit0、wall27.86s。11档归档共8344309
decoded/916903 stored bytes；4个OS档81185行，81180 parsed interfaces、其中70190条
在旧FD profile外，parser frontier0；unshare/close_range各实际1次。公共coverage2回读
及错误nonce必要拒绝通过。GNU进程树peakRSS805588KiB与runner自身130752KiB分别记录。
此门没有新LeWM episode、GPU/physical exporter或完整ExecutionModel验收。

证明范围是实际启动/版本/selection与原字节绑定，**observation completeness仍UNKNOWN**，
不能由正常exit或roundtrip推出无丢失、FD-table连续性、完整effect或ready。相关后继
资源门仍需独立审查，第一阶段S3/S4继续OPEN。入口与所有原失败、准确SHA、范围见
[OS_CAPTURE_LAUNCH.md](OS_CAPTURE_LAUNCH.md)；大型失败raw不提交Git，小回执与样本保留。

### 2026-10-23：tuple异常引用修正及一个自动选中body恢复

通用tuple key前端现可从原SG唯一Tuple/operator/output-slot恢复缺旧computational
overlay的原children，准确CodeWitness区分LOAD_CONST和BUILD_TUPLE。异常路径改为
success-only transfer，独立focused guard沿CFG/FRAME_HOLD/FRAME_EXIT验证有序引用；
未知中间primitive与control join仍保留frontier，不授全lifetime或纯性。

两body实档window exit0、wall26.71s：原65ops图在新producer下修正并公共回读，另一
原自动队列body在新地址guard失败，原FAILED_RETAINED与UNKNOWN construction cost保留。
只补通用heap-source恢复INDEX的PARTIAL读地址和原receiver0/key1端口顺序后，新独立
attempt仅重跑失败body，exit0、wall17.49s，恢复218ops图。两个SG-only tuple key源码/
编译见证/ordered Uses/raise element retention通过，25个其余lifetime frontiers仍在。
两门compile0/prepare0/target0，旧graph和20-key archive全字节不变。

新图准确SHA与原失败见 [SOURCE_FRONTEND_NEXT_PROTOCOL.md](SOURCE_FRONTEND_NEXT_PROTOCOL.md)。
这两份新artifact尚未正式替换842 snapshot中的旧引用；当前旧snapshot在新strict guard
下仍有已知失效body，不能因历史冻结producer的PASS称其现已完整合法。后继需显式原
namespace/parent snapshot绑定的body revision，并在批次完成后统一重新连接当前调用。
第一阶段S3/S4仍OPEN，没有新增优化backend、变换或目标加速结论。

### 2026-10-23：真实view几何接线修正与native/core内容断口

发现physical adapter原样保存`torch.strided`，而规范StorageRegion的bounds/overlap只认
`strided`。现仅在准确provider profile/revision下转换这一拼写，保原provider_layout及
原physical/ETO来源；其它layout不升级为strided。唯一有界实档门exit0，wall1.08s、
RSS76292KiB：4条原Region复用原AllocationID/epoch2的640B receipt，得到full[0,640)、
row0[0,40)、scalar[0,4)、row1[40,80)；overlap与同allocation两row的disjoint均核过。
旧artifact未改，没有新Allocation或内容/ready资格。此门不重跑完整importer、不宣称
所有108682物理槽已用新producer重建，详见[TENSOR_LAYOUT_ADMISSION.md](TENSOR_LAYOUT_ADMISSION.md)。

有界原档与源码审计另定位内容表为何为0：native_import只写provider引用，schema只写
PARTIAL形式端口，physical importer只写Allocation/Region；还没有自动构造实际native
端口到已有core NativeBoundary/ValueOccurrence/UseOccurrence的桥。仅新增nonce IDs或
用token/形状串LogicalValue会绕过而非补齐这一缺口。下一项须沿准确owned dispatch、
native operator/schema和有序slot接回原core，再明确内容版本/外写/ready的真实缺字段。
见[NATIVE_VALUE_CHAIN_AUDIT.md](NATIVE_VALUE_CHAIN_AUDIT.md)；未新增一套IR或优化器。

### 2026-10-23：正式两body到当前运行的完整连接门已通过

`first_stage_source_publication_current_attempt04_20261023` 实际exit0，
wall20:36.46、RSS2632476KiB；当前raw独立读取855 codes、817 groups、100438 entries/
exits、312812 operands，environment读取一次共16403 events。准确复用attempt02已完成
source checkpoint，重新绑定owned scan和公共source accessor，未重跑binder；不是接受
调用方提供的validated布尔值。retained source guards没有冒称fresh live测量。

原840图namespace全部保留，两新body正式成为842中的成员，分别连接900与150次调用；
当前body groups/calls为76/6674，source-only591/88800，unresolved150/4964。
79592 marker/109288 slot守恒，20592 body-linked、58514 source-linked、6仅invocation、
480无ancestor；仍是retained ancestry，不是direct Python→ATen调用证据。
入口参数17022、returns6223，27+27条件路由、3347 entry的10087环境ports及100523
route issues保留。compile0/prepare0/target0；canonical report104486803 bytes，按有限
chunks保存，SHA `a14a15f8bc7c56288926588c5f0bb04c8f7296c96b21d9c5e7f7f7f08899f7de`。

本门只验证原source/结构、scope及引用端口连接；tuple异常引用缺口已由隔离新guard
揭示，未授予原v5图完整lifetime证明。状态、内容版本/来源与资源ready继续OPEN。
前轮静态audit字段错误、CP2字段错误及自有低吞吐任务中断均保留；没有抹去失败或
将离线时间称作LeWM加速。下一步按已知通用表示与跨层值连接断口继续建模。

### 2026-10-23：自动源码恢复队列的真实派工与缺口定位

通用 `source_frontend_worklist.py` 已通过一次真实自动规划/worker门：原2217 bodies、
817 groups/100438 calls全部保留；正式两body发布后的842原图不因本门改变。
按实际source/context/compile key生成77 metadata candidates/1752当前calls，
自动派工12 bodies/4 files，无业务名字规则。12次独立完整CodeType/source见证均匹配，
但12次实际lowerer都返回UNSUPPORTED；program_paths为空，不伪造成功graph。

首阻塞包括固定tuple index-key的来源适配、kwargs expansion、comprehension、combined
slice、Try、嵌套FunctionDef及ImportFrom。它们是程序表示缺口，不是优化拒绝。
真实发射1163 operations；源码context/AST/symtable各file一次，compile0、target0，
wall41.39s/RSS610876KiB。完整终态、原返回与未派工项保留，见
[自动队列与历史计数纠正](SOURCE_FRONTEND_WORKLIST.md)。没有开始化简或性能A/B。

### 2026-10-23：撤回旧FD表连续性资格，保留真实FD回执

发现并核实原capture profile缺口：run.sh只启用strace6.8的四类filter，`unshare`和
`close_range`在该版syscall表的分类flags均为0，不被四类选择。因此先前以原记录
零计数作为“没有table切换”的前提不成立。旧35 container→3context、拟议12110
关联的连续性结论降为条件声明，当前不能计作已闭合；不能仅因typed/FK通过维持
其资源身份/availability资格。原运行与artifact按原字节保留，纠正报告单列。

12,684个handle的真实FD scalar/selector提取仍有准确source回执，原字段不变、原
targets数守恒的核对也仍是事实；它们不证明原OFD targets的实际coidentity或生命周期。
尤其四类filter还可能漏过network类FD producer，不能把既有handle集合当所有FD全集。
后继reader将对不具备独立coverage证据的连续性fail-closed，并以public R2的未知
container形成显式FD_VALUES_ONLY_R2模式，剥离原35条未证container结论。

完整程序建模继续OPEN；source与FD数值结果不因这个缺口一概丢弃，依赖该缺失前提的
关系必须分别撤回。没有实际优化/目标改写，因此不存在已应用变换需要回滚的问题。

纠错现已实际验收：显式schema2 `FD_VALUES_ONLY_R2` 门exit0、wall65.15s、
RSS277160KiB。全部12684个handle经public codec和非endpoint字段核对；35个原端点
准确恢复为public R2，12649个FD端口的真实selector逐行核对，全部container均为
Unresolved。原3个payload chunks通过准确byte校验后hardlink复用，本进程audit hook
禁止全部原archive数据路径，实际raw reopens=0；不重扫82MB日志。
旧context v1 reader和无coverage builder各一次实际拒绝，防止原结论被静默重新授予。
OFD/coidentity/end及完整资源生命周期仍未重证，原target字段守恒不授这些资格。
确切来源与余项见 [OS_CAPTURE_COVERAGE.md](OS_CAPTURE_COVERAGE.md)；新header为
199812bytes、SHA `bb0b7b16d503ea09dc95fe728c8826c302b3f8c86c79243a34070aad936ea624`。

### 2026-10-23：全部既有OS handle获得真实FD来源

通用`os_fd_source_projection.py`唯一实际gate exit0，wall73.74s/RSS296,208KiB。
工具从原完整handles表自动生成需求，8个原档共82,093,008raw bytes/1,035,968行及
8,624,059compressed bytes全部核SHA/长度/行数；每compressed文件一次物理读取、
一次流式解压。仅12,653条准确source行解析，产生12,649个FDports和4birth facts，
FD提取frontier0；不重建百万Work。提取合同实测12,648 OPEN_RETURN、1 DUP_RETURN，
后者保原OFD target而非创建另一个资源。

全部12,684 same-ID handles经公开core codec及原/新非endpoint逐字段核对；旧35个
ProviderHandle完整保留，新12,649个endpoint的selector指向新provider真实JSONL
`/record/fd`。原/新OFD targets同为12,683，25selected Work/38access未改；290个
creator point.process=None保留。全部新selector以2chunk有序批量核，另核每chunk
实际combined resolver代表。producer读取时核真实raw，reader不冒称重做raw提取。

新provider manifest197,638bytes，SHA256
`0ebb957e8b4fd86eafefbce6f854ff045627cface9523f06766aabab8b2e8723`。
实际98个SCAR imports与12关键源SHA前后一致。详见[实现与实测](OS_FD_SOURCE_PROJECTION.md)。
耗时是有并行负载的离线验收成本，没有LeWM A/B或加速声明。

已建FD值来源不等于所有资源闭合：新12,649个container仍Unresolved，未建继承/stdio、
OFD内容/offset、跨exec身份、mmap/设备对应及ready/lifetime继续OPEN。完整模型未通过。

### 2026-10-23：移除FD观察context路径的人工birth选择

新增通用`os_source_lookup.py`，从原R2的35端口、exact archive和coordinates机械生成
3groups/2birth需求，无actor/TID/ordinal入参。2次public原R1查询准确命中，收费
31,998,744 decoded bytes；唯一required pre-exec witness以明确AUTOMATIC_SOURCE_LOOKUP
producer发布，原consumer随后独立复核。唯一实际gate exit0，wall17.54s、RSS122,308KiB：
35containers/3contexts、13pipe对、25selected work/38access保持，选中typed records与旧门
完全一致。root另用stdlib核2原chunk双SHA/原row、source归档映射及child结果，exit0，
0.263s；没有重跑importer或完整模型codec。

此门仅关闭这35个端口context连接的人工选择断口。原ancestor无自身birth坐标仍列
frontier；未声称source全局排序/唯一性/未命中即不存在，旧consumer零/多pre-exec
witness限制保留。全部legacy handles、状态/offset/ready与全ExecutionModel仍OPEN。
见[实现与实测](OS_SOURCE_LOOKUP.md)，实际producer/输入/输出/exit保存在
`first_stage_os_source_lookup_20261023`。没有新target、compile、detector/backend或优化。

### 2026-10-23：同一次运行的正式接线、端点查询与语言/资源局部闭合

当前369749原档的source→production marker→SBA完整gate已actual exit0：817groups、
100,438entries=exits、855codes独立扫描；667groups/95,474calls接原定义，150groups/
4,964calls未解析。220个当前source fingerprint guard全匹配，1个新code实际14次
调用未找到历史static witness，未借旧14次权重。105个依赖图各读一次，242组/
86,688次外部调用为source-only；marker/SBA复用该resolver未重复读依赖图，最后
selected完整source-view查询另读1个小图单列。无prepare/compile。

同Run全部79,592marker/109,288slot保留：BODY10,992、SOURCE68,114、INV_ONLY6、
UNRESOLVED480；source definition79,106、external source-only50,658。它们仍为retained
ancestry/direct=false。SBA独立逐code权重与source全相等，312,812operand、16,403env；
13,872入口参数、27+27条件路由、5,173returns，3,347entries接10,087env ports。
只读20-keyCodeWitness load20、完整descriptor match224、compile0/current source read0。
脚本2068.11s、wall2071.73s、RSS2,134,064KiB；141输出chunk另核stored/decoded SHA/
rows。旧source/资源Run混用的断口在此范围关闭，state/world/内容/ready仍OPEN。

新增`CallEndpointQueries`复用原GraphIndex键、InventoryPartitions及原条件路由，
分别对旧272038与新369749各27argument+27completion回原graph端点通过，4种错误
scope/ID/Run均拒绝；脚本分别2.87s/2.90s。不创建producer，不把callee post-world
说成caller后态，不把端点可导航说成等价。见CALL_ENDPOINT_QUERIES.md。

通用source-language能力在同一份原source的两真实body实测：body11恢复118ops/
UNPACK6；body26在补精确INDEX READ-PARTIAL地址验证后恢复65ops、1BUILD_SLICE和
1CodeConstantReference。两次原失败完整保留（地址集合接口缺失、局部导入遮蔽）；
attempt03实际exit0/wall38.21s、compile0/prepare0，仅补body26并回读旧body11结构。
SourceProgram5无liveCodeType可做STRUCTURE读取但不授源码/常量证明；完整source/code
验证要求独立原CodeWitness。**两图尚未通过CP2/inventory正式接当前Run，不能抬高
当前body覆盖数。**旧wrapper拒新capability；后继正式集成是下一必需项。

资源的35个container已通过隔离FD-table adapter实际精化为3个观察context：builder→
public read→全部35typed handle、3ResourceInstance/FK通过；13pipe两端不同原OFD、
同container，25selected Work/38access及其它字段不变，wall13.67s。完整补集252档/
9.26MB只读投影给连续性证据；ImportedAt不声明新物理allocation。原total12,683与
selected35范围明确保留。childbirth selector仍由checked proof输入提供，上游自动
发现与全ExecutionModel语义均OPEN，不能据此宣称端到端全自动完成。

第一阶段仍OPEN：后续按已验证原图接线，补新body正式发布/消费、自动证明需求、
调用阶段/状态/world与逻辑来源及其它资源生命周期。没有新增detector/backend或变换。

### 2026-10-23：已观察资源端点接线与调用协议边界核对

R2.1已实现ProviderRecordSelector/ProviderHandle/ProviderResourceAccess及原work的
provider executor分支。selector是已发布JSONL的证据定位，资源身份仍取原target；
核心不把全部provider handle误限为POSIX整数。FD整数域检查留在OS adapter。
ProgramGraph v28/execution v9显式隔离新能力，旧wire含义保持。

当前369749原R1上的35个producer ports、22个producer work、13对pipe、3个实际
executor已经完成有限端点/codec检查，delta443,446bytes；35个FD-table container
仍Unresolved。原gate在全部端点检查与6个旧版本拒绝检查后，metrics footer发生
变量遮蔽错误exit1；独立finalizer从已写proofs复核后exit0，没有重复扫百万表。
root另以stdlib独立核134 selectors的selected chunk两层SHA/line/ordinal/preimage及
所有上述端点，3.08s、RSS98,328KiB、exit0。不是完整ExecutionModel语义通过；共享
FD、table epoch、source/state、VM、ready仍OPEN。详见OS_RESOURCE_ASSOCIATIONS_R2.md。

另完成两个Run的完整operand原档分类（各312,812events/100,550attempts）：原路由
96,481条HANDSHAKE_BOUNDARY实际分成88,176 OTHER、40 EXACT_METHOD、7,320项目外
exact function、945项目内generator-target calls；后者8个code全有CO_GENERATOR。
这是原数据揭示的调用阶段建模问题：generator创建与body drive不能套同步入口。
没有据flags推断创建成功/对象/参数，也不把OTHER统称native。逐code与完整收据见
CALL_PROTOCOL_FRONTIERS.md。旧GAP/路由报告未改写，完整阶段不因分类而通过。

当前Run静态源码复用的五文件实现已AST冻结，尚未实档验收；通用解包/Slice/
词法作用域仍在实现。下一步按同一producer快照做369749 source→marker→参数/
返回/environment实档连接，再补明确的call协议和资源状态断口。未运行新目标、
优化或性能A/B；原LeWM与原scar checkout再次实查git status干净。

### 2026-10-23：外部源码正式接线与参数/返回/环境路由实档验收

原272038 capture的source attachments公共resolver连接已PASS。原composition文档及
canonical SHA不变；106个依赖三图在绑定阶段各读一次，243组/86,702次调用接原限定
源码定义。全部817groups/100,438entries=exits/855codes保留：5,624 body-linked、
89,864 source-only、4,950 unresolved。803非file调用与14旧tool源码current guard
false调用均保留；后者只授historical source association，不授当前文件优化权。

同一resolver随后核source→marker连接PASS：79,592markers/109,288slots保留，79,106
有定义、10,992有body/activation/namespace，50,658外部source-only，6仅invocation、
480无ancestor。均不是direct Python→ATen证明。绑定1355.11s、marker433.90s；这是
离线建模成本，没有新target/prepare/compile。完整记录见
`first_stage_source_attachments_20261023/attempt02`。

正规SourceBodyAccess及CodeWitnessStore接回既有参数/返回/environment算法，实档
attempt02 exit0。原20键marshal/source归档只读加载，compile0/current source read0，
完整descriptor匹配224次；原74CP以public codec/overlay/interface读取，namespace不变。
312,812 operand、16,403 env events与100,438调用守恒；13,872入口参数引用、27条
actual/formal及27条completion条件路由、5,173返回root；3,347entries接10,087env ports。
100,523 route issues、6,694 defaults未定仍在；不授内容、状态、effect或world等价。

旧issue列表线性去重在原run耗764.42s仍未结束，明确SIGINT自有分析任务，原异常栈
确认在成员比较。4行保序set索引修正后，同阶段完整耗2.04s；新attempt整体5:26.17、
peakRSS1,833,420KiB。原失败/停止、字节码证据、脚本、producer和分表输出全部保存。
这是SCAR自身吞吐修正，不能报成LeWM加速；不是同样条件的完整性能A/B。

完整OS接口新模式公共CLI也已exit0/PUBLISHED：1,067,773原lines、1,067,768接口/
submissions、1,067,539普通return outcomes，35个新FD producer ports；4,309,455原记录
分681chunks，10.779GB decoded/260.738MB stored，wall22:01.83。独立audit03 exit0，
全量chunk/row/count与work wire关联核过，实际101结构分支代表codec通过；不是
全量work codec或全ExecutionModel语义。成功exec/exit/5未知return、3,340未定process
接口均未虚构完成或归属。
唯一未接祖先actor有真实原档，其为collector上下文，后续须以通用exec/clone证据接线。

完整模型仍OPEN。旧source/路由在272038，新物理/OS在369749；不能混合动态事实。
下一项是版本化静态证据接当前Run、通用语言内部结构、逻辑来源/状态及资源关联；
参见当前交付第5节。没有开始化简或增加backend/detector。

### 2026-10-23：分块归档已发布、物理采集成功，继续连接原图

原单JSON失败已由分片恢复解决：151 source shards与13components，manifest63,577
字节；1627/1627原返回精确恢复，840个原ProgramGraph经公共codec/overlay/formal
检查，787 UNSUPPORTED、590 NOT_ATTEMPTED均保留。无fresh body lowering。
新inventory与旧151source archives的snapshot和完整context逐项相等，正规
CompositionIndex及同capture source binder的接线已实档PASS，不再prepare151个文件：
100,438调用中5,624 body-linked、3,162 source-only、91,652 unresolved；source组合/
绑定wall14:26.32。其后same_capture marker连接PASS：79,592 marker/109,288原slot
全部保留，10,992 body/activation/namespace关联、17,456 source-only；wall442.34s。
缺少外部图正式接入、actual/formal/return/environment/state等，不把引用连接算完成。

依赖源码准入及独立增量均已结束并审核PASS：106文件全部有snapshot/三图，243groups/
86,702次调用有完整descriptor/source witness。只补原预算阻止的27文件；原199个
witness不重match，新增44组全部VERIFIED、27次prepare、7原context一致，437.87s。
剩803次非文件名与14次工具源码current drift显式保留，不提升为body/effect证明。

新增通用物理collector已跑完原LeWM完整episode（return0/success/video），
79,592 markers、109,288 Tensor槽，108,682槽已导入物理epoch；606槽是带provider ID、
storage pointer为None的空CPU Tensor，不伪造分配。原档1.17GB经hash往返压缩至54.9MB；
5进程/252线程/266成员共同坐标
核验PASS。record_shapes可能保留引用、改变所观察生命周期，不能据此推断原程序
泄漏。643.29s为重度插桩墙钟，没有LeWM加速比。

IRBundle分块存储已做一次真实CPU原档全记录往返：25表786条原记录/顺序/收据PASS；
完整LeWM物理联合导入使用 `--bundle-partitions` 已exit0并独立审核PASS：2,259,781原
记录分195chunks，2.98GB decoded/145MB stored，不生成一份巨大bundle JSON。
108,682物理槽/37,506epochs全部与原report一致，209输出stored SHA核验；完整导入
wall18:59.69/peakRSS约6.97GiB。861 OS点process未知、逻辑内容/版本/state/ready仍OPEN。
SQLite原图实体/关系索引首次真实构建及必要查询PASS：437,228实体、1,172,205关系；
151/2217/1627/840原分母守恒，integrity=ok、FK0。建库418.65s、DB约459.2MiB、
peakRSS约188.5MiB。42,767条endpoint引用仍未语义索引；数据库发布不是完整模型通过。
记录与文档见 [GRAPH_STORAGE.md](GRAPH_STORAGE.md)、[当前交付](FIRST_STAGE_DELIVERY.md)。
上述存储发布与局部连接均不是第一阶段完整软硬件依赖闭合，不进入优化阶段。

### 2026-10-23：大模型存储与当前任务纠正

完整普通源码任务已退出2，用时33:49；最终单JSON写入超过256MB独立上限，未
发布inventory。1627份原返回检查点保留，840个有原图，raw合计513,803,391字节。
这不是新全量inventory通过，也不与旧54 body相加。原日志保存。
按用户最新存储要求，暂停1GB大JSON路线；改从原检查点恢复分片inventory，
manifest索引原图与全局组件，逐图/overlay校验不减少。SQLite图索引与原证据归档
分工见 [GRAPH_STORAGE.md](GRAPH_STORAGE.md)，数据库尚未实现。

已实现依赖源码独立准入入口并开始一次真实离线采集原档分析；尚无最终验收数。
Tensor物理sidecar exporter正在实现，复用profiler event tree，不另写CUPTI；
尚未接采集器或运行验收。两者均不授完整状态/逻辑版本/ready结论。
当前继续第一阶段；不新增detector/backend、不报告LeWM加速比。

### 2026-10-23：成功全流程采集与统一运行身份

**最新核验**：生产桥与资源联合导入已完成，实际原档独立审核PASS；39,796 dispatch
接109,288个Tensor引用槽，完整保留480个祖先缺失和383个未资格化叶。schema接口
另经原导出全量核对：100 schemas、481 ports、467,756个实际Tensor槽接形式端口，
175,022个因无schema保留UNQUALIFIED，所有effect为PARTIAL。
source绑定与dispatch引用进一步汇合：79,592个marker全部保留，79,112个接到当前
帧记录，28,448个有source definition，10,986个有原局部body/activation引用；这是
marker观察计数，**不是独立函数数或直接Python→ATen调用证明**。

目前最大源码缺口已按实际调用权重归因：71,368次被project_root挡在依赖边界，
其中70,565次源码实际存在；其次是新code无旧witness、module/genexpr/lambda/延迟
annotation未有定义对应。见[SOURCE_RECOVERY_FRONTIERS.md](SOURCE_RECOVERY_FRONTIERS.md)。
下一项自动准入已安装依赖源码，使用独立SourceRoot和原CodeID证明，不把原root扩大
为整个文件系统，也不递归扫描所有传递依赖。

自动封存策略经真实FIFO调度否决：465个body返回发生444次seal，耗时已超过33分钟，
无法摊销冷成本。只停止自有分析PID，日志原样保存；没有最终inventory，不冒充成果。
默认恢复普通完整校验，显式seal保留可选。新的全量位于
`first_stage_full_inventory_plain_20261023`，基于最新capture，并保存逐body原图检查点。
尚未结束，不用其中间数更新全量覆盖率；公共校验/队列/预算未放宽。

后续同日进展：生产 dispatch 参数槽桥已实现，先以一次真实 CPU 程序核验重复
Tensor 参数、返回、异常、view 与 autograd；不是重新执行目标来猜数据边。随后
原 LeWM 命令成功运行，returncode 0、100,438 次保留调用、39,796 次 dispatch、
119,388 条 sidecar，零 drop/error/gap，owned mode 已退出；episode 成功并保存视频。
404.86s 插桩墙钟和 150.19s 目标 evaluation time 都不是干净性能数据。
新联合导入进行中，264 个成员/906,808 行 OS 已核；逐槽与 provider 的全量核对
尚未结束，不能提前写 VERIFIED。产物位于 `first_stage_lewm_dispatch_20261023` 与
`first_stage_joined_dispatch_20261023`。

唯一的全量源码重建已从真实成功原档重新开始，environment profile、
4096 body/100000 aggregate operations；`first_stage_full_inventory_20261023` 有
逐文件 prepare/seal 和逐 body 的进度。尚无最终覆盖数；不会把运行中计数与旧的
54 个局部 body 相加。新的源码 invocation 接线复用本次产生的 exact code/source
witness，不重新按函数名或行号猜测，不在每次查询再 prepare 全部源码。

本节接管下面历史运行中的状态：此前两个未结束的全量源码分析进程已不存在，
没有可验收的最终产物，不能继续称其“正在运行”。数据挂载恢复后已重新成功运行
原 pusht 单 episode 命令，未修改 LeWM。新采集产品版本 `7de08ee`，returncode 0，
生成 episode 结果和视频；291.93s 是重度插桩墙钟，不能作为干净 benchmark 或加速比。
见[实际完整采集](../artifacts/experiments/first_stage_lewm_environment_mounted_20261022/README.md)。

新增公共 `import-capture` 从同一次原档先核 collector/nonce/原始 hash、进程创建与
文件发布证据，再让内存和 OS 适配器在构造时使用同一组 Run/Process/Thread。
真实导入 exit 0、373.43s：262 个证据成员、5 个进程、252 个线程，保留全部
70,872 条 profiler 内存记录、253 份/720,049 行 OS 记录。151,226 个 CPU RF
对应和 24,082 个 runtime→GPU 对应来自原 provider；不提升为 Python 调用关系。
OS 中还有 654 个所检查端点的进程未解析，明确保留；不能只用 PID 猜接。
见[联合导入和核验](../artifacts/experiments/first_stage_joined_capture_20261023/README.md)。

源码侧新增 `compose-program`，只引用原 source/CFG/body 的身份和摘要，提供递归
展开、有序 Uses/状态访问查询及条件调用目标，不新造 producer 或全程序根。
真实原 151 文件组合已完成：122,323 source atoms、54 个已有局部 typed body。
原 202 UNSUPPORTED/1,961 NOT_ATTEMPTED、module initializer 与跨函数绑定缺口
均保留；这不是新的 body 覆盖率，也不是完整 ProgramSnapshot。
见[组合查询](PROGRAM_COMPOSITION.md)。

一次固定真实源码 profile 证明现有索引改进未测得提速（5.9606→6.1337s），主要
剩余成本是逐函数重复全文件源层校验。正在改为显式、独立封存的每文件分析会话：
只复用已全验的私有源层，公共读入/重放和新 body 构造仍完整校验。吞吐数据仅用于
建模前端，不是优化 LeWM；后续全量结果产生后才更新覆盖数。

**当前优先顺序**：完成封存会话及同范围全量源码重建；把真实 Python 调用与
Torch 输入/输出逐槽身份接通；再将来源、状态、资源使用和完成关系逐项闭合。
第一阶段 S3/S4 仍 OPEN，不进入候选检测、变换或性能 A/B。

### 2026-10-22恢复状态

全范围4096/100000op原重建运行超过30分钟，尚无新全量覆盖数。只读调用链审查已
证实每成功structured/ENV body原有3次core全验与2次overlay全验，无loop也做循环
支配分析。现已消除内部重复，lowerer仍在返回前全验，expansion核profile/definition/
interface/region，公共读入/源码重放保留完整检查。未增加测试，尚无吞吐提速实测；
不会把代码路径减少直接当测得的加速比。后续实际建模使用该版本。

OS资源已从原成功LeWM的253份/705569行原档自动导入：12587 OFD、12588 handle
代次、521 handle结束、968条private表内IO连接；其余syscall及共享/继承明确OPEN。
独立原档hash/行/成功open集合核对PASS。首次输出重复artifact造成512MB上限失败，
改索引化来源及64KB写缓冲后61.48s成功，gzip8.5MiB，未加大上限或增加测试套件。
见[实际OS导入](../artifacts/experiments/first_stage_os_resources_20261022/README.md)。
canonical source/effect、mmap/pipe/device/ready与完整模型仍未通过。

新LeWM采集失败已归档：未加载dataset，因历史数据根未挂载而returncode1。
启动窗口实际得到209 function dispatch/63 entry，零drop/error；明确关闭profiler
时间调整的配置已写入，148条原生memory receipt对应核验通过。此窗口无推理/GPU
计算结论，不能冒充完整episode。32MB自己的原档已核hash无损压到2.6MB。
见[失败与保留](../artifacts/experiments/first_stage_lewm_environment_capture_20261022/README.md)。

全范围源码重建正运行（51ac4d3），取消原256-body尝试上限，改4096/100000op；
复用原成功episode calls，不执行目标或添加测试。结束后才报告新的全量数值。

Dict/heap receiver的真实24body回查完成：20文件，8局部成功/16其余断点/0错误，
96.72s。入口main成功，策略/求解推进到ListComp/解构。跨调用适配同步修复了
structured/ENV未接旧frame路由的问题；显式formal、返回payload、环境端口分别处理。
见[实际回查](../artifacts/experiments/first_stage_mapping_blockers_20261022/README.md)。

真实函数环境采集已实现并做一次小CPU采集，原档/指标保存。新完整LeWM命令已
实际启动但在dataset加载前因原/gpu4-share数据根缺失而失败，未进入推理；此次
失败不得作完整episode或性能数据。继续使用之前成功的完整原档建模，并记录路径
缺口；不改共享mount、LeWM、conda。

最新资源导入已经真实完成（产品7bcece2）：70872条memory全部逐项保留，
35598 allocation epochs、35274配对free、916复用地址槽、324窗口末open；
独立原档/ValueGraph/lifetime审计PASS。旧捕获配置缺失使全部lifetime仍为
CONDITIONAL，canonical stage/effect/physical lifetime未连接；不能计完整闭包。
见[真实内存导入](../artifacts/experiments/first_stage_native_memory_20261022/README.md)。

格式字符串已直接回查19文件/22个相关body，16个局部成功、6个剩余其它阻塞、
0 ERROR，55.59s。见[真实字符串回查](../artifacts/experiments/first_stage_string_blockers_20261022/README.md)。
诊断cohort不与全量54相加；本轮未扩大测试。接下来同次LeWM采集补实际函数
环境和明确profiler配置，源码侧补Dict等已有真实断点；仍不进入化简。

以下“尚未导入”是实施前记录，以上结果接管对应状态。

下一项同时补实际资源断口：原Kineto有70872条memory记录，native importer尚未
建allocation/lifetime；本次独立重计已保存。先复用StorageAllocation/AllocationTarget
接地址代次、provider顺序和生命周期义务，不能称cudaMalloc或拼Tensor内容。
见[具体接线设计](NATIVE_MEMORY_BRIDGE.md)。源码侧继续JoinedStr/Dict/解构等实际断点。

注解/异常/断言也已接线并直接回查真实源码：19文件/24个原阻塞body，
4个局部成功、20个仍拒绝、0错误，60.15秒；下一缺口主要JoinedStr12、Dict6。
产品75fc24d，见[记录](../artifacts/experiments/first_stage_statement_blockers_20261022/README.md)。
与下面90-body诊断均为独立范围，未另报全量新覆盖率，未扩大测试。

随后的真实阻塞回查已完成：从上述环境inventory机械选出66个写入、15个BoolOp、
9个IfExp，31文件/90body中**37个成功局部展开、53个继续拒绝、0构造错误**。
新增receiver/key源接线和短路控制使用原canonical图，未扩测试；两分多钟完成。
这是独立cohort预算，**不能直接与全量54相加**。代码2b805c2及逐项图/下一断点见
[真实源码回查](../artifacts/experiments/first_stage_source_blockers_20261022/README.md)。
当前优先剩余解构、异常、声明、import及复杂目标表达式，运行state/resource闭包
仍未完成；下一动作继续第一阶段建模，不进入优化。

最新真实 environment inventory8 已生成（产品545fa4c）：同151文件/原raw/
256尝试/10000op预算，54个局部图、202个UNSUPPORTED、1961个NOT_ATTEMPTED；
core/source分组34/425。原45个环境拒绝只有3个最终成功，25个继续卡heap写，
其余展开到新的语言/slot阻塞；逐条记录及独立全量标准库比较已保存。
见[环境接线实际报告](../artifacts/experiments/first_stage_environment_inventory_20261022/README.md)。
本轮未另跑完整public重放或扩展测试；whole-program、runtime环境actual、细状态、
逻辑来源和资源闭包仍未通过。下一项按新66个首个写阻塞和15/9个BoolOp/IfExp
补真实来源与控制路径。以下是此前同日结果；不以它们覆盖最新数值。

临时开发目录已不存在，旧查询session和相关进程均不存在，未提交的10月20日
source-layer归档/日志不能作为当前可复核证据。Git提交保存了三图留存/复用及
expression→statement上下文代码（`ccf6cac`），已恢复到持久worktree
`~/AAA/scar-worktrees/structured-program-model`。不改LeWM或原SCAR checkout。
本次17项通用source-context/source-layer/CLI测试通过；全LeWM库存重建与独立
查询核验另见[本次报告](../artifacts/experiments/first_stage_source_context_20261022/README.md)。

现已实际完成原151文件三图恢复与全10,235调用查询，原snapshot/三摘要全部匹配。
9,116个调用有结构语句上下文，1,119个未连；原exact-CALL-ID匹配语句CFG为0。
独立标准库审核全量PASS，核63,541条operand、82,299条结果producer和78,691条
控制边；第一次审核的lambda phase误判及修正原样记录。这些只是源码结构关系，
不等于动态值、状态或资源因果闭包，缺口并未因新增边而自动消失。

公共`inventory-program --body-profile structured`已接原structured前端并输出显式
inventory7（默认及旧1–6不变）。66项相关新旧测试通过；同LeWM入口/raw calls/
source/预算的实际重建得到51个局部图、205个UNSUPPORTED、1,961个NOT_ATTEMPTED，
code/source分组接入33/425，仅比旧baseline增加1个body和1组。独立比较通过；
公开check-inventory完整raw/source重放也已REPLAYED（exit0，645.19s），并非
只读摘要或只验证声明。参见
[公共structured实际验收](../artifacts/experiments/first_stage_structured_inventory_20261022/README.md)。
接线提升很小：closure环境45、heap写41、expanded call15、BoolOp13、IfExp8等
仍造成整body回滚。不能把481条语言protocol或source图规模当完整模型完成率；
下一项按这些实际语言/接口断点排序，实际状态/来源/资源闭包仍未完成。

### 环境接线前的实施计划（已执行，保留历史）

优先**自动函数环境入口及cell/namespace依赖**，不预定下一项就是短路表达式。
这补全部函数的隐式输入断口，复用既有EnvironmentInterface、FunctionEntryLayout、
ReferenceOwner、CellContent/NamespaceKey和canonical Uses/state；不新增环境图。

1. 以symtable分类，复用已有准确compiler/source见证取得co_freevars/co_cellvars及
   顺序；不能按变量名或自行排序猜closure tuple。隐式编译器依赖也需保留。
2. 在原入口ReferenceValue/StateVersion参数中声明五个固定环境role及captured
   cells；被调用body的free-variable slot与外层formal slot独立，实际alias允许。
3. freevar读连cell引用owner和CellContent，global/builtin读连准确namespace；
   每条正常/异常路径携自己的后态。不能删除freevar guard后退回普通global读。
4. 新source profile复用既有入口完整分区检查，替换固定formals+world和index+1
   actual假设；旧SourceProgram3/inventory7按V1固定重放，不静默重释旧产物。
5. 单独采集当前callable及环境actual身份。现monitoring CALL可拿到callable，
   旧calls-only及f_locals只给code/内容，不能补造函数对象或cell身份。静态参数化
   依赖通过与动态actual闭合通过分别报告；不以静态入口存在称动态已连接。

验收先用普通Python testcase自动恢复：同code的两个closure、多个函数共享cell、
cell被改写/删除、global/builtin重绑、代码版本/环境不符及错误cell顺序。测试不手
补IR；同时检查真实LeWM每个旧环境阻塞body的环境连接与下一终止点。**45个首个
环境拒绝不代表下一轮必新增45个成功图。** 随后同范围、同预算重建并记录结果。

再按证据补owner明确的attribute/subscript写、失败后态/释放与source slot对应，
destructuring另验。之后补BoolOp/IfExp的取值/条件上下文及expanded calls，禁止
多执行truth或预执行未选分支。实际Uses/逻辑来源、OS/CUDA资源和ready/输出闭包
继续使用原S3/S4合同，不因完成某语言子集而进入化简。

旧说明中CALL的同ID直连语句CFG建议已撤回：同ID类型不等于同粒度，parent_id也
不是AST父节点。新查询按源码指纹、完整AST字段路径和scope关联原语句，保留
短路、默认值、延迟body等边界，不宣称表达式必执行。S3/S4仍OPEN；原50个局部
typed body、206个UNSUPPORTED、1,961个NOT_ATTEMPTED未因该连接而增加。

设计仍按[合同实体表](FIRST_STAGE_MODEL_CONTRACT.md)：代码来源；Operation/Value/
StateLocation/Region/Resource规范结构；运行occurrence与对象/环境；逻辑内容版本/
来源；allocation/view/materialization；work/completion及证据。类型、角色和动作
标签不混在一层。下一步补实际源码→core恢复、Uses/状态与资源生命周期闭包；
不进入detector/backend/化简或性能A/B。以下保留10月20日已入库记录的原范围。

最新增量：独立 ObjectInstance 目录及准确 marker 参数引用桥已落地（`448b912`）。
重放真实 CPU 原档，得到6个对象、12条逐槽对应、保留2个重复参数槽；独立 raw
审计通过，没有制造 LogicalVersion/allocation。此为有条件的研究 profile，不是
生产 Python→ATen 对应，也没有改善原源码覆盖分母。实际报告见
[对象引用验收](../artifacts/experiments/first_stage_object_reference_20261020/README.md)。
下一项仍是生产采集/来源状态连接和资源闭包，不能开始化简或性能 A/B。

范围及验收由 [第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)接管。旧协议组件
报告保留原有限结论，不再作为下一项任务的自动选择器。F20 未开始实施。

## 本轮已确认

- 开发分支 `codex/structured-program-model`，起点 `221819f`，使用隔离 worktree。
- LeWM 原仓库 clean，未修改目标、conda 或 CUDA；本轮暂未执行新的 LeWM/GPU run。
- 现有五类规范结构有基础，但完整身份清单还包括代码、运行 occurrence、对象、
  内容版本、分配/表示和证据；只有分类表不能验收自动建模。
- `inventory-program` 默认 BOUND_FRAME_V1；函数体检查对 for/import/try/with 等
  尚拒绝；structured profile 可单独处理部分循环，但没有接入公共 inventory。
- 历史真实 inventory 的 151 文件/2,217 定义只有 50 个带缺口的局部 body，
  206 UNSUPPORTED、1,961 NOT_ATTEMPTED；这些是旧产物，不是本轮重建结果。
- 现有资源 sampler 采 CPU/GPU 抽样，不等于文件/mmap/queue/allocation 等自动资源模型。

## 执行顺序

1. 只读审计程序模型、自动前端和资源对应，冻结清楚的 S1 设计。
2. 原 LeWM 入口自动生成 S2 当前覆盖清单，对照旧归档确定真实阻塞。
3. 优先接通已有结构和 provider；每项修改必须改善真实端到端必需覆盖。
4. S3/S4 未完成时不添加 detector/backend，不宣称第一阶段完成或报告新加速比。

本文件后续追加命令、结果与失败，不用单元测试数换算程序完成率。

## 只读审计结论

见 [自动化审计](FIRST_STAGE_AUTOMATION_AUDIT.md)。两个独立审查确认：主要缺口
是自动 source lowering、同次证据到规范模型的适配、资源/输出因果闭包。
source atom 归属已经保留，不能称整个源码结构完全没有；typed body 遇单个
unsupported 会整体回滚，才是待修的具体损失。calls recorder 仍持有 profile
hook，不能与 inject 整体简单叠装；ETO 的执行表示也不能当作原静态定义。

第一阶段合同已补先固定 mandatory/required_expansion 的要求：完整原生接口
不等于 native 内部已展开；实际涉及的资源不能通过缩 scope 从分母消失。

## 当前版本真实自动重建（Observed）

起点产品代码 `221819f`，conda `lewm` / Python 3.14.7，使用旧真实成功运行的
原始 calls trace，**只重新分析，不执行目标**。运行脚本和全部产物位于
[`first_stage_model_20261020`](../artifacts/experiments/first_stage_model_20261020/)。

| 项目 | 当前重建结果 |
| --- | --- |
| 自动 source 文件/定义/源码调用 | 151 / 2,217 / 10,235 |
| body | 50 LOWERED_WITH_GAPS / 206 UNSUPPORTED / 1,961 NOT_ATTEMPTED |
| 全 source atom 分母 | 122,323；682 CONNECTED / 107,351 INVENTORY_ONLY / 14,290 UNSUPPORTED |
| 可用运行 code/source 分组接入 | 32 CORE_LINKED / 393 INDEXED_WITHOUT_BODY，共 425 |
| 已索引 scope 类型 | 1,636 FUNCTION / 301 CLASS / 253 COMPREHENSION / 27 LAMBDA |
| 未尝试原因 | 1,380 受构图预算限制；581 需要 class/lambda/comprehension 接口 |
| discovery 缺口 | 1,083 |
| 分析成本（不是 workload 性能） | 636.94 秒 wall；358,460 KiB peak RSS；exit 0 |
| 完整程序/细状态模型 | 仍为 false；没有完整资源模型产物 |

现有库存生成与独立记录重计数均成功，历史与当前结果的主要覆盖计数完全相同。
这不是完整模型验收 PASS：CONNECTED 只表示 source link，不表示完整依赖；当前
预算保留了所有未尝试项，没有把 256 次尝试当成全部 2,217 个定义。

**下一实施项：** 固定这份真实分母；统一 Python call/operand 与原生 ETO/Kineto
采集的生命周期及准确来源，再接规范端口/资源。同时按真实阻塞补 typed source
恢复，避免整 body 回滚。不先做 F20，不新增 detector/backend；S3/S4 仍 OPEN。

## 同次采集的有限实现（Implemented / Verified）

`trace --call-operands --execution-evidence` 现可保持原 Python hook，同时延迟
启动原生 ETO/Kineto，不重跑目标、不采 Tensor 数值。5 个真实新 CPU 集成测试和
33 个旧 CLI 回归通过，共 38；具体范围见
[采集说明与验收](FIRST_STAGE_NATIVE_EVIDENCE.md)。这只解决采集共存，尚未做
完整规范图导入，S3/S4 仍 OPEN。下一项是原 LeWM 同配置真实采集及 OS 资源对照。

## LeWM 同次真实采集（Observed / Verified，非整模型通过）

产品 `1650431` 使用原 pusht checkpoint、单 episode、budget/goal offset 25 命令，
conda lewm / Torch 2.13.0+cu132 / CUDA build 13.2 / RTX 4090。
**exit 0，success_rate=100.0**；302.0469 秒为 instrumented wall，不是 clean 性能。

| 自动取得的证据 | 实际结果 |
| --- | --- |
| Python entries / records / code descriptors | 84,315 / 168,630 / 851 |
| ETO 节点 | 151,228 |
| ETO→Kineto 正 RF ID/名称唯一匹配 | 151,226，重复正 ID 为 0 |
| GPU kernel / 物理 memcpy / memset | 22,457 / 543 / 1,082 |
| GPU activity→runtime correlation | 上述活动在本 capture 均有唯一匹配 |
| OS 记录 | 253 个逐 TID 文件，705,569 行；含启动器/采集器及后代 |
| 外部输出 | 实际生成本地 mp4 和结果文件；OS 中见 ffmpeg/libx264 与文件写/关闭 |
| 正常采集收尾 | provider CLOSED、failures=[]；call/operand dropped=0 |
| 如实保留的缺口 | 945 operand gaps、65 unknown exits；没有把零丢失称为精确建模 |

第一次无 seccomp-BPF 的 strace 开销过高，停止监督器后未正常收尾，判 FAILED。
完整失败记录保留，未当作 LeWM defect。验证轻过滤后完成第二次采集，目标源码、
数据和环境未修改。详见 [实际结果与原始证据](../artifacts/experiments/first_stage_lewm_capture_20261020_bpf/README.md)。
约 610.6 MB 生成元数据经逐文件字节哈希验证后无损归档为约 41.1 MB；未存 Tensor
逐轮数值、未清共享缓存，未删除用户数据。

**第一阶段仍 OPEN：** 原 source inventory 的 50 个局部图没有因此变成全程序图。
尚缺 source 内部自动恢复、准确 Python→Torch 有序端口/当前状态/逻辑版本，以及
OS/CUDA 资源身份、生命周期和输出因果闭包的规范连接。下一项只落实这些自动
建模适配与源码结构复用，不开展图化简、candidate 或 backend。

## 原生观察的自动建图（Implemented / Verified；全阶段 OPEN）

`fdae346` 的通用 `import-native` 已离线处理上述真实 LeWM ETO/Kineto，输出
205,424动态记录、429,336条边；357,090有序引用槽、151,226 RF对应和24,082
runtime→GPU关联经独立标准库脚本对原始字节重放通过。保留5,593个provider引用
编号，**没有据此生成内容版本**。3个设备/流选择器也没有被当成已知生命周期。

入口、实体边界见 [原生观察模型](NATIVE_OBSERVATION_MODEL.md)，实际命令、测试、
首次CPU输入失败和修正、分析成本见
[实验报告](../artifacts/experiments/first_stage_native_import_20261020/README.md)。
本次只使用已有捕获，不重跑 GPU，不改变源 inventory 的分母。

**当前具体断点：** 30,007条runtime的External id尚未建立经来源核验的CPU对应；
Python occurrence/源码CFG、非Tensor完整端口、当前状态/逻辑版本与OS资源闭包
仍未连接。下一项核验provider关联合同并接已有调用来源证据，不扩detector/backend。
完整程序建模仍未验收，不能把本次原生观察图当作最小依赖程序或报告新加速比。

## CPU→原生 scope 对应已接通（Verified；不代表源码或数据身份已接通）

随后核验固定Torch/Kineto官方源码，并机械导入54,089条provider scope关联：
30,007条runtime/driver、24,082条GPU活动。真实图现在205,424动态记录、483,425边。
独立差分审核核对全部新增关联及原有图不变；7条未报告scope的runtime仍不补猜。
见 [原始源码、命令与验收](../artifacts/experiments/first_stage_native_scope_20261020/README.md)。

这解除上一段的External id合同缺口，**没有解除Python occurrence、logical/state、
source内部恢复和OS资源生命周期缺口**。下一桥先做准确带实参marker的CPU实验，
不按_cdata/shape/名称猜对应，不用测试数或图规模宣布全阶段完成。

## Python Tensor对象桥原理实验（Verified；生产桥尚未实施）

同一provider带Tensor实参marker已在独立CPU testcase中验证：5次dispatch、
10个marker、6个weak token，可按nonce和有序槽机械连接到ETO编号；重复实参、
view、原地写与梯度均检查通过。真实marker直接parent是PythonDispatchMode包装
scope，未按opname猜原ATen；Python上下文也保留包装调用链，未强并InvocationID。

详见 [实验、首次审核失败和后续门槛](../artifacts/experiments/first_stage_marker_probe_20261020/README.md)。
这仅验证准确连接原理。下一实施项是有界生产桥、所有权/异常/foreign mode验收；
之后才重新采LeWM。source内部/状态/资源闭包依然OPEN，继续第一阶段。
