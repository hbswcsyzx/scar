# R2 event/order/readiness：供后续冻结的机器记录设计

状态：**Proposed**，只读设计；本轮只实施 R2.1 Work/Outcome/retention。以下 R2.2/R2.3 记录没有实现，也不计入 R2.1 验收。未修改产品/测试/R0，未运行 pytest、采集或 GPU。阅读文件指纹在 `ready-source-sha256.json`。

## 1. 规范事实归属和依赖

- 原 ProgramGraph 仍唯一拥有 Use、StateAccess、producer、entry/completion formal。EffectRef 沿 R2.1 的 AccessRef / 实际 INVOKE 输入与 completion frontier；本设计不复制 actuals 或重造 producer。
- 原 ValueGraph 唯一拥有 ValueVersionID、MaterializationID、StorageRegionID、StorageAllocationID、几何和 provenance。所有外部端点必须带准确 ProviderArtifact；相同短 ID 不跨 artifact 合并。
- WorkTicket/Outcome/quiescence/retention 从 R2.1 引用，名称在 root 冻结后对齐。R2.1 不提前加入没有 FK 目标的 Ready/Contribution 字段。
- FactRef / Completeness 是来源声明，不是来源已经解析、规则适用或 PROVEN。未解析的 manifest 不能关闭全集、alias、lifetime 或 protocol 义务。

## 2. 建议的精确引用和 placement

以下所有 record 均 frozen/slots、exact typed IDs/enums/tuples，禁止 bool 当 index；来源复用 FactSource，缺口复用 Unresolved。

```text
VersionRef(artifact: ProviderArtifact, version: ValueVersionID)
MatRef(artifact: ProviderArtifact, materialization: MaterializationID)
RegionRef(artifact: ProviderArtifact, region: StorageRegionID)
ContractRef(artifact: ProviderArtifact, contract: ContractID)
Selector = RegionRef | AccessRef | UseRef | Unresolved

StorageBacked(materialization: MatRef)
EndpointBacked(materialization: MatRef, endpoint: ResourceTarget,
               selector: AccessRef | UseRef | Unresolved,
               support: tuple[ValueOccurrenceID,...], source: FactSource)
UnresolvedPlacement(materialization: MatRef, gap: Unresolved)
Placement = StorageBacked | EndpointBacked | UnresolvedPlacement
```

StorageBacked 的 region/allocation 从原 mat 追溯，不能填写一份新 geometry/allocation；region=None 必须拒作 storage-backed。EndpointBacked 必须显式给 endpoint、准确 selector/current-state 及来源；不从 `device='cpu'` / region=None 推出文件或 NVMe。AccessRef 的 footprint 单位不能假定是字节；endpoint selector 没有协议映射时保留 `selector_mapping_unresolved`，不按 whole/disjoint 处理。

Consumer/Denotation 建议：

```text
ObservationRoot(id, contract: ContractRef, endpoint: ResourceTarget,
                selector: Selector, point: ExecutionPoint,
                condition: ProviderFactReference, source: FactSource)
Consumer = UseRef | AccessRef | ObservationRootID | Unresolved
ContentBinding(id, consumer: Consumer, content: VersionRef,
               placement: Placement, selector: Selector,
               support: tuple[ValueOccurrenceID,...],
               completeness: Completeness, source: FactSource)
```

UseRef / AccessRef 在当前 occurrence 查原 UseOccurrence / StateAccess；只声明 Ref 不能证明其代表哪个 logical content。ContentBinding.content 必须等于准确 mat.value_version（同 ValueGraph artifact），selector 必须在该 placement 中，support 必须是该 consumer 点的当前 state。相同 object/storage/shape 不代替这条 denotation。ObservationRoot 的 ContractRef 必须可定位真正 Q 合同和准确观察条件；ContractDefinition 的 EXTERNAL facet、最后一次 close 或任意字符串不能独立生成该根。无根保留 Unresolved，不伪造代码消费者。

## 3. R2.2：event 代次与 queue prefix

