# R2.3 production 与 required-contribution 闭合审查

## 结论

按 `ValueGraph` 与精确外部 `EvidenceGraph` 派生 writer 宇宙，是比直接信任消费者提交的 `required_contributions` 集合更稳妥的 R2.3 起点。**现有字段仍不足以声称这个宇宙闭合或已关联到实际 Work。** R2.3 可以给出逐贡献的结构化条件/缺口；在数据 denotation、EEG↔ValueGraph 的 artifact-scoped join、以及 scoped writer/alias coverage 未闭合前，不得给无条件 `ready=True`。

特别要分开三个东西：

1. **logical lineage prerequisite**：计算某个 `ValueVersion` 时依赖哪些版本/转换；
2. **physical materialization production**：目标 `Materialization` 如何得到该表示；
3. **possible invalidator**：同存储 region 上可能覆盖/改写目标的 writer。

不能把所有 `parent_versions` 或历史 alias writer 平铺成当前内容的 AND 贡献；也不能因它们“历史”就删除。仅在精确版本关系、selector/几何和必要的顺序/覆盖依据表明已被完全替代或不相交时才排除。可能重叠但不能判定的 writer 保留为 conflict/closure gap。

## 现有来源及硬边界

| 来源 | 可复用事实 | 尚不能推出 |
|---|---|---|
| `ValueGraph.ValueVersion` / `ProvenanceRecord` | 版本父边、provenance 输入/输出、relation、可选旧 `OperationInstanceID` producer；ValueGraph validator 保持版本祖先与 provenance 互相一致。 | `MUTATE` 输入不是自动的最终内容 writer；记录没有写入 selector/footprint 或全量生产覆盖。`evidence="Observed"` 是字符串。`UNKNOWN`、无 producer、缺 lineage 均不能当空集。 |
| `Materialization` / `StorageRegion` / `StorageAllocation` | exact materialization→logical version→可选 region→allocation；shape/stride/offset/dtype/device 可作共享 geometry 输入。`MaterializationRef` 已按 artifact digest/schema/size + ID 精确定位并由 work validator 加载 ValueGraph。 | `producer: v2 OperationInstanceID`、`ready_event: str`、`validity_scope: str` 不接新 WorkTicket/Occurrence，不能证明 data production/ready。现有 ValueGraph 只验证 allocation bounds，没有区域交叠或 contribution selector 算法。 |
| EEG `EvidenceRelation` | typed edge 家族包括 `PRODUCES`, `OBSERVED_WRITE`, `OVERWRITES`, `MATERIALIZES`, `ALIASES`；可从确切 artifact 中枚举候选事实。`ValueObservation` 的 version/materialization/operation 也是可复用原始事实。 | 不能只筛 `PRODUCES`：写/覆盖和 alias 可能使旧内容失效，`MATERIALIZES` 是物理表示关联而非自动 logical producer。EEG `EvidenceEndpoint` 只携带裸 typed ID；graph 没有 writer-inventory completeness 或 ValueGraph artifact 外键。`EvidenceClaim` 的 OBSERVED/PROVEN 不闭合捕获范围。 |
| Execution R1/R2.2 | `WorkSubmission.effects` 指原 `AccessRef`/`InvokeBoundaryStateEffect`；`materializations` 指 artifact-scoped `MaterializationRef`；Outcome 保留 status/frontier/quiescence；queue event generation、captured prefix 和 wait record 有准确代次。`OccurrenceEvidenceBinding` 可映射一个 core `OperationOccurrence` 到 artifact-scoped legacy operation instance。 | State effect 不是 Tensor/value production；Outcome frontier 也只含原 state effects。一个 core occurrence 可关联多个 WorkTicket；不能由 occurrence 相同或 materialization 列表相同猜具体 ticket。现 validation 已对 legacy materialization producer 留 `materialization_producer_scope` gap，且每 work 的 `Completeness.COMPLETE` 仅闭合该行声明列表，不闭合 run 内所有工作。 |
| Provider coverage | `ProviderCoverageDomain` 已有 DATAFLOW / ALIAS_IDENTITY / STATE_EFFECTS 等声明域；`ProviderArtifact` 有 exact schema/digest/size。 | Coverage 的 docstring 明确是 declaration, not legality certificate；通用 DATAFLOW/ALIAS_IDENTITY 声明不特指 target、footprint、run 内 writer 全集，也不证明采集没 drop。FactRef 只可溯源。 |

## 最小可执行 R2.3 结构

以下是关系接口建议，不是已实现 records，也不增加第二份 producer/use/state 图。

