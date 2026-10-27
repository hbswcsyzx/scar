# AnalysisScope / CoverageObligation 最小公共账本方案

2026-10-25。**最小 v2 已实施，retained source/call membership 门实际 exit0；整体 OPEN。** 服从
[第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md) §2.1；补充
[声明模型审计](DECLARATIVE_MODEL_AUDIT.md)，不修改已冻结审计。
后继接线主线是原完整运行的全部 dispatch，当前报告分母为 39,796；scalar 内容只是其中一项，
不再以反复 16-prefix 子门代替全范围接入。本方案不执行目标、不读 raw、不改变原图 schema。
本次真实门只完整枚举已保留的 2217 个 source 定义和 100438 次 source invocation，合计
102655 个原成员，另有六个 mandatory 集合欠账，共 102661 条义务；没有完成全部依赖建模，
也不是新 LeWM episode。实际[结果与限制](../artifacts/experiments/modeling_scope_retained_gate_20261025/RESULT.md)
记录 637 块、stored 126695719B / decoded 4268542417B、worker 694.3875720299839s、
SELF/GNU-time peak RSS 均 114576KiB。逐义务重复 locator/规则/证据/四轴编码的成本明显，
不称高效；十个只读查询样本各定位一个 index chunk 和一个 data chunk，不是查询延迟基准。

下文保留全合同目标与后继 adapter 设计；尚未实现的 qualified-entity 细化、全部域逐成员
producer、语义 accepted-scope 复用、revision delta 与总体验收 API 均不能算本次已完成。
实际公共 API 和严格支持范围以[实现说明](MODELING_SCOPE_MEMBERSHIP_IMPLEMENTATION.md)为准。

## 1. 目的与必须保持的权威

账本回答“哪个原对象/原集合必须满足哪些关系、要求什么展开层级、证据还缺在哪里”。
ProgramGraph、ExecutionModel、ValueGraph、EvidenceGraph 仍分别声明原事实；账本不新增
Operation/producer/Use/state/resource，也不补出原图中不存在的边。
账本发布成功、记录结构合法、证据复核通过、完整建模通过必须分别报告。

方案制定前不存在合同字段齐备的统一 typed AnalysisScope/CoverageObligation；现已新增最小
公共类型、strict codec、固定 source/call producer 和有界发布/只读查询。现有 CoverageEntry、
provider coverage、OS classifications、source frontiers 与 `whole_program=False` 仍只是输入，
不能作为满足覆盖义务的证据。本次 102655 个准确原成员各有实际 obligation；其他六域是
准确 collection-level debt，未被一张全 False 汇总或空 manifest 替代。

公共类型/API 草案和机器可读记录规格见
[方案目录](../artifacts/analysis/modeling_scope_ledger_plan_20261025/README.md)。
这些文件是设计规格，不是一个新执行 IR，也不是已生成的真实覆盖结果。

## 2. 最小公共记录

已新增 `scar/ir/modeling_scope.py`、`modeling_scope_codec.py`、`scar/analysis/modeling_scope.py`
及 `scar/store/scope_partitions.py`。实际 record 为 `scar.modeling-scope-record`2、transport 为
`scar.partitioned-modeling-scope-ledger`2、policy 为 SOURCE_CALL_MEMBERSHIP_V2；v1 prototype
被明确拒绝并保留历史，不静默迁移。原始方案目录仍是设计规格，以下记录表含后继未实现项。
不改变 ProgramGraph28、ExecutionModel9 或 v2 图 codec；不把账本塞进任意 metadata。

