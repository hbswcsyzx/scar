# 完整程序声明模型：实体、关系、权威及自动生产链审计

2026-10-25。**代码审计完成；第一阶段整体建模仍 OPEN。** 本文服从
[FIRST_STAGE_MODEL_CONTRACT.md](FIRST_STAGE_MODEL_CONTRACT.md)，包含自动恢复与原入口全流程验收，
不采用旧 completion matrix 中把自动恢复移出第一阶段的安排。

结论：已有声明格式足够承载目前需要的规范结构、执行关联、对象/内容/物理表示与证据。
下一步应补现有记录的 producer 和跨片接线；不需要再造图 DSL、第二套 IR 或可独立写的
数据库事实。**有类型、有 codec、有局部 producer、有整次自动闭合是四个不同结论。**

## 1. 本次如何核对

完整阅读任务指定的六份模型文档，并沿下面各表核对 dataclass 原字段、构造/装配代码、
codec 的版本/分支、validator 和公开 reader/writer。另参考当前状态文档定位历史边界，
但以本工作树实际代码为准。没有运行目标、编译目标、重跑 lowerer、读旧 raw、改旧产物或建库。

[机器审计目录](../artifacts/analysis/declarative_model_audit_20261025/)包含：

- `audit.json`：本合同实体/关系、实现状态、权威与下一任务的人工核对映射。
- `typed_records.json`：`program/execution/v2` 中全部 **564** 个 dataclass 的原路径、行号及字段；
  包括辅助端点、查询结果和旧 codec 记录，不把这 564 类都称为执行节点。
- `constructor_sites.json`：生产目录中的定向 AST 构造点；与实际构造函数正文一起判断 producer。
  它不识别所有 alias/`replace`/解码装配，不能单凭“没有直接调用”证明不存在能力。
- `source_receipts.json`、`audit.py`：六文档与代码的 SHA、可重复的纯源码核对方法。

以下 `AUTO_PARTIAL` 指有可定位自动 producer，但范围有限；`SUPPLIED` 指声明/校验/查询已实现、
不等于原入口自动生产；`DESIGN_ONLY` 指当前合同要求尚无对应完整持久化/执行路径。
本审计没有重新验收历史运行数，文档中的旧数字不作为新测量。

## 2. 规范定义：程序到底由什么组成

