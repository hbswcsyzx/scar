# Proposed — P：从原始来源派生物化生产义务

**Proposed／未实现／未冻结 records。** 准备基线为父代理指定的 clean `f71740e`；本轮仅阅读源码和既有设计，写本 ignored 文档。全仓运行期间未修改产品、测试或 docs，未运行测试、探针、采集、LeWM、GPU、安装或 git。本提案不宣称完整 M0–M2、自动运行时恢复、P/V 或 ready 已完成。

## 1. 先分清三种依赖，不能直接把候选边变成 AND

1. **逻辑 lineage 前提**：从准确 ValueGraph 的 ValueVersion.parent_versions／ProvenanceRecord.inputs→outputs 回查来源。它解释逻辑值怎样派生，不等于当前物化的所有物理 writer。
2. **当前物化生产贡献**：准确 source 输出／写效果确实建立当前 VersionRef、MaterializationRef 所需 selector 的某部分。只有来源、版本、placement、写范围及必要的覆盖／顺序对应成立，才列为当前 AND 内容贡献。
3. **潜在 invalidator**：可能改写同 backing／alias selector 的实际操作。OBSERVED_WRITE、OVERWRITES、外部未知写不自动产生所需版本；不能把它们当成功贡献或无关操作。

分类可分阶段仍 unresolved。同一物理事实可同时说明 lineage 与一个物化步骤；不能为分类整齐丢掉关系，也不能把所有候选 writer 强制 AND、或把所有旧 writer 直接删除。候选不确定性应输出分类／关联 gap。

## 2. 当前字段实际能给什么

| 现成来源 | 可直接复用 | 不能提升成什么 |
| --- | --- | --- |
| D ContentRead、StorageContent／EndpointContent、VersionRef／MatRef／RegionRef | 原消费者、current support、准确声明的内容和 selector；三种消费者 Resource／Host／Q | 一次引用传递不是内容读；Reference identity 不是永久内容版本；D 当前状态锚不是整个异步读取区间稳定性。 |
| ValueGraph provenance、parent_versions | 已校验的版本 ancestry、relation、输入输出列表 | TRANSFORM/COPY/MUTATE 不自带 byte selector transfer；父版本不是自动 AND 物理贡献。MATERIALIZE 可保留同逻辑版本，不能造逻辑自环。 |
| Materialization.producer／ProvenanceRecord.producer | 可选旧 OperationInstanceID 提示，可作为待连接来源端点 | 裸旧 ID 不是 core occurrence、WorkTicket 或准确 EEG artifact；None 是未给来源，不是无生产操作。 |
| EEG PRODUCES／MATERIALIZES／OBSERVED_WRITE／OVERWRITES／ALIASES | 准确 artifact 内可枚举的 typed 原事实 | endpoint 裸 Mat/Version/Region ID 不携 ValueGraph artifact；边没有 writer selector、native output ordinal 或 closed writer inventory。 |
| WorkEvidenceBinding／OccurrenceEvidenceBinding | 显式正向、多对多来源关联 | 没有匹配 pair 是 gap，即使同 owner 已给其它 pair；非成员不证明排斥，父 wrapper 关系也不自动补 child kernel 对应。 |
| ResourceOutcome.effect_frontier／protocol_result | 原 ticket 的实际结果声明、原 effect tuple 条目 | frontier 仍是 StateAccess 或 INVOKE 状态边界，没有 actual produced byte selector；COMPLETED 不等于整范围完成，FAILED/CANCELLED 不等于零写入或 quiescent。 |

### normalize_v2 的 inventory 只能先做来源对账

- `normalize_v2.py:106–110,485–496` 保留每个原始行的 line／raw_reference／sha256、解析状态、normalized 端点列表，以及整个源文件 hash、raw/accounted counts。它能发现“已提供的文件行未被对账”，不能证明文件之外没有丢采或未观察 writer。
- `:319–347` 对每次 snapshot 建 provisional logical/version/object/allocation；legacy storage/version/address 只作 hints，跨 snapshot identity 明确 UNKNOWN。不能因相同旧 token 合并 allocation 或内容。
- `:357–377` 对输出 capture 建 PRODUCES→ValueObservation；它可能只是返回已有对象或 view，不能自动算物理写。输入 OBSERVED_READ 明确 INFERRED，假设是 captured argument、actual read not proven；legacy writes 的 token 命中也没有 byte footprint。
- normalize 的 scope 明确 effects completeness not promoted、snapshot-scoped identity、no host/GPU clock alignment。`valid` 或 status=normalized 只证明格式投影成立。
- session 的 event_count／结束元信息，以及 call_operands 的 base_manifest／event attempts／dropped_events／io_failed 可作已有来源边界证据；后者属于该 Python operand collector，不能转成全部 Torch/GPU/external writer 的覆盖证明。