| 记录 | 必需字段 | 责任 |
| --- | --- | --- |
| `AnalysisScope` | `id,revision,parent,contract,policy,source,run,fields,observability,denominators,policy_sources` | 将验收绑定准确运行/入口、原输入与固定规则；字段缺证据仍可建立 OPEN scope。 |
| `CoverageObligation` | **`id,source,subject,required_relations,required_expansion,mandatory`**，另有 `scope_revision,rule_key` | 原合同要求的稳定验收项；不存结论。source 同时引用规则原位置与独立发现该 subject 的原位置。 |
| `DenominatorInventory` | `id,domain,collection,source,declared_count,enumerated_count,membership_sha256,enumeration,observation_coverage,cursor,gaps` | 独立保存范围与逐成员账；枚举完归档不意味着观察无丢失。 |
| `DenominatorMember` | `denominator,subject,obligations,source` | 每个真实原成员到适用 obligation 的验收索引；跨域去重 obligation 不丢原独立 membership。 |
| `CoverageAssessment` | `obligation,scope_revision,axes,checker,source` | 四轴逐 requirement 的可复核结果；每项保原证据、条件、缺口和未访 cursor。 |
| `ScopeRevisionDelta` | `parent,child,added,removed,modified,reasons,source` | 显式显示 mandatory、required_relations、展开层级、源快照或范围修订；不能静默缩分母。 |
| `LedgerReceipt` | `schema,schema_version,scope_revision,scope,tables,storage_receipts` | 返回实际 scope/表位置与归档 receipt；仅运输，不提供 `complete=True` 或模型 PASS。 |

其中 source/subject/receipt 的小型封闭引用类型见 §3；Gap/AxisResult/Cursor 是这些记录的
typed 子记录。`LedgerVerification` 是重新计算的查询返回值，不是可由输入布尔值授予的证明。
只有 `CoverageObligation.mandatory` 为原合同布尔；不接受 caller 提供的 PASS/verified 布尔。

稳定身份规则：

- `ScopeID = sha256(profile, 原 Run 的限定引用, 原 command receipt 的身份及 command locator)`。
  原 logical URI/namespace 属于身份，不能靠相同 SHA 猜两份 artifact 同源；当前无 retention
  relocation 映射，不承诺搬家后自动同身份。不得用当前 PID、时间或分析机器 cwd 生成 scope 身份。
- `ScopeRevision = sha256(除 revision 自身外的规范 AnalysisScope 字节)`。原政策、源快照、
  输入身份、观察能力或分母变更形成新 revision，parent 与 delta 必须保留。
- `ObligationID = sha256(ScopeID, 原 subject 的规范限定键, rule_key)`，不含评估结论、
  新鲜时间、数组序号、mandatory 或展开级别。后两者变化因此必须显式出现在 revision delta。
  `rule_key` 是版本化规则中的稳定条款键；四个必要源码的 URI/SHA/size 放在显式
  scope.policy_sources，初始化冻结并在发布终检，不用程序 CODE_VERSIONS 或 status 替代。
- 原 source/body 被显式 revision 替换时，原 subject 不再相同，新 obligation 保留旧项的
  supersession 记录。不能将旧 842 的实际调用关联迁移成新 843 的动态证明。
- Ledger ID 是验收记录身份，不改任何原图 ID。不同独立分母可以指同一原 subject；
  原事实不合并，验收条款按 scope+subject+rule 去重，分母 membership 分别保留。

## 3. Subject 与证据引用：不能使用裸 ID

`CoverageSubject` 为封闭联合：

1. `SourceDefinitionSubject(reference:SourceDefinitionReference)`，直接复用
   `program/source_references.py` 的原 source/root/context/graph qualified reference。
2. `QualifiedEntitySubject(reference:QualifiedProgramReference,record:EvidenceLocator)`。
   `reference` 严格复用 `InventoryPartitions.qualified_reference` 返回的
   `{namespace,kind,local_id}`；namespace 包含原 artifact decoded SHA、representation、
   record_pointer、body identity。新 helper 只将原公共 wire shape 强类型化，不能重新分配身份。
3. `ArtifactRecordSubject(record:EvidenceLocator)`：没有 typed body 的 source definition、
   调用记录、provider instance、OS resource/handle 都可用**准确原记录位置**保留，
   不要求先为其伪造 canonical 节点。