| 合同实体及程序对应 | 原类与字段（事实来源） | 实际生产、读取、边界 |
| --- | --- | --- |
| CodeIdentity：源码快照、已加载 code 与编译身份 | `ir/ids.py:CodeID(source,qualname,line,column,version)`；`ir/v2/common.py:SourceVersion/SourceReference(path,fingerprint,span,atom_id)`；`v2/semantic.py:OperationDefinition(code_id,source_atoms,parent_id)` | `CodeID.from_code` hash loaded marshal；源码由 `analysis/program_lowering.py:prepare_source` 进入 snapshot。`program/source.py:LoweringMetadata.operation_links/value_links/use_links` 显式对应 core；不能把 SG `code_id` 一律当 loaded-code SHA。`analysis/source_body_access.py` 与 source invocation reader 核 exact receipt/code witness。AUTO_PARTIAL。 |
| Operation：一处求值/调用/读写/等待 | `program/model.py:637 Operation(id,behaviors,uses,results,accesses,effects_complete,terminator,callee,call_arguments,completions,invoke_arguments)` | `analysis/program_lowering.py:_Builder`、`structured_lowering.py:StructuredBuilder.make_graph` 自动构造；`source_heap_lowering.py` 使用原 builder/Use/world，无新 heap graph。`program/codec.py:dumps/loads` 和 `program/validation.py` 消费原字段。支持范围外返回具体 gap。AUTO_PARTIAL。 |
| ValueDefinition：定义结果、区域/块形参、精确 literal | `program/model.py:DataValue/ReferenceValue/StateVersionValue/LocalBindingValue/ProtocolValue(id,region,origin,...)`；`Origin=BlockArgument(block,index) / OperationResult(operation,index) / LiteralOrigin / ExactLiteralOrigin` | `Operation.results` 和 Value.origin 是受验证的同一事实两端；validator 117–141 行双向核对，不能分别改。有序消费为 `Operation.uses[j]:Use(id,value,role)`，重复值保留重复 Use。它们不是 v2 ValueSlot，更不是动态内容版本。AUTO_PARTIAL。 |
| StateLocation：可变位置/域 | `model.py:145 StateLocation(id,label,extent,stability)`；`StateVersionValue.location`；`StateAccess(location,before:UseID,after:ValueID,mode,footprint,full_overwrite,reference)` | 原 location **没有** owner/selector 字段；细地址由 `program/state_addresses.py:StateAddressRefinement(site,effects,coverage,protocol)` 附着到原 Access/Invoke state Use；`AddressEffect.owner/path/mode/stage` 引用原 reference/key/index Use。`environment_lowering.py` 和 heap lowerer 自动写 PARTIAL 地址，状态仍可为 coarse world。AUTO_PARTIAL，非统一实际位置/alias 已知。 |
| Region：入口、函数、控制/库子区域 | `model.py:775 Region(id,entry,blocks,exits,parent)`；`Block(id,arguments,operations)`；`ExitPort(name,kind,types)` | 结构包含与调用引用分开。`Terminator(kind,successors,condition,exit,values)`、`Successor`、`CompletionSuccessor` 保留 CFG/逐槽传递；branch/loop 不是 trace 展开。`analysis/program_composition.py:CompositionIndex` 按需加载原 body，包含不授予调用/数据流。AUTO_PARTIAL。 |
| ResourceDefinition/Requirement：可执行/承载接口及约束 | `program/resources.py:ResourceDefinition(id,kind,role,origin)`；`ResourceRequirement(id,owner,kind,role,capacities,relations)`；`ResourceUse(operation,requirement,definition,handle)`；`ResourceLocation(location,resource)` | `CreatedResource/ExternalResource`、容量与 SAME/DISTINCT/CHILD 约束已可声明/校验。资源状态仍在原 Location/SSA。`v2/contracts.py:ResourceRequirement(ResourceID,selector,...)` 是旧 SG/观察接口，不与上述 RequirementID 自动互换。整次 source→实际 resource requirement 自动恢复未接通，SUPPLIED/局部观察 producer。 |

规范图其余实体不是遗漏，而是原五支点的 typed 接口/关联：`binding_definitions/reads`；
`environments/function_entries`；`control_scopes/ports/exception_packets/pending_completions`；
`provider_envelopes/regions/bindings/native_boundaries/boundary_relations`；cleanup/handled-context；
resumable/frame-context；driver/create/association/drive/lifecycle/session/terminal-release；
state-address/literal/protocol/exception-match/call-effect/stored-value。这些原 table、精确类与字段
全部列于 `typed_records.json` 中 `ProgramGraph` 及其所属模块；不能把协议名当业务节点，
也不能因 supplied 协议可序列化就称源码已自动恢复所有协议。

## 3. 动态发生与对象环境：定义不是一次执行