因此下一 P 门首先消费这些现成事实及成熟 provider 的原始写信息，不新增一套自制 producer。不新增 Tensor payload；shape、前缀样本或 fingerprint 不作为逻辑身份、完整写入或可替换物化证明。现有 normalized 数据不足时，正确结果是可回查的候选及确切缺口，而不是追加 COMPLETE FactRef。

## 3. 严格必要的新增连接，仅四类关系需求

这里定义必须接通的信息，不冻结一堆 class 或独立图。

### A. source endpoint 的显式 scoped bridge

引用准确 EvidenceEdgeRef／EvidenceObservationRef 及其原 endpoint，另一端是准确 VersionRef／MatRef／RegionRef／ObjectRef；解析两份已哈希图中的原行。ValueGraph artifact scope 必须明给，不能从裸 ID 文本相同、当前查询首个图、URI 或 op 名猜。

D 已给 denotation/read basis 的 bridge 可直接复用；没有覆盖到的 writer／alias endpoint 需要同样的明确关联。一个 source endpoint 指向多个候选 artifact 时保留歧义，不任选其一。已提供 FK／版本矛盾是 issue；缺图、缺 bridge 或部分来源非成员是 gap。沿用每 query 的 ExternalSnapshots，不另造 snapshot 框架。

### B. 原 source 写事实到实际执行和 selector 的关联

准确原 edge/native output、原 operation instance，接 D 的 exact WorkEvidenceBinding／原 core occurrence／原 AccessRef 或 INVOKE actual completion，以及 source-backed 写 selector。存在 work 才引用 WorkTicket；Host 写／初始化或 external establishment 使用真实原端口、EvidencePoint 和支持，未知保留缺口。

原 output/Use/effect/producer 保持唯一，不把解释后的写入再登记成一个 core producer。Footprint.INTERVAL 没有 byte 单位；只有明确坐标映射后才能接 RegionRef geometry。Endpoint selector 使用原 D typed selector／协议，不伪造 allocation。Mat.producer 的旧 ID 仍需明确 EEG artifact 与上述执行关联。

同一次 physical write 的多个来源边保留为该写的多个依据；按准确输出／effect／动态发生识别后才能归并。不凭“同 ticket”“同 Mat”“同 host”归并多个写阶段或 wrapper/child；无法确认是同一事实时保留歧义，不重复计 AND 或擅自去重。

### C. 上游来源 inventory 与本次查询 scope 的对账

需要能回查原 capture/run/window/artifact-set、边界、drop/gap、事件范围和 raw→normalized 端点映射的上游 inventory。它必须独立于本次提交的 Work／contribution tuple；不能由 ready 调用方自行挑 writer 清单。

先从源清单枚举原事实，再尝试关联 execution。删掉 contribution 而保留原 writer→仍有未对账项；再删 Work→原 writer 仍在，变缺 execution join；删掉整个来源 artifact→上游 manifest 仍缺该 artifact。若当前只能看到某个局部文件，没有上游闭合范围，则 inventory closure 保持 unresolved。

raw_records==accounted_records 只闭合给定文件的格式账，不闭合实际运行的写行为。ProviderCoverage/Completeness 字段可表达声明范围，但必须逐项核可解析的原 source 范围、缺采和 alias 边界；一个 COMPLETE+FactRef 不会使未知 external writer 或 graph break 消失。即使结构对账完整，native/runtime applicability 仍独立。

### D. actual produced 的原 Outcome 关联

生产成功支持须接准确 ResourceOutcome、该原 effect_frontier 的条目、原 protocol_result／native 输出事实，以及实际产生的 selector。新增的只是这些原事实的关联，不复制状态或输出。

short write／失败部分产出只能覆盖实际 selector；没有可解析结果映射时 frontier 不能算 whole。FAILED/CANCELLED 的已发生部分写应保留，剩余部分未满足；未给 Outcome 不是失败，可保留 Ordered 的成功／错误传播条件，但不能伪装 Observed Produced。

## 4. 建议验证与派生顺序