4. `CollectionSubject(collection:CollectionLocator)`：准确原 manifest/table/array 的全集，
   用于未枚举、漏采和整域义务。它不能把集合缺口当成一个已恢复的执行节点。

`EvidenceLocator` 只允许四类，并均由允许清单中的显式 reader 解析：

- `JsonRecordRef(artifact:RetainedArtifact,pointer)`：指向原 JSON 的真实 RFC6901 fragment；
  `#` 是原 root，缺字段不能伪造 `#/cwd` 当存在证据。
- `JsonlRecordRef(artifact,line,line_sha256,pointer)`：一基真实 decoded line，pointer 在该行内。
  不把 JSONL 当成虚构 `#/records/123` 数组。
- `PartitionRecordRef(manifest_chunk:JsonRecordRef,table,ordinal,line,line_sha256,pointer)`：
  chunk 指针是**实际 manifest** 的 `#/graphs/<g>/tables/<t>/chunks/<n>` 或
  `#/tables/<t>/chunks/<n>`；校验该 declaration 的 stored/decoded receipt，再定位原行。
  ordinal 只是原 table 位置，不能当 invocation/实体 ID。
- `TextRangeRef(artifact,first_line,last_line,range_sha256)`：真实 decoded text 行范围；
  用于原 Markdown 合同和 strace 文本，不把它们伪装成 JSON/JSONL。

`RetainedArtifact` 复用原 ProviderArtifact 的 URI/schema/physical SHA/size，另存 decoded SHA/
size 及显式 JSON/JSONL/text、gzip 编码；不猜 gzip 文件名、不从网络任意打开 URI。
已有 SourceArtifactLocator 可通过无损适配保留原 declaration/双 SHA，不迁移其身份。
source 文档和报告若只提供 declared receipt，标为 DECLARED/OPEN；不是已经独立验过字节。

collection 必须指真实已存在的 array/table descriptor，而非字符串“所有 OS”。若必需 provider
或字段根本未保存，subject 引准确 capture/root/membership 集合，并生成该域缺失义务；
`MISSING_COLLECTION` 留在 Gap，不伪造不存在的 artifact 或一批匿名执行实体。

## 4. Scope 的实际来源与当前明确缺口

`ScopeField` 用封闭 `kind`、准确 `sources`、`availability` 与 `gaps` 表达来源，
不接收任意 metadata 值。reader 从这些原定位取回实际值并验证类型。最少字段如下：

| ScopeField.kind | 可复用的实际原来源/读者 | 证据不足时 |
| --- | --- | --- |
| `ARGV` | `trace/run.json` 的原 `command`；`capture_coordinates.py:390–432` 将其核到唯一成功 exec；owned OS launch 的 target argv/nonce 可补来源 | 只保精确 argv 来源，不能由成功 exit 推出完整范围。 |
| `CWD` | 原 owned launch/collector 的 cwd 收据或有初态且完整的 OS cwd 历史 | 当前 `cli.py` 的 run.json 只有 command/returncode/wall_s，`os_capture_launch.py` 当前 intent/launch 也不保存 cwd；不能用分析时 `Path.cwd()` 补。没有原始证据则 OPEN；下次联合采集增加字段。 |
| `CODE_VERSIONS` | source snapshots、compiler/code witness、dependency source ownership 与 native provider revision | 区分源码 SHA、实际 loaded code、distribution/库版本；缺实际 loaded 对应不得用当前安装版本替代。 |
| `ENVIRONMENT` | 原 native collector 的 python/provider/configuration、call/operand collector 元数据及原环境收据 | `dependency_sources.py` 离线分析机的 environment 不能冒充目标完整环境；没有原值/版本的项 OPEN。 |
| `CONFIGURATION / INPUT_IDENTITIES` | 原 argv 参数指向的配置、文件读取/加载及内容身份收据、原输入清单 | 路径字符串不证明文件内容版本；未保存输入内容身份则 OPEN，不读当前同名文件伪造历史身份。 |
| `RUN_MODE / PROCESS_TREE / CAPTURE_INTERVAL` | 原 capture coordinates.run/process/thread/membership、collector window、OS birth/exec 证据 | 进程/线程未覆盖、采集起止不全分别记录；RunID 存在不意味着全进程树完整。 |
| `SOFTWARE_INTERFACES / HARDWARE_LAYERS` | 原 provider schemas/revision、profile selection、OS executable/filter/ABI/architecture、实际 device/allocation/queue 观察层级 | 指定 SOURCE_BODY/PROVIDER_GRAPH/PROTOCOL_INTERFACE/PHYSICAL_DETAIL 边界；utilization 不证明资源/内部活动全覆盖。 |