| 合同实体 | 原类/字段与连接 | 已有 producer、尚缺的连接 |
| --- | --- | --- |
| Run/Process/Thread | `execution/coordinates.py:ExecutionRun(id,source)`、`ProcessInstance(id,run,pid,source)`、`HostThreadInstance(id,process,tid,source)` | `trace/capture_coordinates.py` 绑定真实 capture；`trace/os_resources.py` 复用坐标。实例 ID 与 pid/tid 分离。原三类没有通用 parent/start/end 字段，进程树/采集时段目前由 provider/coordinate reports 支持；通用完整生命周期与父子关系不能声称已经进入上述字段。AUTO_PARTIAL。 |
| RegionActivation / Invocation | `RegionActivation(id,region,process,entry)`；`ExecutionSegment(id,activation,host_thread,ingress)`；`BlockVisit(id,segment,block)`；`CallActivation(id,caller,activation,entry,completion,source)` | segment/visit 区分挂起恢复、同块多次发生。`program/call_edges.py:InvocationKey(process_id,thread_id,invocation_id)` 是实际 call recorder 键；不是自动等同 RegionActivationID。`analysis/source_invocations.py` 产生 qualified body/source 关联报告，并明确 `actual_formal_return_connected=False`，不能直接充数为 CallActivation。通用跨 body 实例调用 producer 未闭合。 |
| OperationOccurrence | `coordinates.py:OperationOccurrence(id,visit,operation)`；`model.py:OccurrenceEvidenceBinding(operation,LegacyOperationRef(artifact,instance),source)` | 引回原 OperationID 和 exact v2 evidence instance。`trace/native_protocol.py:_build_execution` 已自动构造有界 native occurrence；不是只有设计。全源程序逐操作发生尚未由 frame entry 自动获得。AUTO_PARTIAL。 |
| ValueOccurrence / UseOccurrence / ControlTransfer | `ValueOccurrence(id,value,origin:OperationOccurrenceID|BlockVisitID|RegionActivationID)`；`UseOccurrence(operation,use,value|Unresolved)`；`ControlTransfer(operation,successor_index,target)` | `execution/validation.py` 检查 exact producer/formal/activation 和 Use 原 value；`flow.py` 检查路径可用性。native window 写实际输入与 normal landing；循环每访/多调用不可合并。自动 Python operands/return 报告仍为条件路由，并未普遍物化本三表。 |
| ObjectInstance：实际引用身份 | `v2/values.py:189 ObjectInstance(id,scope,evidence,metadata)`；`ObjectBinding(object_id,value_version,relation,scope,...)` 是另外的内容关联 | `trace/reference_import.py`、`dispatch_import.py` 注册对象；native window 构造 `ValueDenotation(identity=ObjectIdentity(ObjectRef(artifact,object)))`。first/last observation 不是 birth/free；同对象不证明内容稳定。AUTO_PARTIAL。 |
| Environment：function/globals/builtins/defaults/cells | `program/environments.py:EnvironmentInterface(id,region,code_definition,members)`；`EnvironmentMember(role,reference,locations,cell_slot,cell_position)`；`FunctionEntryLayout(environment,parameters)` | `environment_lowering.py` 自动生成五角色前缀与 cell 端口，复用原 ReferenceValue。`analysis/callable_environment_import.py` 以 same-capture handshake 对接准确 `reference_port`/namespace；defaults 是 dispatch event-local snapshot，明确不能冒充 entry binding；内容、defaults 绑定和环境原子快照仍未证明。AUTO_PARTIAL。 |
| 动态 StateVersion | 仍为原 `StateVersionValue` 在这次 visit 的 `ValueOccurrence`；实际前/后选择由 `AccessRef`、`InvokeBoundaryStateEffect(state_input,post)` 与 `ActualCompletionState(successor_index,result_index,formal)` 表达 | 没有第二套动态 StateVersion 表是正确分工。`state_preservation` 等 query 不写新状态；声明路径可查不等于跨调用内容存活。不同原 body 的 coarse-world 必须有域/实例对应，既不能按同 ID 合并，也不能因不同 ID 认作 disjoint。 |

## 4. 逻辑内容与物理表示：不能用一个 Tensor ID 代替

