# 跨 fragment 的静态／动态连接：最小持久关系方案（只设计）

2026-10-26。**单snapshot是现ExecutionModel的硬边界；新增一层严格typed跨片关系，引用原端点与原证据，既不合图，也不复制producer/Use/StateLocation/资源身份。** 这次接新GPU work，取消初稿旧seq2331查询；旧稿留PLAN.query_only_initial.md。未改生产、未读work/EEG大块、未运行门。V2/Memset未消费，下面实际依据是Root44866已通过的V1。

## 1．已核实的真实连接与唯一尚缺的owner证明

GPU `attempt01/result/manifest.json` 的Run为 `capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0`，coordinates SHA `4d266b…` 与现source/native导航输入的坐标payload相同（logical URI仍各自保留）；V1有23000个qualified single activities/90shards，非全依赖闭合。

manifest实际首shard为 `shards/000000.{work.jsonl.gz,evidence.json,receipts.jsonl.gz}`。只核source-receipts压缩17780B的SHA并读首line：ticket `native-activity:8011554b07f2a8d8c7c75719244d77754ab77a731667b608e07adfd5a5224ef2` → projection_index0 → 原EEG ordinal310463，即 `evidence/instances/000063.jsonl.gz` line5115 `/record` → Kineto traceEvents/385137。未宣称该receipt gzip完整decoded SHA已核。

现 `native_work_protocol.make_records:62–83` 已生成原WorkSubmission / WorkEvidenceBinding / WorkQuiescence：binding准确指projection EEG artifact + 原OperationInstanceID；origin是ExternalWorkSource，executor/queue/effects/dependencies/materializations/retention保持UNKNOWN。`native_work_bridge._check_original:289–324`明确GPU `parent=None`；首receipt没有host owner。因此不能把parent或最近CPU事件当submit。

**owner不是完全无现成事实**：`trace/native_import.py:417–428`已有原EEG `SUBMITS_WORK(runtime→GPU)`（唯一正correlation、同capture/provider条件），`:432–460`已有 `PROVIDER_SCOPE_ASSOCIATION(CPU→activity)`（CUSTOM0 linkedActivity，非submission/parent/order）。缺的是：把选中GPU的这些**原edge准确locator**、其host端与native ExecutionModel原OccurrenceEvidenceBinding的同一legacy端点核回，再接source context的持久typed关系。当前小receipt不足以确定首ticket是否有唯一该路径，方案不预填owner。

## 2．最小字段：端点只限定原身份，关系只新增跨片事实

保旧ExecutionModel1–9及其单ProgramSnapshot；不能把snapshot可空来绕静态FK，也不以858 composition充scar.program-graph。`validation.py:544–547`核原图schema/SHA/bytes；`call_validation.py:295–313`要求本图callee Region，故跨图不能塞旧CallActivation。

| 记录／字段 | 封闭合同与复用 |
|---|---|
| **静态端点** | 原SourceDefinitionReference/QualifiedSourceBodyReference或准确ProgramSnapshot+namespace+既有RegionID/OperationID/UseID/StateLocationID；graph locator保SourceArtifactLocator的原logical URI、stored/decoded SHA/bytes/pointer。未执行分支仍在原静态图，不从动态出现次数裁掉。 |
| **动态端点** | 原QualifiedOccurrenceRef(execution artifact,occurrence,binding)继续唯一权威；新增WorkTicketRef(locator指原work行/submission + 原WorkTicketID)、InvocationRef(原invocation fact + InvocationKey + Run/process)。GPU EEG端用现LegacyOperationRef/准确原locator；不重mint任何实体ID。 |
| **WorkActivityProjectionLink** | `work_binding:原行/binding locator; original_activity:原EEG locator+OpInstanceID; projection_receipt:原receipt行; run/process`。仅核已有binding到原表示的对应，不复制一份WorkEvidenceBinding权威。 |
| **WorkHostRelation** | `work:WorkTicketRef; host:QualifiedOccurrenceRef或原LegacyOperationRef; activity:上述原GPU端点; kind:{SUBMITTED_BY_RUNTIME,PROVIDER_SCOPE_CONTEXT}; evidence_path:非空原EEG edge locators; source:原facts; run/process`。各kind核固定原relation与方向；scope关联绝不升级direct submit/within-call。无唯一host时保typed MissingEndpoint及具体未核集合/计数，不删work。 |
| **InvocationStaticBinding** | `invocation:InvocationRef; code_capture:原CodeCapture fact; code_source:原CodeSourceLink fact; definition:SourceDefinitionReference; body:原qualified Region可缺; witness:原CodeWitness receipt`。CodeVersion复用CapturedCode.key及完整descriptor/CodeSourceLink+SourceSnapshot/编译选项/源body版本，不造新CodeVersion身份；native静态版本沿ProgramSnapshot+provider固定revision。 |
| **NativeSourceContextRelation** | `native:QualifiedOccurrenceRef; invocation:InvocationRef; retained_association:原dispatch/source行facts; kind:RETAINED_SOURCE_CONTEXT; source_binding:上行引用`。复用现NativeContextResult的确切语义，不能改成direct CALL。真正跨图call后续另有精确caller actual/formal/return/exception/world端口证据时才准入，不以本行代替。 |