`Observability` 按 provider+domain 分别记录 `selection_source,window_source,loss_source,
coverage:COMPLETE|PARTIAL|UNKNOWN|CONFLICT,gaps`。读取器核 profile selection、丢失、预算、
进程/线程覆盖与 parser frontier；不能由 `status=CLOSED`、`dropped=0` 或脚本 exit0 单独判完整。
旧 strace filter 漏 unshare/close_range 的历史 capture 仍是部分观察，不得迁移新 owned launch
的选择资格给旧 Run。

## 5. required_relations 与四轴评估

`RelationRequirement(key,kind,selection,source)` 是**验收要求**，不是第二张依赖边。
`kind` 最少覆盖 `SOURCE_BINDING,ORDERED_INPUTS,ORDERED_RESULTS,STATE_PRE_POST,
CONTROL_COMPLETION,CALL_ACTUAL_FORMAL,CALL_RETURN_EXCEPTION,ENVIRONMENT_IDENTITY,
OWNER_SELECTOR,ALIAS_ESCAPE,VALUE_PROVENANCE,LOGICAL_MATERIALIZATION,RESOURCE_BINDING,
RESOURCE_WORK,READY_ORDER,LIFETIME`。
selection 只允许 `SUBJECT_INTERFACE/ALL_ORIGINAL_INPUTS/ALL_ORIGINAL_RESULTS/
ALL_ORIGINAL_STATE_PORTS/ALL_ORIGINAL_COMPLETION_PATHS/ALL_ORIGINAL_RESOURCE_USES` 等固定枚举；
不能用任意查询字符串筛掉失败端口。具体逐槽 obligation 由原端口枚举展开，重复 Use 保留。

规则从原 subject 类型/构造/调用和固定 expansion policy 自动生成，在看验收结果前固定。
SOURCE_BODY 的源码定义不因为 lowerer UNSUPPORTED 就改成 PROTOCOL_INTERFACE。
事先选为接口层的库/OS/CUDA 项仍要求完整有序输入/结果、状态前后态、alias/escape、
控制/失败、资源、ready/lifetime；接口变 OPAQUE、把未知效果改空集均不能通过。

每项 obligation 的 Assessment 必须恰有四个 `AxisResult`：

| 轴 | 固定检查内容 | 可以与其它轴不同的结果 |
| --- | --- | --- |
| `STRUCTURAL_ATTRIBUTION` | 原 subject 是否存在且限定唯一、归属 source/body/run/provider/resource、原分母成员对应 | source definition 可已归属，但 body/依赖仍 OPEN。 |
| `DEPENDENCY_CONNECTION` | 全 required_relations 的逐端口/逐路径原关系、当前 state/alias、跨片准确 endpoint | 不能以相同 local ID、retained ancestor、同时间或类型相等补边。 |
| `INTERNAL_EXPANSION` | 是否达到原 required_expansion，真实内部操作/子图是否存在；接口覆盖单列 | PROTOCOL_INTERFACE 通过时 SOURCE_BODY/PROVIDER_GRAPH 内部展开数量仍 0；不能称 native 内部理解。 |
| `RUNTIME_EVIDENCE` | 每条关系的来源模式、同 Run/进程/visit/slot、provider/schema 适用条件、漏采/未观测 | 静态未执行源码可标 `STATIC_SOURCE`，不计作实际执行验证；动态调用要求 `ACTUAL_OBSERVATION`。合同事实保持 `VERSIONED_CONTRACT`，未满足条件保持 OPEN。 |