| 实体 | 原字段/持久化路径 | 自动来源与限制 |
| --- | --- | --- |
| LogicalValue / ValueVersion | `v2/values.py:LogicalValue(id,semantic_type,...)`、`ValueVersion(id,provenance_id,parent_versions,semantic_type,control_scope,...)`；id 为 `(LogicalValueID,version)` | `ir/provenance.py:ProvenanceRegistry` 有 opt-in 生产 API；`trace/normalize_v2.py:snapshot` 对旧 capture 生成每次独立 provisional 根。后者没有跨 snapshot 内容相等，不能拿来替换较准的 native allocation epoch。native importer/物理 adapter 的逻辑内容链仍未接通。 |
| Provenance | `ProvenanceRecord(id,relation,inputs,outputs,producer:OperationInstanceID,equivalence,evidence,metadata)` | producer 指该 v2 actual instance，不能改写静态 Value.origin；来源 DAG 与语义 def-use 层次不同。`ProvenanceRegistry` 支持 origin/copy/transform/mutate；native/reference window 没有恢复整个实际内容 DAG。 |
| Allocation | `StorageAllocation(id,device,nbytes,allocator_token,lifetime_scope,metadata)` | `trace/native_memory.py` 与 `tensor_physical_import.py` 生产 epoch/大小/设备，pool 关联可用 `execution/resources.py:AllocationPlacement(allocation,pool,source)`。原指针不作身份；host allocator epoch 不自动等于实际 CUDA allocation。 |
| StorageRegion / View | `StorageRegion(id,allocation,offset,shape,strides,dtype,device,layout,metadata)` | `tensor_physical_import.py` 写几何；`canonical_tensor_layout` 仅在 pinned profile/revision 把 `torch.strided` 正规化为 `strided`。native window `_project` 保留源对象/allocation/region receipt 和原 ID，局部复制投影不是给同物理实体重新命名。几何重叠不证明内容/对象相等。 |
| Materialization | `Materialization(id,value_version,representation,device,region,producer,ready_event,validity_scope,evidence,metadata)` | 可表达版本的副本；`ready_event` 是旧可选字符串，不独自提供 typed ready/order 证明。`execution/work.py:MaterializationRef(artifact,materialization)`、production/validity/order 记录负责精确关联。native 实际 materialization/失效/ready 自动 producer 尚未闭合。 |
| occurrence→对象/内容 | `execution/content.py:ValueDenotation(id,value,identity,basis,source)`；`ObjectRef/VersionRef` 均绑定 exact ProviderArtifact | `content_validation.py:411–427` 仅允许 DataValue→DataIdentity、ReferenceValue→ObjectIdentity，State/Binding/Protocol 从 canonical 图推导；**不能给 Tensor ReferenceValue 直接换成永久内容版本**。Tensor 内容须经已有 ContentRead、状态与 placement/provenance 接线。 |
| 实际读取/生产及持续有效性 | `ContentRead(consumer,placement,effect,anchor,support,basis,source)`；`SourceEndpointBridge`；`WriteAssociation(stage,writer,production,placement,evidence,source)`；`OutcomeProduction(write,outcome,actual,rule,...)`；`EstablishedProduction(write,established,actual,result,rule,...)` | 现有 codec/validator/query 已实现；当前 native window 只写对象 denotation，不写这些完整链。`production.py:_validate_evidence_reference` 拒绝将 PROVIDER_REFERENCE token 当 content endpoint。`StoredValueWrite/Read` 附着原地址效果/payload/结果，不是新 heap；自动 source lowerer 尚未普遍填充它们。SUPPLIED。 |

完整 Tensor 数值无需默认保存。metadata、样本、同形、同地址、同 `_version` 都不能填补
上述内容链；没有来源时保留未解析项，不能通过每次分配一个 LogicalValueID 宣称已恢复 producer/use。

## 5. 资源执行与证据/合同/覆盖