1. 从准确 D consumer 取得需求 key：scoped 内容版本、物化、storage／endpoint selector、实际读区间、原 state/reference 支持。Data intrinsic identity 与 Reference 当前内容关联分开；缺对应不会默认 whole。
2. 检查外部 snapshots、上游 inventory scope 和 A bridges；先保留来源端点全集及缺口，不从 execution 工作列表生成空宇宙。
3. 走 ValueGraph 原 ancestry 形成 lineage 视图；扫描原 source 的 PRODUCES／MATERIALIZES／OBSERVED_WRITE／OVERWRITES，并沿明确 ALIASES 与已知共享 allocation 扩展潜在冲突。未知 alias 不解释成 disjoint。
4. 逐项用 B 连接输出、effect、实际执行、selector；没有 exact pair 就保留 missing-join，不由已有其它 pair 排斥，也不由父子 op 自动补映射。
5. 有必要的 native 写/内容语义后，分出当前物化的内容贡献、lineage-only 和 possible invalidator。完整覆写+准确顺序+selector transfer 才可 kill 旧贡献；READ_WRITE、未知范围或未知顺序不推出 kill。历史事实保留在来源视图。
6. 用原 RegionRef 的预算化 byte-set union／containment 核内容覆盖；跨 artifact/alloc 无关系不能合并，不以 bbox 填 stride holes。Endpoint 未解析 selector 的覆盖保持未知。预算耗尽不是无 writer／无 overlap。
7. 用原 ResourceOutcome 与待设计的 actual-produced selector 关联分别记录已产生部分／缺失部分／成功条件待定部分，不声称现 D 已实现此关联。最后才为来源派生的必要贡献给出 AND 义务；同一贡献的匹配支持在 V 中 OR。P 不接受 caller required_contributions 删减全集。
8. 输出原来源 refs、已对账与未对账项、分类、贡献 selector、potential conflicts、条件和具体 gaps；source/runtime/transform authority 仍 false。Q root 是观察需求，不是物理 producer；无 work 的 Host/Q 读不为满足表结构 mint ticket。

## 5. 最小验收反例（Proposed，未执行）

| 情景 | 必须得到的结果 |
| --- | --- |
| 源仍有 writer，删 contribution；再删唯一 Work；再漏掉一个 manifest 中的 source artifact | 每次保留来源未对账／缺 join／缺 artifact；不能得到空 AND 已满足。 |
| 两个 VG 都有 mat:x，一个 EEG 裸 endpoint | 没显式 scoped bridge 只能歧义 gap；不能配到查询者偏好的图。 |
| T1→父A，T2→B；T1 的 basis 是 child B | 缺(T1,B)是 gap，不是已知排斥；同 host／parent 不能补 join，不能用于 ready 支持。 |
| 输出只是 view/返回原 tensor，normalizer 仍有 PRODUCES observation | 不算新 allocation/physical writer；保留捕获输出与实际写对应缺口。 |
| V0→V1 的完整独立覆写，另有 partial READ_WRITE／unknown selector 变体 | 前者有必要 kill 依据可不把 V0 物理 writer 加 AND；后者保留未覆盖依赖或冲突，不能猜。 |
| PRODUCES、MATERIALIZES、OBSERVED_WRITE 三边指同一个确切写事件；另有同 ticket 第二写阶段 | 前者保留多依据而不三计；后者不凭 ticket 相同归并。 |
| alias region 有洞或另一 writer 可能重叠，capture 同时缺 alias/external coverage | 不填洞，不因缺 writer 边认定无效化，不因 COMPLETE 标签关闭缺口。 |
| 同 buffer 被原地/NumPy 外部覆盖，Reference/Object 不变 | 旧 denotation/Mat/支持不能永久继承；current state/alias capture不足则具体 gap。 |
| FAILED 写[0,4)，需求[0,8)；CANCELLED 有实际部分产出；另一个无 Outcome | 首项 remainder 未满足；取消保留部分但不自动 quiescent；pending 不判失败也不宣称已产完整。 |
| 源只有 ORIGIN／输入来自外部，消费者是 Host 或 Q，无 work | 用真实初始/外部内容来源及观察关系或 gap，不造 ticket；Q 不是 writer。 |
| normalized 全行已记账，但上游采集有 drop、opaque、外部写或未捕获窗口 | 格式账可闭合，实际 writer closure 仍未知；不声称完整自动恢复。 |

## 6. 实施建议与界线

先实现来源枚举／bridge 对账和只读分类查询，证明删 execution 行不会缩小已知 source 候选；再收敛 selector transfer/actual-produced 关系。闭合 inventory 与 native profile 缺失时，允许条件性结构结果，但不宣布完整生产证明。P 后才接 V 的有效区间／visibility 和每贡献 AND/OR；本提案不新增 detector、backend、source lowerer 或性能结论。

## 读取源码 SHA256

- docs/M1_RESOURCE_READY_CONTRACT.md：b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f
- scar/ir/execution/content.py：1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e
- scar/ir/execution/content_validation.py：ebff98a37d99583fe1c2a103e25639bba1e536697bdcf60d9276474754d59a23
- scar/ir/execution/work.py：c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70
- scar/ir/execution/observations.py：8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882
- scar/trace/normalize_v2.py：7733fb9b02a8f657d2413a982a3203ee2d3dee7d532400118ca7b1902538b2a5
- scar/trace/session.py：c08a75b4bd2ee520b302373b406392c4f083a413a7b46692dcedff2dcdd3747a
- scar/trace/call_operands.py：9fe46732d636691c3bb66ed0c7c7d39696c1e1764966e760767dbc58e79f03a4
- scar/ir/v2/values.py：2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259
- scar/ir/v2/evidence.py：dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5
- scar/ir/execution/snapshot.py：e3b4e071a865f8cb94bcf732ae8b45688ee33243e03921c551dc76690621ed5b