每轴包含原规则生成的完整 requirement-key 集，以及每 key 的
`RequirementResult(status,basis_modes,evidence,conditions,gaps,cursor)`。status 封闭为
`SATISFIED/OPEN/CONTRADICTED/NOT_APPLICABLE`。OPEN/CONTRADICTED 必须有具体 Gap；
NOT_APPLICABLE 必须有来源与排除条款，不能从未观测、空数组或没有 adapter 推导。
不允许省略该轴、空 expected-set 自行判成功、只存一个字符串 reason。

结果不是输入自证：`checker` 指明准确 rule 版本、实现依赖 SHA、实际输入 receipts、检查范围与
检查收据。完整语义审核在相应 producer/发布 gate 执行一次；ledger 发布核对其准确输入、
producer、Run/范围、已审 requirement 和遗留条件后可复用已验收证据。普通只读 query
不为每项再扫全 raw，不要求新的 owned live 会话。已验收来源可标 `REUSED_ACCEPTED`，
保留原 gate/输入/范围及未重放说明；仅 caller 给一个 PASS/validated 布尔不能授予这种资格。
没有既有验收收据、hash/producer/范围不匹配或新增义务超出原范围时，相关项保持
`EVIDENCE_UNREVIEWED`/OPEN，按实际缺口在 producer gate 补验，不能由查询自行补值或补边。

## 6. 独立分母与不会丢项的自动 producer

同一 scope 至少保留下表的独立 domains，不能把 source/body-linked/native-known 子集当全集：

| domain | 机械枚举入口 | 必须保留 |
| --- | --- | --- |
| `SOURCE_DEFINITIONS` | `InventoryPartitions.file(fi)['definitions']` 的所有 source shards；使用 snapshot/context 和准确 `#/file/definitions/j`，有原 SourceDefinitionReference 时复用 | 全定义、无 graph 的定义、UNSUPPORTED、NOT_ATTEMPTED、未执行路径。当前公开报告 151 文件/2217 定义（header.summary.definitions）只是核对期望，不能混作 lowered body/graph 数；producer 从原数组数数，不硬编码。 |
| `SOURCE_CONSTRUCTS` | 同一 shard 的 `coverage/calls/implicit_invocations`；规则按 phase/AST construct 保留 | 定义时求值、模块/类、隐式调用、非执行注释空白的来源角色，不把空白变执行节点。 |
| `OBSERVED_PYTHON_CALLS` | 完整 source-invocations 的原 `invocations.jsonl.gz`（另保 orphan exits），每行 exact original InvocationKey/anchor | 当前报告 100438 调用全保留；body-linked、source-only、unresolved 都在，旧 842 关联不能成为新 843 动态证明。 |
| `DISPATCH_ATTEMPTS` | 原 dispatch metadata 的 attempts 与 bridge 的完整 group 分母；关联完整 dispatch inventory，见下文 schema 缺口 | 当前 39796 不能缩到 16、可解析 schema 或有正常输出的子集。BEGIN/OUTPUT/END 缺段、失败、无 marker、未知 operator 都入账。 |
| `NATIVE_ACTIVITIES` | `BundlePartitions.iter_records('evidence','instances')` 的全部原 native/provider instances | CPU op、runtime、kernel、copy、user marker 及未知活动，分别保原 role，不只挑与 dispatch 已匹配项。 |
| `OS_INTERFACES` | `OSInterfacePartitions` 的 observations/line_classifications/submissions/outcomes | 每条原接口及 parser/selection gap，ordinary return 不是 complete effects/ready。 |
| `OS_RESOURCES` | 同 reader 的 resources/handles/target_lifetime_events/processes/threads；同时保原独立 OS/proc/provider 清单 | 不能把现有已建 FD bindings 当真实所有 OS 资源；缺继承/stdio/共享表/短命资源仍形成集合义务。 |
| `PHYSICAL_OBJECTS_AND_RESOURCES` | native bundle values.objects/allocations/regions 及原 provider resource catalogs | 生命周期/对象/内容/placement/ready 分开；没有 Materialization 不删除 allocation 的覆盖义务。 |