1. **Exact endpoint refs**：复用 `MaterializationRef`；补 exact `ValueVersionRef(artifact: ProviderArtifact, version: ValueVersionID)`，以及 exact evidence-edge 引用 `(evidence_artifact: ProviderArtifact, edge_id)`（或对 `ProviderFactReference.locator` 定义并严格验证 edge-ID 语法）。`ProvenanceRef` 若单独引用也必须含 ValueGraph artifact。任何 ValueVersion/Materialization 都不可仅靠裸 ID 跨图 join。
2. **Scoped bridge**：`EvidenceValueBridge(evidence_edge, value_endpoint: ValueVersionRef | MaterializationRef | StorageRegionRef, source)` 把 EEG endpoint 指到唯一 exact ValueGraph artifact/行。检查 edge 的 typed endpoint-kind/ID 与被 bridge 的实际 row 一致；若 edge 指 `MaterializationID`，再检查 `Materialization.value_version` 和 region/allocation。不同 artifact 中同 wire ID 冲突时必须保留分歧，不选第一个。
3. **Target-scoped production coverage**：以 `(run/window scope, evidence artifact, ValueGraph artifact, exact target version + MaterializationRef + selector)` 为键，固定覆盖维度至少为 provenance/dataflow、`PRODUCES`、`OBSERVED_WRITE`、`OVERWRITES`、`MATERIALIZES`、`ALIASES`，每项可为 COMPLETE/PARTIAL/UNKNOWN 并引用来源。维度是协议固定集合，不能让调用方删去不方便的 relation。它表示 provider 声明了什么范围；结构验证可确认 artifact 与 rows 精确对上，仍不能把 COMPLETE/FactRef 本身升级为“现实里 writer 已全捕获”。缺 target-scoped coverage、artifact 缺失、来源有 drop/gap、范围不含消费点时，贡献闭包为 incomplete/unknown。
4. **Writer association，不造 producer**：给每个纳入的 writer-edge 一个 association，引用 exact evidence edge、exact target endpoint/selector、`WorkTicketID | ObservationRootID | Unresolved`，以及可选原 `AccessRef | InvokeBoundaryStateEffect | Unresolved`、source。校验 legacy operation 通过同一 EEG artifact 的 `OccurrenceEvidenceBinding` 对齐到 occurrence；work 若是 within-operation，校验对应 owner/target/materialization。多 ticket 同 owner occurrence 时只有唯一精确关联可自动 join，否则 ambiguous gap。External work/producer 只有精确 EvidencePoint/root 及 artifact correspondence 才能接入。
5. **Derived closure result**：query 从 exact ValueGraph 版本血缘 + 上述全部 EEG writer/alias 边 + associations 计算 obligation，不接受任意 caller-provided empty list。输出分开的集合：`derivation_prerequisites`、`materialization_steps`、`required_content_contributions`、`potential_invalidators`，每项保留原事实引用和 selector/coverage。只有 selector/geometry 证明不相交，或 version/coverage 证明 writer 已被完整覆盖/替换，才能排除；未知交叠留下 gap，不把所有历史祖先强迫成当前 AND writer。
6. **Visibility algebra**：对于一个被证实必需的贡献，合法的 CompletedVisibility、精确 queue-prefix/order 链、或匹配的 external ObservationRoot 是 OR 支持；不同必要内容 slice/contribution 之间是 AND。每条支持都绑定相同的 version、Materialization、allocation lifetime、selector、scope 和 consumer visibility domain，禁止把 writer 集合与 consumer 集合分别 union 后跨配。此 query 输出条件和反证，不把静态 coverage 变为动态授权。

### 归并与排除规则

- 同一 EEG `OperationInstance` 对同一精确 version/materialization/selector 同时有 `PRODUCES` 和 `MATERIALIZES` 等关系时，它是一组带多个 typed facts 的来源，不是多个 AND contribution。
- `MATERIALIZES(ValueVersion→M)` 可描述表示创建/迁移，不能单独说明该 version 的逻辑内容正确或完整。
- 全 `ValueVersion.parent_versions` 是 derivation ancestry，不等于最终 consumer 的全部物理 writers。COPY/VIEW/TRANSFORM/MUTATE 的部分/全量 selector transfer 需可复用的 typed geometry/selector mapping；当前 provenance relation 本身不提供此映射。
- `ALIASES` 用于扩展可能同存储 target 的 writers/invalidators。它是候选 alias 边，不自动表示每对 region 完全相等；已知 geometry 可证明不相交时才排除，UNKNOWN 保留 conflict gap。需要在共享 geometry helper 上区分 `DISJOINT / OVERLAP / UNKNOWN`，考虑 stride、dtype width、empty/zero-stride 等；不能用 bounding box 误判有 holes 的布局。
- `OVERWRITES` 不等于产生当前 logical version：它可能是旧内容的失效事件。其位置在精确 writer、consumer/最终 materialization 的顺序关系之前还是之后决定是否仍 relevant；无顺序则 conflict gap。

## 支持与结果边界

