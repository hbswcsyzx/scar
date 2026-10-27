# SourceProgram5 正式接回分片 inventory/composition：最小接口设计

2026-10-23。**Implemented / 两个真实body已正式发布并经公共reader回读；当前Run联合门未结束。**
两个新 source bodies 已有真实有界验证；当前调用覆盖数须等完整runtime门后重新推导。
本设计不新增图、detector/backend，不准备151份source，不执行目标，不扩GraphIndex基建。

## 1. 已核代码与确切接口断口

已读 `inventory_partitions.py` 的 writer/reader、TypedBodyPartition、CP引用、各component；
`program_inventory.py`/`ir/program/inventory.py`；`program_composition.py` 的
_InventorySource/_compose_file/CompositionIndex；source_layers 的输入绑定与archive读取；
function_interfaces、call_demand._call_source_scope、source_invocations 的 _source_tables/
_binding_rows、SourceBodyAccess.bundle、call_edges._link_call_model。

| 当前接口 | 当前事实与必需改动 |
| --- | --- |
| partition root1/file wrapper1/CP1 | 原lowerer返回检查点；CP1保存operations_emitted、请求source/profile/budget等。只能在显式后继版本接新capability |
| checkpoint_reference | 严格只收CP1；旧行为保留，新CP2用独立准入构造入口 |
| InventoryPartitions.checkpoint | 当前只核schema/authority，未独立拒绝未知checkpoint版本；新reader必须明确按root/file允许版本核CP1/2 |
| TypedBodyPartition | 无language，source_overlay布尔未区分语言结构/独立source-code证明；需尾部显式字段 |
| typed_body(source_layers=...) | 固定以language=None验证structured；新协议必拒。必须正规传overlay及验证模式 |
| _InventorySource.body_locators | 假定PG/metadata在CP自身#/graph、#/metadata；CP2引用既有SourceProgram时必须返回真实目标artifact/pointer |
| compose_program | 每次解151source及所有body；delta发布不应再调用这个完整重组成路径 |
| source inventory header8 | 不能在旧scar.program-inventory/8下悄悄放入新协议；legacy monolithic1–8继续拒新能力 |
| SourceBodyAccess | 当前header numeric==8，bundle不传language；call_edges还检查numeric5–8。必须显式能力分支，不能伪装v8 |

## 2. Proposed：版本与真正的数据来源

建议采用 **partition manifest2 + affected file wrapper2**；允许混合引用原CP1和新CP2。
root显式列出允许的checkpoint版本和source-language版本/capabilities；未知版本拒绝。
未改变的150 source shards、840原成功PG及所有未改组件引用原URI+SHA/size，原件不复制。
PG IDs、原source snapshot/context、SourceDefinitionReference、旧CP1含义不变。

新header建议独立schema `scar.partitioned-inventory-header/2`，保留原header receipt与
STRUCTURED_ENV entry ABI，单列publication capability/budget/新摘要。**不声称已经实现
public monolithic inventory9**，也不修改legacy ProgramInventory.from_dict的整库重放合同。
组件外层 `scar.inventory-component/1` 是通用name/value归档，可保原版本；其新header值
schema必须由reader/SBA显式核定。旧reader在manifest2入口即拒绝。

CP2建议为 **SOURCE_PROGRAM5_ADMISSION 的引用封装**，不复制原PG和三份source图：

```text
scar.body-construction-checkpoint/2
  origin: SOURCE_PROGRAM5_ADMISSION
  source_program: exact SourceProgram5 artifact + SHA/size
  body_identity: snapshot + namespace_root + DefinitionID + source + entry
  profile: unchanged STRUCTURED_ENV_V1
  graph / metadata / interface / frame / structured / language:
    required field locators into that exact source_program artifact
  source_archive: original artifact/context locators
  previous_body: exact parent source-shard/body locator
  verification: structural checks, independent-source/code checks, remaining conditions
  construction: original lowerer cost known/UNKNOWN, publication budget separately
  whole_program_established: false
```

language为必需的可解析来源引用，必须指向原 `/language` 的版本化overlay；不能只放一个
capability字符串或已通过布尔。新record是准入收据，不冒称原LoweredSourceBody返回。
CP2的graph字段若是locator，不能用CP2#/graph冒充图节点；canonical namespace必须取
**实际SourceProgram5 artifact的decodedSHA + scar.program-graph/N + #/graph + body**。
CP2准入record自身有自己的artifact身份，与PG实体身份分开。两新body的PG本体不重写。