```text
QueuePrefix(id: QueuePrefixID, queue: ResourceAccessID,
            cutoff: ProviderFactReference,
            members: tuple[WorkTicketID,...],
            completeness: Completeness, source: FactSource)
EventRecord(id: EventRecordID, event: ResourceInstanceID,
            recorder: ExecutionPoint, captured: QueuePrefixID | Unresolved,
            rule: ProviderFactReference, source: FactSource)
OrderEdge(id: OrderEdgeID,
          before: WorkTicketID | EventRecordID | QueuePrefixID,
          after: WorkTicketID | QueuePrefixID,
          establishing: ExecutionPoint,
          rule: ProviderFactReference, source: FactSource)
```

QueuePrefix.queue 回查原 ResourceAccessBinding→RequirementBinding→同一 queue lifetime；相关 context 沿真实 relation/binding 或协议证据定位，不按设备名字猜。cutoff 指原提交范围/标记，members 是已登记成员，不赋予 tuple 位置执行顺序。只有源 prefix manifest 与真实 submissions 对账闭合时才宣称该范围完整；缺头部、截窗、无法解析 cutoff 均是具体 gap。两次 queue-access binding 可指同一 queue instance，但不能只按静态 requirement 相同合并。

EventRecordID 自身是一次 record 身份，不再给 event instance 加可变 generation counter。wait/order edge 引确切 EventRecordID，event 后续 rerecord 只增加新 row，不修改旧 captured prefix。未 record 的空 event 没有任意 work 的 prefix。多个 record 的支持不得按 event instance 归并。

OrderEdge 只有规则声明；协议适用/实际 enqueue 顺序必须有来源。判定路径逐边检查 queue/context/作用域和准确 generation；拒自环/已知 HB cycle。不能从时间重叠、host tuple 顺序、成员集合包含或相同 stream 字符串自动补边。EventRecord 节点展开为其准确 captured prefix；Prefix 节点表示所含工作在 cutoff 的完成 frontier，Work 节点作目标时表示该工作开始。供 ready 使用的路径必须最终到准确 consumer work 的开始，不能仅到一个“后来包含 consumer 的 prefix 的完成”，更不能变成“此 queue 上所有将来工作”。

## 4. R2.3：贡献来源闭合，不能删 writer 换 ready

```text
ProductionCoverage(id, materialization: MatRef, origin: EffectRef | Unresolved,
                   selector: Selector,
                   frontier_source: ProviderFactReference | Unresolved,
                   completeness: Completeness, source: FactSource)
Contribution(id, production: ProductionCoverageID,
             work: WorkTicketID, effect: EffectRef,
             selector: Selector, source: FactSource)
```

Contribution.production 是登记成员关系的唯一规范入口，ProductionCoverage 不另存可自由裁剪的 required tuple。Required 集由以下步骤派生：

1. 从 ContentBinding 的准确 MatRef/selector 查唯一适用 production scope；多个冲突来源不择一覆盖。
2. 对齐该 scope 的原 work/submission effect→materialization 输出 frontier。每个已登记、可能贡献 consumer 所需内容的 writer 都必须有相应 Contribution，effect 必须真实属于该 work，不能把 read 冒充 produce。
3. 按同一 allocation/endpoint selector 的准确交集选入贡献；unknown overlap 不删项。被后续完整覆盖的 writer 仅在来源已证明不是该内容版本的必要贡献时排除，不能用全局“最后一个 writer”猜测。
4. 将贡献 selector 的并集与 consumer selector 对账，要求完全覆盖。多个 writer 对同域覆盖有冲突/缺失的 production provenance，则列来源缺口，不随意选其中一个。
5. 对比原 frontier manifest 和采集/映射 coverage；未知 native 输出匹配、截断 work 窗口、没有 manifest 或仅有未解析 FactRef，一律 `production_frontier_unclosed`。COMPLETE 标签不能关闭这个缺口。