每条relation稳定ID由kind+完整qualified端点+原证据locator的规范序列导出，状态/评估变化不换ID；不同logical namespace不可按同SHA合并。关系包只存原artifact目录/typed跨片关系与覆盖debt，SQLite/按ID反查只是可删重建索引。原静态/动态/逻辑内容/资源图继续各管原事实，不生成平行world状态。

## 3．producer→validator→query：最小实现边界

建议5文件：新 `ir/execution/fragment_relations.py`、strict `fragment_relations_codec.py`、`analysis/fragment_relations.py`、有界分片 `store/fragment_relations.py`；现 `analysis/source_native_composition.py` 仅把QualifiedOccurrenceRef下移并同class re-export以免IR反向依赖analysis，旧query合同不放宽。新独立wire v1，不改ProgramGraph或旧ExecutionModel wire。

自动producer沿manifest真实分母/首可查shard，不手填函数/seq：先复用WorkEvidenceBinding+projection receipt；再从原EEG显式SUBMITS_WORK/PROVIDER_SCOPE_ASSOCIATION查证据路径，对接native原evidence binding并保该局部snapshot，最后通过现native-context索引按**实际找到的dispatch sequence**接source Invocation/CodeSourceLink/静态body。source858只是静态版本目录；同Run还须以source report/coordinates核，不能把旧Invocation搬到新Run。未有typed body时保原静态definition与body expansion debt；所有静态分支继续可查。

validator核全部receipt/原URI/namespace/成员、binding真实producer、Run/process、投影与原instance/raw-reference相等、每个原edge关系/方向/条件、native occurrence→静态operation归属、完整code/source/body版本匹配及原source association行；复用已验收不可变artifact/producer/scope资格，普通query不要求新live acquisition或每次全raw重扫。不能用serialized verified=True/PASS自证。独立拒同Run错GPU producer、错host或改scope为submit；保原provider历史binary/source与ready/效果/cleanup债务。

## 4．一次新GPU真实验收与成本边界

门只消费该V1真实首work shard（256行，declared decoded2175412B）/projection284517B/source receipt290706B、原EEG准确路径、同Run选中native fragment/source上下文，发布并普通读回新typed关系，再从原WorkTicket查询→GPU EEG→原host关系→native occurrence→source Invocation→CodeVersion/静态definition/Region/Uses；source未展开分支不要求动态假 occurrence。必须至少得到一个机械选取且证据完整的真实host路径；缺项逐record可查，不能把relation包PUBLISHED当统一模型完整。

**当前没有按GPU ID反查原edge的现成索引，不能承诺小query自动找到owner。** 原bundle metadata有1170339条EEG edges/81chunks，单遍declared stored36984846+decoded1287320853B；instances全表另为76212360+1200966077B。设计不读取它们。后继应一次构建按原EEG端点/关系的可重建locator索引（流式、同receipt、无raw），再只按ordinal读取所需chunks；没有该索引/已验原端点资格就先按准确read-plan核预算，不发64MB必过的假门，也不把为每body重扫全链作为接口要求。Root授权实施前以实际必要roots/chunks定完整总预算与中断条件；本轮不运行producer/index/query，不抬任何旧门预算。

验收保V1 46142 candidates与23000 qualified活动独立分母、其它类别/host未定项明确OPEN；不授结果成功/child completion/资源ready/对象身份/世界状态传递。新关系层是将现有事实连为程序模型的一步，query-only结果及关系发布本身都不是统一模型完成。