| 职责 | 已有原记录及读写路径 | 当前边界 |
| --- | --- | --- |
| 实际资源与 handle 生命周期 | `execution/resources.py:ResourceInstance(id,kind,role,realm,origin,source)`；`ResourceRealization(definition,site,target)`；`RequirementBinding(requirement,owner,target)`；`HandleBinding(handle,target,start,end,support,rights,ownership,source)`；`ResourceAccessBinding(operation,requirement,handle,support,constraints)`；`ProviderResourceAccess` | `trace/os_resources.py` 写真实资源、handles 和 unknown 端点；`os_fd_table_contexts.py` 等 reader/refinement 核 coverage。fd 复用/CLONE_FILES/漏选 syscall 的连续性不足必须保持 OPEN。v2 GPU/stream ResourceRequirement 观察不能自动升级成此处 ResourceInstance/RequirementBinding。 |
| enqueue/工作/返回/资源完成 | `work.py:WorkSubmission(id,origin,executor,scheduling,dependencies+coverage,effects+coverage,materializations+coverage,retention,protocol,source)`；`ResourceOutcome(ticket,kind,observed_at,protocol_result,effect_frontier,frontier_coverage,quiescence,source)`；`WorkQuiescence`；`WorkRetention` | OS `OSResourceFragment.iter_work_records` 已逐条构造本原类，并写 UNKNOWN dependency/effect/retention/executor。syscall return 可为 COMPLETED，但明确不是 device quiescence。native Kineto `SUBMITS_WORK` 只是 provider association；未自动填满 typed WorkSubmission/ready 链。 |
| queue/event/wait 与 happens-before | `order.py:QueueOrderProfile/RecordedPrefix/EventRecord(event,marker,captured,generation,observed_at,...)/QueueWait(ticket,record,event_access,selection,...)`；`work.py:QueuePrefix` | 已有声明、codec 和 order/validity query；profile/generation 与 native protocol 必须有证据。不能按时间邻近、一个 correlation、host 返回或 event 字符串补边。SUPPLIED，完整 native ready/order producer 未接通。 |
| 原档与 provenance | `program/providers.py:ProviderArtifact(uri,sha256,size_bytes,schema)`、`ProviderFactReference(artifact,locator)`；`ProviderEnvelope(provider_version,source_revision,capture_mode,capture_scope,sources,stages,conditions,coverage,collection)` | `execution/common.py:FactSource` 允许原 fact 或 MissingEvidence；v2 `EvidenceClaim(kind,references,scope,confidence,assumptions)` 与 `ProofClaim(status,required_next)` 区分观察、声明、推导和证明。exact hash/record locator 证明原字节，不证明运行语义完整。 |
| 保留合同与观察根 | `v2/contracts.py:ContractDefinition(required_outputs,facets,assumptions,evidence)`、`EffectSummary` 的各域 completeness；`MeasurementRecord`；`execution/observations.py:ObservationRequirement(contract,target,protocol,source)`、`ObservationRoot(actual,interval,anchor,support,source)` | `execution/composition.py:CompositionScope` 是 query 输入，不能当全程序 AnalysisScope。合同/效果/测量不是新的执行步骤。SUPPLIED；原入口最终输出、外部写/结束须自动绑定实际根。 |
| 第一阶段验收覆盖义务 | `program/inventory.py:CoverageEntry(source,owner,phase,ast_kind,status,reason)`、`BodyInventory(status,graph,metadata,reason,construction_operations)`；provider Coverage、source-invocation frontiers、OS classifications | 这些分别记源码构造、body、provider、关联和 OS 范围；**不是合同要求的统一 CoverageObligation**。目前没有含稳定 obligation ID、来源、subject、必需关系集、required_expansion、mandatory 的完整 AnalysisScope/ledger 类型与整次 producer。此小型非执行验收记录仍是 DESIGN_ONLY；不得把 StorageCoverageResult 的 byte coverage 误当全模型覆盖。 |

## 6. 现有声明格式和真实公共读写路径