所有计数都需区分：`declared_count`（manifest 声明）、`enumerated_count`（实际原成员）、
`membership_sha256`（按原限定键排序或明确原顺序的 membership 摘要）、`enumeration`
（DECLARED/PARTIAL/ENUMERATED）、`observation_coverage`（归档外是否完整）。只读 manifest
能生成 collection-level obligation 和未访 cursor，不能声称已逐条建账。

集合义务必须要求：每个枚举成员有适用条款，枚举/obligation counts 守恒，原 manifest
声明与实际成员一致，观察缺口已独立处理。declared_count 未知、预算中止、丢失、
未派工、缺 source/call/native/OS domain 或成员条款漏列都使集合 OPEN。
已知差额不能填成一批虚假的“unknown节点”；保留精确集合 subject、missing count（若已知）
及未访 chunk/range cursor，后续真实枚举再生成原成员 obligation。

当前 dispatch 的真实 schema 缺口：`trace/dispatch_import.py:289–303` 发布 schema1 bridge 的
`dispatches=len(grouped)`、BEGIN/OUTPUT marker `observations` 与 paths，但没有逐 sequence
的完整 group/END/operator 库存。`dispatch_sources.py` 发布的也是逐 marker association。
因此：

- 现档可从实际 observations 的 sequence 枚举有原 record 的成员；不能假设 1..N 连续，
  不能用 marker 数除 2，不能删除 end-only/无 marker 的 group。若无法证明该列表与 declared
  dispatches 全等，未枚举债仍在集合义务中 OPEN。
- 全39796自动接入 producer 应一次联合读取时发布 bounded `DispatchInventoryEntry`
  （原 sequence、所有已出现 BEGIN/OUTPUT/END locators、operator source、outcome、缺段/预算项）；
  它是原观察索引，不是新 Operation。完整性按原 attempts/group/phase counts 独立核对。
- 完整 group 库存可由新 `native-capture-batch` artifact 以显式 schema、bounded entries、
  原来源与计数收据发布，账本直接引用，不必修改旧 dispatch bridge。只有选择扩展旧 strict
  dispatch import report 时才需 schema2/capability，旧 schema1 reader 保原语义。
  不能从现有 summary 反造完整 entries，或单独重读一个小 prefix 冒充。

## 7. 已完成的最小切口与后继接线

本次已完成 source/call 原成员 producer 与查询；SOURCE_DEFINITIONS 为 2217/2217、
OBSERVED_PYTHON_CALLS 为 100438/100438 ENUMERATED。其它六域 declared/enumerated 分别为
SOURCE_CONSTRUCTS 122323/0、DISPATCH_ATTEMPTS 39796/0、NATIVE_ACTIVITIES 461242/0、
OS_INTERFACES 1067768/0、OS_RESOURCES 38307/0、PHYSICAL_OBJECTS_AND_RESOURCES
225630/0，均为 DECLARED 并保未访 cursor/debt。OS 38307 是 resource/handle/lifetime/process/
thread 表项之和，不能称所有真实 OS 资源的数量。八域 observation_coverage 仍为 UNKNOWN；
native provider 同 Run 资格未在此 ledger policy 审查，原 CATALOG_RUN_BINDING_UNREVIEWED 保留。
四轴只实核 102655 项 ORIGINAL_RECORD_MEMBERSHIP；依赖、内部展开、运行语义仍 OPEN。

后继全范围工作仍按以下顺序推进，不恢复新事实、不重跑 raw；第2项的其它域遍历尚未实施：