一个实存缺口需如实处理：SourceProgram5不保存max_operations或operations_emitted。
body26的durable checks保存65；body11保存PG118与原progress/budget，但没有独立返回成本
报告。`len(graph.operations)`只能证明图大小，不能冒充原lowerer曾发射/回滚的总成本。
因此通用准入器默认将原construction cost记UNKNOWN，publication的节点计数/验证预算
另记；不因要填CP1字段而重新lower body11。若既有BodyInventory typed API需要该值，
最小严谨扩展是 `construction_operations: int | None`，CP2未知为None；旧CP1仍严格int，
legacy writer继续拒新capability。不得用0冒充已知零成本。

已核类型/预算路径：BodyInventory当前声明int；ProgramInventory.summary直接sum；
program_expansion把该值交给旧queue并另计operation_budget_charged/construction_cost_known。
本publisher不进入旧queue、不伪造新ExpansionScheduleV6。若增加nullable typed字段，
legacy ProgramInventory._check_profile也需明确拒None，避免summary的隐式TypeError或旧wire泄漏；
CP1 reader继续严格int。新header的总construction成本遇None即UNKNOWN，单列known subtotal /
unknown body count；原队列成本与原预算收据只作为base历史保存。

## 3. Proposed：自动定位、准入与局部发布

新增入口建议：

```text
publish_source_programs(base_composition, source_program_paths, out_dir,
                        code_witnesses=explicit_readonly_owned_store,
                        budget=SourcePublicationBudget(...))
  -> manifest2 + publication receipt
```

不传LeWM名、file140/body11/26或qualname猜测。对每个输入机械执行：

1. 正规SourceProgram5结构读取，检查完整PG/原source layers/overlay与entry ABI。
2. 按metadata.source(path,fingerprint)、language.namespace_root和interface.definition，
   在base source snapshot/context及DefinitionInventory.source中唯一定位原definition/body；
   该definition还须与structured.source及原CodeSourceLink完全一致。无唯一匹配即拒绝。
3. 比对输入三source图与该base SourceLayerView的完整context digests，复用原archive；
   当前文件只核exact text/fingerprint、每file一次AST/symtable，绝不prepare/compile。
4. 用显式只读CodeWitnessStore + 原composition构造SourceCodeEvidence，完整CapturedCode、
   原CodeSourceLink、compiler profile/flags、原source与constant path独立验证。
   不自动打开输入JSON任意指向的marshal archive，不接受一份自称VERIFIED的dict为证明。
5. 验证新interface与唯一原FunctionSignature、正常/异常world、language overlay/source
   与原ports；继续保留UNKNOWN effects、constant runtime-instance、comp等frontiers。
6. 写2个小CP2；只写受影响source shard2，在原body序号替换准入ref与status/reason，
   原definitions/calls/coverage/context、其它body refs保持。旧失败CP1通过parent receipt保留。
7. interfaces component只加入新entry refs；structured只加入新model refs。原signatures、
   source-level conditional bindings、issues与其顺序保持；不凭新body伪造新actual/formal
   routes，也不把原缺失的CallArgument.use强行补成无namespace的bare UseID。
8. admission按已有单条通用规则机械重算受影响项，保eligible origin分母与顺序；
   call_sources原记录不改。runtime agent负责该规则的正规提取与SBA消费适配。
9. 新header/summary区分base历史construction/queue measurements与本次publication成本；
   不改旧expansion、原measurements或budget而假称整个队列重跑。原计数逐项加减，原未恢复
   与未尝试分母完整保留，所有新artifact校验后才原子发布manifest2。

原source archive index的input仍属于历史inventory，不能改写SHA假称由新manifest产生。
新publication receipt显式继承parent inventory/composition/source-index收据，并逐file核
相同snapshot/context。source_layers.load_source_layers可按原archive读取，不调用其
整库rebuild/reuse入口来绕过输入SHA检查。

还有一个必须正规适配的来源边界：当前SourceCodeEvidence.to_dict把composition.inventory
写入witness。新manifest后以newComposition重建options，会与原overlay的旧producer收据
不等；不能为方便删除平等检查或修改旧overlay。建议CompositionIndex新增
`code_source_origin()`：旧index按原行为返回当前inventory/原call_sources artifact；
新index3按已核parent manifest继承**原static code witness origin**，且核call_sources组件
URI/SHA/size确实原件未变。SourceCodeEvidence只从该正规API取origin，其CodeType完整
describe_code/CodeSourceLink/source验证仍照旧。所需原manifest很小，不必再load第二份巨型
旧composition；若组件改变或继承不能核，就保留full proof frontier，结构读取仍可分开。
current Run/new inventory身份仍由source binding/report单独记录，绝不借旧PID/entry当新事实。