| 内容 | schema /版本 | writer → reader 与校验职责 |
| --- | --- | --- |
| 规范 core | `scar.program-graph`，`program/codec.py` 最高 28，读 1–28 | `dumps` 先 record+graph validation，再按实际 capability 选最低相容版本；`loads` 严格字段/tag/profile 并校验图。不能把常量最高版本当每份产物的实际版本。 |
| 单快照执行关联 | `scar.execution-model`，最高 9，读 1–9 | `execution/codec.py:to_dict/from_dict/dumps/loads` 用固定 `$record`/fields 词表，按 populated tables 选择版本；codec 验记录不证明 runtime。`execution/validation.py:_analyze` 将 ProgramSnapshot 的 schema/hash/size/version 与原 program_dumps 字节核对；`snapshot_for` 只接受真实 ProgramGraph。不能传 composition manifest/空根冒充全局 snapshot。 |
| v2 分层图/组合 | semantic2、values1/2、evidence3/4/5/6、correspondence1、bundle2；完整 schema 名为 `scar.ir.v2.*` | graph `to_dict` 与 `v2/codec.py:semantic_from_dict/values_from_dict/evidence_from_dict/correspondence_from_dict/bundle_from_dict/bundle_from_json` 对接；ValueGraph 有对象时写 v2，否则保 v1。EEG 按 provider/object capabilities 选版本；`IRBundle.assert_valid` 验跨图端点。OIR 保留兼容，第一阶段不需新建 optimization graph。 |
| 来源 body wrapper | `scar.source-program`，1–5；`scar.program-inventory` 多 profile | `analysis/program_lowering.py:SourceProgram.to_dict/read_structure/from_dict`，内含原 graph/metadata/semantic/semantics/control；SourceLanguageOverlay 引原 OperationID/ValueSlotID，不复制 producer。`program_inventory.py` 与 CLI 的 inventory 现有 frame/structured/environment 可选，默认 frame；contract 中“仅 model-program 可选 structured”的旧起点已落后代码。 |
| 原图分片/namespace | `scar.partitioned-program-inventory`1/2；`scar.body-construction-checkpoint`1/2 | `analysis/inventory_partitions.py:publish_partitioned_inventory/InventoryPartitions.checkpoint/body_record/body_field_locators/qualified_reference`；源 revision 有显式 parent/new receipt，不能静默改旧 body。qualified key 为 **namespace(artifact+representation+record pointer+body) + kind + 原 local_id**，不是路径或 ID 文本。 |
| v2 有限分块 | `scar.partitioned-ir-bundle`1 | `store/bundle_partitions.py:publish_bundle` 遍历原表 record，先 bundle.assert_valid；`BundlePartitions.iter_records/selected_records` 验 chunk hash/字节/ordinal。reader 不重新组成全 bundle、不自动获得语义全局验证。只支持 SG/EEG/Value/Correspondence；拒绝 populated optimization/source_semantics，不能宣称所有公共输出已迁移。 |
| source 组合/实际关联 | `scar.program-composition`、`scar.source-invocation-bindings`、`scar.source-invocations`、operand/dispatch/environment 报告 | `program_composition.py:compose_program/CompositionIndex` 与 `source_invocations.py`、`call_operands.py`、`dispatch_sources.py` 形成限定引用/条件路由。它们本身不是一个多快照 ExecutionModel。原 JSON/gzip 仍由现有 reader 读取。 |
| OS typed fragment | `scar.os-resource-fragment`1/2；`scar.partitioned-os-resource-fragment`1 | `trace/os_resources.py:import_os_resources/publish_os_interfaces/OSInterfacePartitions`；schema2 复用原 work/resource 类，bounded chunks 不另造 OS IR。读取存储成功不授予 FD 连续性、完整效果或 ready。 |
| 可丢弃查询索引 | `scar.readonly-program-graph-index`1，SQLite | `store/graph_index.py:index_inventory`→`GraphIndex`。DDL entity UNIQUE(namespace,kind,local_id)，relations 保 pointer/ordinal/qualifier；`_index_body` 明确投影 producer/Use/StateAccess。reader 用 `mode=ro`/`query_only`，producer/consumers 仍回到原 locator；`record_coverage` 保 NOT_INDEXED。DB 删除重建不丢规范事实，PUBLISHED 不等于全模型 PASS。 |

## 7. 重复权威审查