1. 输入准确当前 843 source inventory/composition、同 Run 的 capture coordinates、已存完整
   source-invocation/dispatch bridge/native bundle/OS fragment receipts 与固定合同/规则版本。
   输入缺任何必需 domain，仍建 scope 的集合缺失项，不提供空全集。
2. 源头只读 metadata/manifest 建立 collections 与 declared counts；有界流式遍历全部 source
   shards、完整 invocation rows、现有 dispatch observations、native instances、OS resources/
   handles/接口表，生成准确原成员 obligation。预算只限制本次遍历量，cursor 保持原全集。
3. 首次可机械验证 source/body membership、原记录归属、计数/端点 receipt；未运行原 public
   semantic validator/owned replay 的轴留 OPEN，不把字段中的 validated=True 当新证明。
   843/842 mismatch、dispatch inventory 缺口、CWD/input identity、state/content/ready 均逐项显式保留。
4. `query_obligation` 返回 exact subject、固定 mandatory/展开/relations、四轴 requirement 结果、
   原证据定位、未满足条件、missing/unvisited cursor。真实未建 body 可直接查询，不能只有汇总。
5. 随全39796 dispatch 接入产出的原 typed facts/新 dispatch inventory，按 obligation ID 增量评估；
   只更新 assessment，不把 ledger 结果反向写回图。按 scope revision 保显式新增/修订差异。

最低实施验收不是“OPEN数为0”：至少全部指定 domains 可查询，source 全定义与当前实际
calls/native/OS 原独立分母不丢失；任意未建 body、未连接调用、无 schema dispatch、未知 FD
container 都可定位到具体 obligation/原 collection 债。完整遍历与本次只遍历一部分分别报告。
如果新 producer 仅生成一张全 False 摘要或空 manifest，不满足该项验收。

## 8. 精确公共 API 与复核顺序

下列为后继目标 API（签名在原方案目录 `.pyi`），不是本次全部已实现的接口。当前可调用
`InputResolver.plan_scope/rows`、`produce_scope_ledger`、`publish_scope_ledger` 与
`ScopePartitions.query(id,scope_revision=...)`；固定 typed InputCatalog 不接收任意 callback。
语义评估、通用 qualified endpoint adapter 与 revision delta 尚无本次真实验收。


```python
plan_scope(inputs, policy, resolver, budgets) -> AnalysisScope
enumerate_obligations(scope, inputs, policy, resolver, budgets) -> Iterator[LedgerRow]
assess_obligation(scope, obligation, catalogs, resolver, budgets) -> CoverageAssessment
verify_ledger(scope, rows, catalogs, resolver, budgets) -> LedgerVerification
query_obligation(scope_revision, obligation_id, reader) -> ObligationView
write_ledger(scope, rows, fresh_output, budgets) -> LedgerReceipt
read_ledger(receipt, resolver, budgets) -> LedgerReader
```

`inputs/catalogs/resolver/policy/budgets` 均封闭类型，不接收 arbitrary callbacks 作为 trusted checker，
不允许 caller 写 `complete=True`、手选业务函数名单或 supplied IR 来缩分母。reader 仅开显式
catalog 中原 immutable artifacts；SQLite 可做派生 lookup，不提供写事实 API。

发布复核按依赖顺序：schema/重复字段/tag → artifact stored/decoded receipt → locator真实存在 →
scope/Run/process/版本一致 → 原 qualified entity/slot 类型 → 固定规则生成的 requirement 全集 →
原 producer gate 的准确语义验收收据（或本次必要的原 validator/owned protocol 审核） →
四轴逐项证据/缺口 → 独立分母守恒 → 修订差异 → 聚合。manifest hash 和 public graph
validity 只履行各自检查，不把 runtime identity/effect/ready 升级。

校验成本按三层记录，不能把 query 变成重复采集工程：

1. **原 producer/发布 gate**：对该准确不可变输入、producer 版本和声明范围做必要的完整
   语义检查；全39796 dispatch 接入时联合一次读取相关原档，复用已有校验，不逐 obligation 重扫。