## 4. Proposed：最小reader/composition接线

`InventoryPartitions.checkpoint`返回实际CP版本文档；新增受控body-field resolver按CP2
固定SourceProgram5字段locators解析，不追任意JSON pointer。body_record继续暴露同一
规范graph/metadata来源，增加来源/能力必须用显式版本分支；不能拼回巨型inventory。

TypedBodyPartition保留现有前置字段，新增尾部：language、language结构检查状态、
独立source/code检查状态及实际locators。source_replay_performed仍false，除非确实重建。
仅graph core解码不等于language/source overlay已核。CP2可通过原SourceProgram5结构codec
核其内嵌三图，然后逐项digest核到原file context，不要求重建或复制source图；亦可接受
已经核对snapshot/context的SourceLayerView，避免重复读取同一file。独立source/code proof仍需显式options/AST；
保存的verification收据只是历史producer证据，不能自动提升当前权限。

delta composition新增正规入口 `compose_source_publication(base_composition,new_manifest,...)`：
核parent receipt与完整差异集，复用150原file projection，**只重建变化file的projection**。
同file旧PG使用原namespace，其inventory-header locator更新到新source shard；新PG真实
locator指向原SourceProgram5。跨file definition targets不变，所有summary从实际rows汇总。
原file/CP/artifact的URI即使从新root改成external引用，实际locator必须保持canonical原路径。

建议composition新schema3明确partition2/capability与parent来源，旧index1/2不重解释；
CompositionIndex正规accept3并保持旧API。ElementReference仍是内部导航坐标，正式source
身份取原SourceDefinitionReference，formal/Use/Region引用均带实际PG namespace。
旧source-only状态不能直接冒充新body准入；本Run的重绑定由runtime接线独立完成。

## 5. 待改文件与边界

| 归属 | 准确文件/API |
| --- | --- |
| 新publisher | NEW `analysis/source_program_publication.py`：局部准入、immutable CP2/分片发布；不创建ProgramInventory整图对象 |
| 存储reader | `analysis/inventory_partitions.py`：root1/2、file1/2、CP1/2准入、TypedBodyPartition、真实field locators、严格旧CP拒新tag |
| nullable成本类型 | `ir/program/inventory.py` BodyInventory：若采用该接口，construction_operations显式None，不更改ProgramGraph |
| 旧wrapper成本门 | `analysis/program_inventory.py`：只加legacy入口拒None的明确门，原1–8及重放算法不变 |
| composition | `analysis/program_composition.py`：schema3、delta composer、CP2 actual locators/namespace、typed language bundle；source archives不重建 |
| 原language来源 | `analysis/source_language.py` SourceCodeEvidence通过正规code_source_origin保原producer收据；原descriptor/独立CodeType校验不删 |
| 原language语义 | `analysis/program_lowering.py`与language lowering/validators只复用当前public接口，不新增语法或放宽guard |
| runtime agent | `call_demand.py`或独立共享单条admission helper；`source_invocations.py`、`source_body_access.py`、`call_edges.py`：正规header/capability、language验证、currentRun端口选图 |
| 保持 | legacy ProgramInventory1–8、旧CP1/manifest1、source_layers原档/语义、source attachments、CodeWitnessStore、trace/profiler |

CLI可在publisher/reader通过后由root接；GraphIndex需后继新快照/namespace输入更新，本门
只列此需要，不实现数据库迁移或全库增量基础设施。

有界实档验收：从两个已存SourceProgram5自动发现同一source的两原definition，发布1个
source shard2、2个CP2与必要components/root；核其它150source/840PG refs逐项不变，
旧版本拒新能力，新CP2可typed读取/按原record查询、independent proof与结构权限分开。
不重lower、prepare或compile，不执行目标。随后独立以现369749原raw/Run与current-source
证据接新composition，核原groups/calls及两个source-only→newbody的端口，model仍OPEN。

## 6. 实现检查点

上述最小接口已实现，6个拥有生产文件AST、diffcheck与public API import检查PASS。
实际源码SHA/patch/导入链记录在
`artifacts/experiments/first_stage_source_publication_implementation_20261023/freeze.json`。
尚未运行实际publication、全源读取/prepare/compile或目标。根将统一记录真实两body发布、
composition delta与当前Run接线的验收，不能从本实现冻结推导已完成集成。