没有理由再把文件事实搬成一套可独立改写的数据库图。已有看似重复处应这样解释：

1. **`Operation.results` ↔ Value.origin**：同一规范事实的互检端点，必须由同次 producer 一致构造；
   validator 拒绝冲突。Use 仅在 Operation.uses 拥有；索引 VALUE_USE/OPERATION_USE 是投影。
2. **SG OperationDefinition/ValueSlot 与 core Operation/Value**：来源/接口与执行语义投影，
   通过 LoweringMetadata/SourceReference 连接；SG slots 不再充当另一套任意 SSA。
3. **EEG OperationInstance 与 core OperationOccurrence**：原 provider 观察与 canonical occurrence，
   由 OccurrenceEvidenceBinding/NativeBoundary 原端点关联；不能按时间或名称合并身份。
4. **v2 provenance.producer 与 Value.origin**：前者是内容转换的实际来源，后者是规范定义。
   关系必须显式桥接，不把两个 ID 相等或两张表独立维护当一致性。
5. **StateAccess / address refinement / StoredValueWrite/Read**：前后 SSA、地址选择与 payload
   是分层附件，不是三套状态。任何 alias/read/source query 都应回原 site/Use/completion；
   不得新增 `last_writer` 或字符串 world 表来覆盖原状态。
6. **core resources 与旧 v2 ResourceRequirement**：两类同名不同 ID/职责，当前确有集成缺口；
   应写 ResourceRealization/RequirementBinding/ProviderResourceAccess，不把旧 selector 直接升级为实例。
7. **旧 `scar/ir/graph.py` 的 `scar.program_graph`1**：K/Σ/A/R/Q/M 兼容证据容器；
   MODEL.md 后半所述 last producer/record_order 不成为 typed core 的第二事实来源。
8. **源 wrapper / source-language overlay / 分片投影 / SQLite**：保存或索引准确原记录；
   revision 必须显式快照迁移。两个独立可编辑 producer/use/state 表是禁止的新设计。

## 8. 完整建模仍缺的必需关系（不能被记录数替代）

| 关系 | 现成承载点 | 仍需实际闭合的内容 |
| --- | --- | --- |
| 来源→定义→发生 | SourceReference/LoweringMetadata、qualified body、OccurrenceEvidenceBinding | 当前 source snapshot 与同 Run 的全部 actual 调用重新绑定；缺 body、未执行构造、动态 loader 均保留分母。 |
| actual→formal→own result→return/exception | 原 call/invoke Use/completion、CallActivation、UseOccurrence、ControlTransfer | 原 Python recorder 的参数/返回/环境条件路由还未普遍变为 exact typed occurrence 链；retained ancestor 不是直接 Python→ATen callsite。 |
| caller state→callee entry/post-state | StateVersionValue occurrence、InvokeBoundaryStateEffect、canonical call/state ports | 不同 body 的 coarse world 域/实例关系、选中 N/R 与当前完整状态 tuple；独立原 ID 不证明无干扰。 |
| reference→owner/selector→实际读写 | EnvironmentInterface、AddressEffect、ObjectIdentity、StoredValueWrite/Read | 引用/对象生命周期、descriptor/index/cell/global 的实际协议与 alias 范围；PARTIAL 地址不变成 complete effect。 |
| 内容来源→版本→物化→消费 | ValueGraph、ContentRead、SourceEndpointBridge、Write/Outcome/EstablishedProduction | native Tensor 仍是 reference/geometry；实际内容产生、mutation/foreign writes、copy/transform、失效、完整有序 consumer 没有整次自动链。 |
| operation→work→executor/handle | ResourceAccess/ProviderAccess、WorkSubmission、WorkEvidenceBinding | native kernel/copy/runtime 与 core operation 的真实关联及 pool/device/queue/FD 对应；OS work 有 UNKNOWN executor/effects，不能当无依赖。 |
| enqueue→ready/wait→lifetime | ResourceOutcome/Quiescence、QueuePrefix/EventRecord/QueueWait、Retention、TargetLifetimeEvent | 具体协议、事件代次、正确资源和同 Run 时序；host normal 与 GPU completion、syscall return 与 visibility 分开。 |
| 全范围覆盖与验收 | 现有各分母/原 receipts + 新的小型验收 ledger | AnalysisScope/mandatory/required_expansion/必需关系集还须统一记录；结构归属、关系闭合、内部展开、运行证据四轴分别核，必需 OPEN=0 前第一阶段不完成。 |