删 Contribution 但仍存在原 writer 时是 `missing_contribution` issue；连 work 行也删时，来源 manifest/coverage 不闭合，不能通过“当前表已经空了”生成 vacuous ready。该 source closure 是 R2.3 的必要接口，不能由 ReadyEvidence 自己声明一个缩小的全集。原材料读取/manifest 解码属于明确 provider adapter，codec 不自动访问 URI。

## 5. 真实 Produced frontier 与失败/取消

建议后续把原 Outcome.effect_frontier 的准确条目引用为 `OutcomeEffectRef(outcome,index)`，再建立：

```text
ProducedContribution(contribution: ContributionID,
                     frontier: OutcomeEffectRef,
                     selector: Selector, source: FactSource)
```

这是一条 outcome 原 effect/实际结果→贡献/覆盖的对应关系，不是新结果 producer。Outcome 必须属于 Contribution.work，frontier 条目必须对应同 EffectRef/MatRef/逻辑版本，实际 selector 只能覆盖已产生部分。

- COMPLETED enum 本身不生成 ProducedContribution，也不把短 write 当 full-write。
- FAILED/CANCELLED enum 本身同样不给任何成功 content 或 quiescence；它们也不能抹掉实际写入。
- 如果准确 Produced frontier 证明指定 partial selector 已经产生所要求的版本，该部分可以参与同范围 ready；其余范围仍缺失。已知失败且没有 Produced 支持的部分必须拒绝，正确 order chain 不能补内容。
- 无 outcome 不等于失败。Ordered 支持可使用原 work 的成功生产/异常传播条件作为未消除条件，不能宣称数值生产已被观测。已知失败会反证该条件，除非有上面的准确部分 Produced 支持。

## 6. AND/OR 与 visibility 精确匹配

```text
HostVisibility(process: ProcessInstanceID,
               thread: HostThreadInstanceID | Unresolved,
               address_space: ProviderFactReference)
QueueVisibility(consumer: WorkTicketID, prefix: QueuePrefixID,
                context: ResourceBindingID | Unresolved,
                rule: ProviderFactReference)
EndpointVisibility(endpoint: ResourceTarget, condition: ProviderFactReference)
UnresolvedVisibility(gap: Unresolved)

ConditionalProduction(contribution: ContributionID,
                      condition: ProviderFactReference, source: FactSource)
CompletedVisibility(production: ProducedContribution,
                    outcome: WorkOutcomeID, quiescence: QuiescenceRef | Unresolved,
                    establishment: ExecutionPoint,
                    rule: ProviderFactReference, source: FactSource)
OrderedVisibility(production: ProducedContribution | ConditionalProduction,
                  chain: tuple[OrderEdgeID,...], consumer: WorkTicketID,
                  rule: ProviderFactReference, source: FactSource)
ContributionAlternatives(contribution: ContributionID,
                         alternatives: tuple[CompletedVisibility | OrderedVisibility,...])
ReadyRequirement(id, binding: ContentBindingID, visibility: VisibilityDomain)
ReadyEvidence(id, production: ProductionCoverageID,
              placement: Placement, visibility: VisibilityDomain,
              support: tuple[ContributionAlternatives,...],
              validity_source: ProviderFactReference | Unresolved,
              source: FactSource)
```

WorkOutcomeID/QuiescenceRef 以 R2.1 冻结 API 为准。ConditionalProduction.condition 必须定位该贡献原 work 的成功生产/异常传播条件，不能任意填一个 true 字符串。CompletedVisibility 名称表示对应 Produced 部分的完成/可见性支持，不能仅测试整个 ticket 的 COMPLETED enum；如果部分来自 FAILED/CANCELLED，仍须准确 Produced、实际 quiescence 和域适用依据。不能把故障 enum 当成功或把取消当无借用。

对 derived required 集 D，判定式是 `AND(c in D: OR(valid alternatives for c))`。每个 c 可走不同 basis；不得把所有 work 的完成和所有 consumer 的域分别 union 后交叉配对。Evidence 中缺必要贡献、额外冒充贡献或重复覆盖错误键都不能缩小 D。空 D 只有源证明该需求确实没有贡献/空选择时成立，来源不闭合时仍 gap。