2. **ledger 发布/独立 audit**：核独立分母、原定位、四轴和收据的适用范围。准确已验收输入
   可复用；新增/变更事实才对受影响范围执行必要验证。独立 raw replay 是显式 audit 模式，
   带预算和成本，不是每次 query 的默认前置。
3. **普通只读 query**：定位所需 ledger 行、原端点和精确已验收 gate，复用固定快照缓存；
   返回 evidence review mode、复用的原范围/producer/输入、此次未重放来源和遗留条件。
   可以只做局部 receipt/索引检查，不需再次打开全部 raw、重新构造全图或新建 live owned 会话。

复用键至少包含原 artifact 内容身份（stored/decoded按原格式）、producer及必要依赖 SHA、
schema/capability、Run/process/原namespace、已审范围/requirement-set及 policy 兼容性。
原静态 code/source 证明可按正规 ancestor 合同复用；旧 Invocation、动态 state、FD 连续性
和 ready 不能越 Run 或未经审查的新范围复用。query 缺少某项新资格只使该项 OPEN，
不抹掉其它原准确归属/字节证据。

`verify_ledger` 的结果为 INVALID（结构/receipt/身份冲突）、OPEN（未满足/未复核/未枚举）或
SATISFIED_WITHIN_SCOPE（仅在该 scope 的全部 mandatory obligation、四轴、scope字段、独立
collections 与 observation prerequisites 均满足时）。运行成本、读档范围与 evidence mode
分别返回。必需 NOT_APPLICABLE 必须有原 scope 排除证据；非必需 PHYSICAL_DETAIL 仍单列。
unknown=0 但 missing_count>0、必需 domain 不存在、未枚举/未生成 obligation、条件未复核，
全部必须 OPEN；不允许修改分母或将 UNKNOWN 改名来获得完成。

## 9. 需要修改什么，不需要修改什么

| 修改 | 原因及兼容边界 |
| --- | --- |
| 已新增 v2 公共类型/codec/source-call producer/query | record 为 scar.modeling-scope-record2，transport 为 scar.partitioned-modeling-scope-ledger2；只验收原记录成员，语义及其它域未完成。非执行 ledger 不迁移/替换原 IR。 |
| 完整 dispatch inventory 的显式发布 | 原 compact bridge 不保存所有 group/END/operator；新 `native-capture-batch` artifact 可独立发布完整库存及原来源/计数，直接被 ledger 消费。只有改旧 strict report 时才需其 schema2/capability，不强制迁移旧 bridge。 |
| 下一次联合采集的 run/launch scope receipt 版本 | 当前收据缺 cwd、完整 code/env/input identity；需在 owned launch/capture 时保存实际来源。旧档不能用分析机值补写；没有证据则 OPEN。 |
| 已新增独立 ledger bounded transport | data/index chunk 同时限制 stored/decoded 8MB 及1000行，只保存 obligation/assessment/reference；原 BundlePartitions TABLES 与 bundle schema保持。637块/4.27GB decoded 的实测重复编码成本须后续改进，不能以压缩后大小掩盖。 |
| 不需改 ProgramGraph/ExecutionModel/v2 身份或 SQLite权威 | 原事实表达与端点已经存在；缺 producer/关联时沿各自原 schema正式补事实，ledger不产生替代边。 |

root 已审核 v2 字段/身份规则、准确 catalog/freeze 与预算并完成一次真实 retained source/call 门。
后继最小接线仍是显式发布的完整 dispatch inventory：接准实际 native-capture-batch schema、
原 Run/计数/端点收据并逐成员生成义务；未发布前不得猜字段或缩到 prefix/scalar 子集。语义轴
只有准确 accepted-scope 资格审核后才可更新；PUBLISHED_MEMBERSHIP_ONLY/aggregate OPEN
不作 S2/S3/S4 或全程序完成声明。独立 source_revision_current 复核结论由其自身报告负责，
本账本结果不预先冒用；不另开长期数据库/DSL工程。