有界 native bridge 是本轮核对中值得保留的实际进展：`trace/native_protocol.py:_build_program`
已经用原类型建立 ordered native input/output、Normal/Raise 和 opaque world；`_build_execution`
建立真实 visit/Use/对象 denotation；`bind_native_protocol_window` 经过原 codec/validator 与
owned replay。它的 hard window 是 sequence 1 起、最多 16；输出明确
`content_versions_established/complete_state_effects_established/alias_completeness_established/resource_readiness_established=False`。
旧 NATIVE_VALUE_CHAIN_AUDIT 中“没有 NativeBoundary 自动 constructor”已不再准确；
“native content/materialization/ready 全链未闭合”仍准确。本次未重跑这个窗口，也未授予其整次运行验收。

## 9. 下一项最小实际落地及验收

建议下一步只扩展现成 `bind_native_protocol_window` 的一个缺口：**自动保存该有界窗口内
真实 boxed builtin scalar 的实际输入/输出内容，使现有 DataValue occurrence 接入原
ValueGraph / ValueDenotation；不改 Tensor ReferenceValue 的身份含义。** `replay_interfaces`
已经保留每个 boxed leaf 的 `path/type/value`，当前 `_build_execution` 在非 Tensor 分支直接
continue；原数据无需新采集就可补这一条真实跨层 producer 链。它验证的正是“已有声明格式能否
表达程序里实际产生的值”，不会扩展为逐业务函数手写协议。

具体验收条件：

1. 通用按原 provider slot 类型/路径选择精确 `None/bool/int/float/string`，逐项检查类型与有限值；
   unsupported container/type 形成原具体 frontier，不能省略分母或由文本转换猜值。
2. 原 Operation/Value/Use/Invocation/NativeBoundary ID、端口 ordinal、ProgramSnapshot 均保留；
   用该次确切 v2 OperationInstance 作为内容 Provenance producer，并绑定 exact output port。
   每次 occurrence 的 LogicalValue/Version 独立建立；相同 scalar 不跨调用自动合并，input 也不倒写为 output producer。
3. 持久化复用原 `ValueGraph`、`ValueDenotation(DataIdentity(VersionRef))` 及可复核的 provider
   原值证据；准确内容观察可用原 LiteralEvaluation 机制，但不能改静态 LiteralOrigin 伪造恒定值。
   若现有 `NativePortEvidence` 仅支持 ObjectIdentity，应在同一 owned protocol 中显式新增 scalar
   capability/检查分支；不以 caller 提供的 `verified=True` 或普通 metadata 绕过 validator。
4. 公共 codec 回读；原 raw slot→canonical slot→ValueOccurrence→VersionRef→provenance producer
   五段有独立复核。换 Run/body/artifact、错 ordinal、错输出、重复 same-site occurrence、错误 builtin 类型
   必须拒绝或保留具体 gap。原 Tensor 引用正例与其 content/alias/ready 未证明状态保持。
5. 只读原有界原档/选中 chunk，输出成本、实际访问范围与未访问分母；无目标运行、无新 DSL/IR、无全量重导入。
   通过只报告 scalar 内容子门，不能称 source/call/state/Tensor/resource/whole stage 已完成。

随后按上表的实际断口推进 Tensor 状态/内容、调用与资源连接；统一 scope/obligation ledger
必须覆盖这些仍 OPEN 项，不能因为先做一个可落地子门而降低第一阶段合同。