- `COMPLETED` + `WorkQuiescence` 只是对应 ticket 的协议终结/quiescence 声明。仍须有 exact contribution association 和 output/version/materialization/selector correspondence；不能由 `effect_frontier` 或 `frontier_coverage=COMPLETE` 推数据内容。
- `FAILED`/`CANCELLED` 的 frontier 可在额外 exact partial-output association 表明确有某 footprint 写出时，只支持那个 footprint；所需 remainder 仍 unmet。单纯 AccessRef/InvokeBoundaryStateEffect 只能确认 state boundary，不能计 data contribution。
- 无 outcome 不是 FAILED。精确 EventRecord→QueueWait→consumer queue prefix 的 order path 可以提供 `OrderedVisibility` 条件，但若尚无 actual outcome，返回 pending/conditional，并保留相同 writer 的协议成功/异常传播、exact materialization/output 与正确内容条件。Order validator 的 WorkStart→WorkEnd 边是图上的 conditional work boundary，不是运行完成事实。
- `ORIGIN` / 无 provenance producer 也不构成空 required set；需精确外部 source/ObservationRoot，或 unresolved input contribution。consumer Use→ValueVersion 无可靠 denotation时整个 requirement unresolved。

## 可复现的反例（结构推演，不是运行测试）

1. **删 WorkTicket**：EEG 精确 artifact 仍含 `OBSERVED_WRITE op→M`，execution 却删掉它唯一 `WorkSubmission`。如果 required list 来自 execution submissions，空集将错误满足；派生 universe 仍含该 edge，必须报告 missing ticket association。
2. **只查 PRODUCES**：旧 `M1` 所在 allocation 上另一个 region `R2` 有 `ALIASES(M1,R2)`，随后 `OVERWRITES/OBSERVED_WRITE op→R2`。仅看 `PRODUCES→M1` 会保留已过时支持；需要 geometry/顺序或冲突 gap。
3. **错误地 AND 历史祖先**：`V0` 经完整新版本转换得到 `V1`，完整覆盖 selector；若把 V0 writer 一并要求，产生过度拒绝。反向，若 selector 未知而直接排除 V0/alias writer，则会漏依赖；应 unresolved。
4. **同 ID 跨图碰撞**：两个 ValueGraph artifacts 都有 `mat:x`，EEG target 只有裸 `MaterializationID(mat:x)`。没有显式 artifact bridge不能静默配到调用者偏好的一个图。
5. **同宿主多 work**：一个 Invoke occurrence 分别提交 wA/wB，二者都声明 `MaterializationRef(M)`，只有一个 EEG writer edge。仅按同 occurrence/同 M 合并会随机选 ticket；需 exact edge→ticket association或歧义 gap。
6. **空图/伪 COMPLETE**：EvidenceGraph 对 target 没有 writer edge，ProviderCoverage.DATAFLOW=COMPLETE，但没有 target-scoped `ALIAS_IDENTITY`/writes coverage或 capture-drop 检查。空 edge 集不能当“无 writer”；只能视为该 artifact 已枚举 + provider completeness claim，实际 capture closure remains unknown。
7. **FAILED 部分写 / pending no outcome**：w 写 `[0:4]` 后抛错，consumer 要求 `[0:8]`；可支持的 `[0:4]` 不满足 remainder。另一个 queued w 无 Outcome 但被精确 wait；可给顺序条件，不能当已完成，也不能错判失败。

## 必须的前置与排序

1. 先有 consumer `UseOccurrence`/外部 endpoint → exact `ValueVersionRef` 的 data-denotation 关系；当前 `ExecutionModel` 的 `ValueOccurrence(value: core ValueID)` 不含 ValueGraph version/materialization。旧 `CorrespondenceGraph.SLOT_VERSION` 是静态 ValueSlot→ValueVersion，`OccurrenceEvidenceBinding` 是 op occurrence→legacy op instance，二者都不解决动态 ValueOccurrence denotation。
2. 再有 exact EEG artifact↔ValueGraph artifact bridge 与可核验 producer/writer scope coverage。验证 artifacts 的 canonical bytes/hash，确保加载后不让可变图对象被无声修改；不能把 artifact URI/裸 IDs 当身份。
3. 使用同一 geometry/selector tri-state helper 做 contribution partition 与 alias-invalidation closure。没有精确 selector/partial producer rule前，只能 unresolved，不以 guessed whole-region 代替。
4. 最后才派生 AND contribution obligations、每项 OR visibility alternatives、失败/取消的 partial coverage 和无 outcome 的 conditional ordering。

当前R2.3可完成“声明与关系可验证、缺口清楚”的conditional query；真正全量 trace/source 与动态 denotation仍属后续证据门。不得因补齐这些结构把 `source_runtime_verified` 或 `transformation_authorized` 改 true。

## 审查版本与源码指纹

审查工作树 HEAD `2d6f1d44d81e36a3f0638d79a60d4f4c1c4312fc`；只读，没有运行测试/工作负载。

| 文件 | SHA256 |
|---|---|
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` | `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/order_validation.py` | `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/evidence.py` | `dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5` |
| `scar/ir/v2/correspondence.py` | `7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5` |
| `scar/ir/v2/schemas.py` | `4c54102f84f342c0f51f32bf3632494cecbd5b65131ad0783ba4d2fa798f2025` |
| `scar/ir/program/providers.py` | `fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343` |