同队列有序 consumer 可由 OrderedVisibility 满足，不要求 CPUCompleted。CompletedVisibility 也必须满足该精确 Host/Queue/Endpoint 域的规则，不自动升级成 persistence/flush。QueueVisibility.consumer 必须沿该 work 的原 effect/input 对应关系连回 ContentBinding.consumer；仅归属同 host op 不证明实际消费。prefix 指该 consumer 入队前的准确队列 frontier，并需实际 before→consumer-start 关系；缺这个对应关系是 `consumer_work_mapping_unresolved`，不从 prefix 的任意成员补出。另一 queue/host/thread/domain 均不能借用。ReadyEvidence 可被多个匹配消费者引用，不是一用即耗的 permit。

## 7. 几何、有效期与状态

- 复用 `scar.ir.provenance._width/_byte_bounds/_byte_intervals`，不存 Tensor 内容。必须先检查 `0 in shape`（空集）和 `layout=='strided'`；目前 `_byte_intervals` 自身未检查 layout，且 size=0/stride=0 的维度会枚举一格，不能裸调用。
- 相同准确 RegionRef 可直接证明集合相等；否则只在预算内用精确 byte intervals 做交/并/包含。zero stride 只是重复地址，不扩 allocation；负 stride 按原合法边界处理。
- `_byte_bounds` 只能用来拒绝、界限或已独立证明连续的情况；bbox 相同不证明跨 stride 孔洞覆盖。超预算/未知 dtype/未知 selector 是 `coverage_geometry_unresolved`，不可当 full/disjoint。
- consumer 当前 ContentBinding 必须独立核对版本和当前 state。原 ReadyEvidence 不自动跟随同 object 的新值；旧内容/新 allocation lifetime/错误 artifact 即 issue。
- 有效期证据必须覆盖生产/建立支持到 consumer 所需区间的 alias-write、allocation retirement、端点选择和跨边界 coverage；可沿准确原 effect/current-state 及有来源的 lifetime 事实建立。旧 local EventPoint 时钟、指针、`_version`、`Materialization.ready_event` 或旧 registry 的 READY/VALID enum 均不自动迁移。
- 已知覆盖写/retirement 使旧支持失效；未知 alias/native write/缺失 lifetime 覆盖给精确 validity gap。不能因为未看到 invalidator 就认其不存在。endpoint backing 与 storage backing 也不默认 disjoint（例如存在共享来源）。

## 8. 验收反例（后续，不在本轮运行）

1. 同 queue 两次提交，A→consumer 的顺序成立、无 CPU completion：条件化 ordered 支持；移至不同 queue 或 host consumer 则不适用。
2. event E record r1 捕获 A，r2 捕获 B；wait r1 不能覆盖 B，更不能因 query(E) 完成而改成 r2。
3. 两贡献 A/B，A Completed、B Ordered：AND/OR 混合正例；删除 B evidence 必须缺支持，删 B contribution 必须被原 writer/frontier 对账抓出。
4. 已取消 copy 只确实产生第一段：第一段在真实 Produced+visibility 条件下可用，whole selector 不可；失败标签不凭空抹除或填满范围。
5. v0 已 ready、同对象更新到 v1：旧 Evidence 不满足 v1；相同 raw pointer 的新 allocation incarnation 也不能复用旧 placement。
6. stride 孔洞、expand 零 stride、空 size0/stride0、超预算、未知 dtype：不能用 bbox 或完整 tensor allocation 大小伪造覆盖。
7. 相同 mat/region 短 ID 置于不同 artifact、错误 byte size/hash、queue context/run/process 不符：机械拒绝；缺目录/未知映射给明确 gap。
8. 未恢复 Use→content、原 production manifest 不可查、未知外部 alias 写：不产生无条件 ready；free/retention 资格不从 output ready 推出。

最终 query 应返回原 consumer/production/contribution/支持链、反证、逐项缺口和条件适用范围。可报告结构匹配或条件满足，不能把手写 FactRef/COMPLETE 变成 runtime-ready=True、资源可释放或 transformation authorization。
