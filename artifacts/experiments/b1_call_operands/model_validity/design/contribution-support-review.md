# V0：来源贡献、替代支持与覆盖的设计审查

状态：**Proposed，未冻结 API、未实现、未运行测试/采集**。基线为 root 提供的
clean `f2b4672`；本报告只读产品、既有合同和证据，不修改 src/tests/docs。
本设计覆盖 V 应连接的完整义务；不把结构性条件成立等同于 native/runtime 证明。

## 1. 先作的决定

1. **来源全集仍来自 P，不新增 required_contributions 输入。** 从原读取 run 的全部
   inventory/原行/EEG 关系枚举，再连接 Write/Produced。缺 inventory、pending、alias、
   opaque、跨范围桥和截断都留在 obligation ledger。删 work/write/support 不缩 source IDs。
2. **不能只消费 `production().current_production`。** 当前该字段刻意要求 exact 同
   version/Mat/selector；合法的分段 selector 可能只在 `candidates.write_associations`。
   V 从所有候选的准确关联派生 fragment，再以原需求 selector 检验范围。保留 P 原接口，
   复用同源枚举/精确连接 helper，避免另写一份可漂移的 universe。
3. **AND 不是把所有曾出现的 writer/祖先平铺。** 血缘前提、当前内容 fragment、潜在
   invalidator 各有义务。一个物理 stage 的多个证据不是多个独立贡献；多个真正的分段
   writer 也不能因同 ticket/host 而合并。
4. **OR 只能在同一准确贡献/范围/消费者/域中。** A 的完成不能替代 B 的顺序；跨域
   signal 或一个更晚版本的支持也不能挪来配对。不同合法 fragment 的并集可覆盖需求，
   必须保留每个被覆盖部分的来源标签，不能先 union selectors 再另 union 支持。
5. **有意义的条件性正例必须可表达。** 返回已匹配 fragment 的条件性覆盖和支持公式，
   同时单列无法闭合的来源/native/lifetime 条件；不能仅反复返回 ready=False。也不能
   把缺失的 write/Produced/当前状态端口当一个任意用户假设而填成成功。

## 2. 最小关系记录建议

以下名字/字段是 API 建议，尚未冻结。所有新记录 frozen/slots/exact；复用原 typed
references、FactSource/Unresolved，不存数值 Tensor、第二 producer、第二 state 或实际参数。

```text
EstablishedProduction(
  id: EstablishedProductionID,
  write: WriteAssociationID,
  established: ExecutionPoint,
  actual: RegionRef | ProtocolSelector | Unresolved,
  result: ValueOccurrenceID | ProviderFactReference | Unresolved,
  rule: BytePrefixWrite | Unresolved,
  source: FactSource)

HostDomain(thread: HostThreadInstanceID)
QueueDomain(queue: ResourceInstanceID)
EndpointDomain(root: ObservationRootID)
VisibilityDomain = HostDomain | QueueDomain | EndpointDomain | Unresolved

CompletedVisibility(
  established: ExecutionPoint,
  basis: AccessRef | InvokeBoundaryStateEffect | UseRef | ProviderFactReference | Unresolved,
  domain: VisibilityDomain,
  protocol: ProviderFactReference)

OrderedVisibility(protocol: ProviderFactReference)

ContributionSupport(
  id: ContributionSupportID,
  read: ContentReadID,
  write: WriteAssociationID,
  production: OutcomeProductionID | EstablishedProductionID | None,
  visibility: CompletedVisibility | OrderedVisibility | Unresolved,
  source: FactSource)
```

`EstablishedProduction` 补齐真实 HostWrite/ExternalEstablishment 的实际结果；不造 ticket。
Host 普通操作需准确 AFTER；INVOKE 需本次真实 EDGE，且原 StateProduction 的 post 沿真实
CompletionResult/formal。RAISE 仍可有部分产出。External 仅 EvidencePoint，范围/时钟未知
就保留 gap，不能套 host 顺序。它是结果关联，producer 仍是原 Value/StateAccess。
`BytePrefixWrite` 可复用现有五字段 parser 与 byte-count/selector guards；请求范围、
实际范围、原返回值仍逐项核对，不能从 placement=request 自动推出 actual=request。

`ContributionSupport` 不再存 stage、version、Mat、selector、ticket、consumer、当前 state：
这些从 write/production/read 唯一派生。来源 stage 只能回到既有 exact SourceEdgeRef / 原物理
RawRecordRef（或仍待连接的 NativeOutputRef），不接受另一个“同名 stage”字符串。支持行
不能创造候选；没有 source join 的支持保留 orphan/missing-join gap。

`production=None` 只允许表达**没有实际结果可用的前瞻 Ordered 条件**，不得表达完成。
若同一 work 已有任何已知 terminal Outcome，必须处理这些结果：不能借 None 忽略已知
FAILED/CANCELLED/short-write。相同 kind 的多个 Outcome 观察也不能选择最有利一行；
准确 protocol result/actual 若矛盾，报告 issue；尚不可比则 unresolved。

`CompletedVisibility.basis` 指原“建立可见性”动作/返回值/源事实，通常发生于生产完成后：
在其 established 点核对实际 owner/scope、原 Use/效果及 after/真实 completion state。
不能只填 arbitrary FactRef 而令协议被证明；未解析 basis/protocol 是准确条件或 gap。
该 relation 可表达 sync、host handoff、端点 flush 等具体阶段，不将它们改造成新 producer。

Ordered 仅适用于具有真实 work consumer 的 queue 域；目的 WorkStart、queue/context、
输入槽和保守读取区间都从 read 派生。协议引用不能将其它路径改为本路径。Host/endpoint
有序建立用准确 CompletedVisibility 关系接原协议动作，不伪造 WorkTicket 或把 host
观察点强塞进现有 OrderPoint union。

## 3. 精确配对、不变量及校验接口

建议 `support_errors(ctx)` 在 D/P/work/order 解析后运行；`validity(ctx, read_id, budget)`
与 public query 共用纯解析函数，不在 query 重新创建生产或执行 provider。

每个已派生 fragment 的规范键为：

```text
(source physical-stage identity / exact unmerged source fact,
 original write production reference,
 expected scoped VersionRef, MatRef, physical placement,
 actual-selector reference OR accurately guarded pending requested selector,
 original ContentReadID, derived exact consumer+input+read interval,
 derived visibility domain)
```

- stage 归并只按 P 已准许的准确物理 RawRecordRef + production + placement（保守地要求
  writer 同一）；两个 EEG 关系或两条相同 ticket 声明不自行归并。
- production ID 必须 belongs-to 该 write；Outcome ticket 必须 exact WorkWrite.ticket；
  frontier 必须原 effect 条目；EstablishedProduction 必须 Host/External writer 的真实
  scope/完成端口，不接受别的 host invocation 的结果。
- read expected version 从准确 Mat/denotation 解析。Reference 必须接当前 StateAccess/
  actual completion/support；不能拿最初 object 的内容做永久 identity。
- 同 artifact/hash/schema/size + allocation lifetime 才能直接比较 geometry；URI alias 不
  新建身份。不同物化/分配只能靠明确、尚待核实的映射，裸 AllocationID 不跨范围合并。
- domain 从 read 解析后逐项匹配。Host 是真实 process/address-space/thread；Queue 是
  真实 consumer ticket、queue/context、native input；Endpoint 是原 Q root/target/selector/
  read/flush/persistence 条件。host 完成不自动建立另一线程、queue 或持久化可见性。
- 结构已知错 FK/type/run/actual port/version/target/frontier 是 issue。缺源/映射/协议解释/
  某条 order path、截窗和预算是 gap。未给记录不是 NONE，也不能把开放多对多的非成员
  当成物理上不可能。重复 supported rows 仅给 OR，不增加 Produced 字节数。

## 4. 源义务、覆盖与 AND/OR 的可执行算法

1. 从 P 同 run 的独立 inventory 派生稳定候选 ledger U；先枚举，后消费 support。按
   exact source stage/evidence 回查所有 write、结果、native/原 core effects。未连接的
   candidate 始终保留，输出特定缺口；不拿现有 support/write tuple 作 universe。
2. 针对每个 write，从原 placement 与已解析 actual 派生 fragment。逻辑祖先仅列 lineage；
   版本或空间不明确者留 unresolved；相同空间其它版本留 possible invalidator，不能计作
   expected-version 产出。选中 fragment 必须有准确 native-content 映射条件，PRODUCES
   本身不是 memcpy/write/“此段内容已经成为 V”的证明。
3. 收集每个 fragment **自己的**可用替代项：Completed 与 Ordered 均可同时存在。
   Completed 要准确实际结果及对应可见性建立；Ordered 要 WorkEnd(writer)→WorkStart(read)
   的现有条件路径及正确输入/域。不能以 consumer End、包含 consumer 的 PrefixEnd，或
   尚未绑定 generation 的 event 替代目标。路径不存在/截断只使该替代项 unresolved。
4. 已有实际结果时，任何 basis 的可用范围至多为准确 Produced.actual；COMPLETED 不扩张。
   FAILED/CANCELLED 的真实部分可以被支持，但 error propagation/后续 consumer 能否执行
   单列协议条件。前瞻无 Outcome 的 Ordered 用准确 request selector，明确带
   `successfully establishes V on that selector before this consumer starts` 的条件；这是
   计划依赖，不伪称已观测生产。一旦存在 terminal partial 结果，回落到 actual。
5. 利用 G 的准确 byte-set 和同一次 detached snapshots 计算交集/并集，保留标签：

```text
covered(fragment) = actual_or_guarded_requested ∩ demand
leaf(fragment) = OR(matching Completed, matching Ordered, ...)
per-required-portion obligation = OR(eligible fragment leaves for that portion)
support formula = AND(all required portions, causal-required fragment obligations,
                      source-reconciliation, lifetime, stability, domain conditions)
```

这等价于合同的每贡献 AND/替代支持 OR：两段 A/B 都必需时必须同时满足；同一段的重复
证明仅是 OR。不能把内容不同、带冲突副作用或没有最终版本映射的两个 writer 当作可任选
覆盖。真正的 RMW/aggregate 因果依赖须沿准确 provenance/state transition 保留；同一个
final VersionRef 名字不证明每个中间 writer 单独建立 final 内容。

不要求实现通用 SAT/最小 cover/编译器。可返回带标签的 coverage expression 与每个候选
支持；在已证明内容兼容、无冲突且各叶条件独立可合取时，使用一次 union coverage 快路。
有互斥条件/未闭合版本 kill 的重叠只返回 unresolved/冲突，不假装“所有 OR 都可同时选”。

### 复用 G，补齐标签而不复制几何

`_storage_coverage(required, tuple(fragment.region), catalog, remaining_budget)` 已支持并集。
它的 `used` 是几何所用引用，并不携带每个区间的 visibility 依据，不能直接当支持证明。
建议在**同一共享几何层**增一个 derived labeled-intersection/sweep helper，或逐 fragment
复用 G 的 covered_intervals 并在同一预算中分割 label；不另造 byte 算法/持久 selector。
query 临时区间仅为几何派生，不成为新的 VG region/producer。
`covered_intervals=None` 的 exact-ref symbolic fastpath 不是空集：保留原 selector 的 whole
符号证明及 labels。empty selector 可以几何 covered，但 source/Q/side-effect 义务仍在。
holes/zero stride/unknown layout/预算规则完全继承 G，不用 bounding box 填洞。

## 5. 有效期与 invalidator 是并列必需义务

支持区间从准确生产/visibility establishment 起，覆盖 read 的完整实际读取区间。
WholeWorkRead 以 WorkStart..WorkEnd 为保守区间；缩短需要原 NativeWorkRead 的 parsed
last-read 关系。host anchor 的当前 state 不能替代 GPU 在执行期间的内容稳定性。

派生可能失效者的来源不能取自 caller 排除清单：使用独立 U 的 overwrite/alias/escape/
raw/存储路径，以及原 core 写效果、资源退役事实。逐 fragment 核对 selector、版本和
区间；只有准确 disjoint、确切区间外顺序，或可查 native/provenance 的覆盖+version kill
规则才能排除。一次历史写发生较早，不等于它已被 killed；state 从 S0→S1→S0 的端点
相等也不证明中间无写。UNKNOWN call/跨范围 alias/未采窗口仍是显式 gap。

实际 target/allocation retirement 必须有独立源事实关联到 target+原 effect/完成+point；
现 HandleBinding.end 只结束 handle，BorrowRelease 只结束借用，均不是释放底层 allocation。
这需要资源/lifetime 分册冻结最小退役关系，V 必须消费它，不猜 free。实际退役影响哪段
read 由准确 order/interval 校验；retention/ownership 不能证明内容不变或任意 free 合法。

来源 capture 闭合仍是独立条件：现 inventory 只证明给定文件投影守恒，没有真实 write/
alias/drop/window 捕获闭合 provider。保持逐来源条件和缺口，禁止 COMPLETE+FactRef
自证。未来 parsed capture receipt 可接该义务，不需要改写 contributor/support 结构。

## 6. 公共查询建议与状态

`ExecutionIndex.validity(read_id, *, budget=4096)`：无 required-contribution 输入、无执行行为。
返回原 D demand/interval/域；P source universe/lineage/pending；每 contribution 的原 stage/
write/actual/Outcome 或 establishment；逐项 alternatives（含 order path/原 protocol）；
带来源 labels 的 conditional coverage/formula；逐 invalidator/lifetime exclusion 或缺口。

建议至少分开：

- `known_fragment_coverage`：COVERED / INCOMPLETE / UNRESOLVED，明确仅相对于准确且已连接
  fragments；partial native 只给其实际范围。
- `conditional_support`：MATCHED / MISSING / CONTRADICTED / TRUNCATED，说明支持/结构是否
  机械配对；可在全局 capture applicability 未证实时仍对已连接 A+B 返回 MATCHED。
- `source_reconciliation` 和 `validity_conditions`：列具体未连接来源、alias、kill、域、
  协议、lifetime/时钟，不能藏在一个 alwaysFalse 里。已知缺 B 不能算 MATCHED。
- `runtime_applicability` = UNKNOWN（由实现派生，不接调用者 proof bool），
  `source_runtime_verified`/`transformation_authorized` 恒 False。当前没有无条件 ready。

全局 open source 时，即便 known_fragment_coverage=COVERED，也明确不能推出所有实际
writers/invalidators 已排除。结构性的分段支持正例与 runtime 证明分别验收。

预算累计 source枚举、association/group joins、每条 order edge、每次几何描述/展开/
sweep、invalidator 扫描；共享剩余预算，不能每贡献重置 4096。snapshot/replay 字节
成本单列。预算截断保留剩余义务，不能改变 source universe 或被当作无冲突。

## 7. 最小验收节点与可复用 fixture

本表是未来验收计划，**没有运行**。不使用业务名、白名单或 FakeContext。

| 组合 | 既有 fixture 起点 / 最小扩展 | 必须观察 |
| --- | --- | --- |
| A actual[0,4) Completed，B requested[4,8) pending Ordered，demand[0,8) | byte_prefix_execution + event_order_execution 的 canonical core/queue；同一准确 VG 新增原 region refs；两段有不同物理 raw stage | 条件 MATCHED/COVERED；A 的完成和 B 的顺序各只支持自己的段；CPU 不必先等 B Completed。 |
| 两段 selector 各自不同于完整 demand selector | production_query_fixture 的原 D/read 和 source inventory | 从 candidates.write_associations 找全；不能只用 current_production 丢掉分段。 |
| B Failed/Cancelled 实际只到[4,6)，或 COMPLETED 短写 | byte_prefix 原 profile/frontier/result/selector | demand[0,8) 仅已知覆盖[0,6)；不能借 pending Ordered 填[6,8)。 |
| A 只支持 version V0/queue QA，B 支持 V1/queue QB | 同 host 多 work 的 content_connection_fixture + 两原 stage | 不交叉拼成一条覆盖；version/domain 已知矛盾为 issue。 |
| 删除 B support/write/Produced/work 及依赖行 | source inventory 保持不动的 P deletion fixture | 来源 candidate IDs 不变，准确缺口出现；不变成空 AND。 |
| 一个 raw stage 的多个关系 vs 同 ticket 两个 raw stage | P production_query_fixture | 前者证据 OR；后者保留两个实际阶段，不靠 host/ticket 合并。 |
| holes/空/zero stride/相同裸 allocation 跨 artifact/预算 | G 原 fixtures + exact placement refs | label sweep 不填洞；empty 不抹 source/Q；截断 unresolved。 |
| r1/r2、wait→consumerEnd、跨 queue/context/domain | event_order_execution 原 records/prefix/wait/Use | 错 generation/目标拒；缺 consumerStart path 不放行；不依赖 CPUCompleted。 |
| 在读区间中间 unknown/alias write，端点 state 一样 | canonical D read span + inventory raw/原 effects | 稳定性 unresolved/冲突；无 native kill 不排旧 writer。 |
| host INVOKE Raised 后已写部分，无 work | P HostWrite+真实 RAISE completion，新增 EstablishedProduction | 使用真实 partial post-state，支持实际范围；不造 work；旧 state/错 completion 拒。 |
| 外部建立/flush 根、target retirement vs handle close | 原 Q endpoint/read + 资源退役分册关系 | 精确目标/selector/协议；host信号不升级persistence；close/borrow结束不等于free。 |

建议实施顺序：V1 共同 effect resolver + EstablishedProduction 连接；V2 strict 支持记录/
标签覆盖/混合 basis；V3 interval/invalidator/lifetime/domain 组合；V4 schema/旧 wire/
组件与全仓。每门只声称已验部分，完整 V 前不得称 R2/R3/M0–M2 已闭合。

## 8. 发现的模型连接缺口（不是新 detector）

1. `content_validation.py` 的 Host INVOKE effect 强制 `ctx.work_effects`，而
   production_validation._effect 已允许无 work 的 HostWrite INVOKE。需要共用原 core
   effect resolver；真实 resource consumer 另验 exact work effect，不制造 work。
2. OutcomeProduction 只接受 WorkWrite+ResourceOutcome；缺 Host/External actual-selector/
   result/完成桥。EstablishedProduction 是最小补齐，不将请求 placement 当实际产出。
3. P current_production 完整 selector 筛选不够 V 分段并集；需源候选级 fragment 解析。
4. G 的无标签 union 不能单独表达“每段哪个支持”；需 derived label overlay，复用原几何。
5. OrderPoint 目前仅 work/prefix/event，没有 host/native completion→host handoff/
   endpoint visibility 关系；CompletedVisibility 明确接真实 establishing point/basis。
6. 无实际 target/allocation retirement 关系；HandleEnd/借用结束不可冒充。这与 V3 联动。
7. 真实 capture/content/协议闭合尚无 provider；维持条件化，不通过可写 PROVEN、COMPLETE
   或一个新枚举伪造能力。此缺口不妨碍机械验证匹配/部分覆盖/已知矛盾。

## 阅读指纹

以下为本次只读文件 SHA，不能代表新实现。

| 输入 | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `artifacts/experiments/b1_call_operands/model_production/design/next-validity-proposal.md` | `0773c3802b00abb16473afe8a643c9e2e87eb81a1982e3d0613091a61361d3d2` |
| `scar/ir/execution/production_query.py` | `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab` |
| `scar/ir/execution/coverage.py` | `43a0f21c7a5e5815f3e4408dcf76ff39eeb96f30f4fc0af655a8ccf0aff3a32b` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/order_validation.py` | `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba` |
| `scar/ir/execution/query.py` | `cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1` |
| `scar/ir/execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `scar/ir/execution/content_validation.py` | `bd163c92244a06dae9e5756882124cab350ffeec09bbe22e3137278712f5b298` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/production.py` | `cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098` |
| `scar/ir/execution/production_validation.py` | `c824c947a3ecf745b95096cdd6b69a529c2563ed02f6b951e261783ce4bb8c1e` |
| `scar/ir/execution/resource_validation.py` | `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08` |
| `scar/ir/execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `scar/ir/execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `scar/ir/execution/snapshot.py` | `7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107` |
| `tests/fixtures/execution_order_graphs.py` | `d4e21e8c63ebdb279bafae66ce14b5f78b917f05d3d1e37e3c56b94a2a203e2a` |
| `tests/fixtures/execution_produced_graphs.py` | `751b40a5c3e5190c5bf08341dc7c68c4fafe76aed3cdae7fb50fba9546c79aa6` |
| `tests/fixtures/execution_production_queries.py` | `92539d2c4d65c1b7a33e6623144c6c2ee5e2234bcb41b9370cdb9300f85ba22b` |
| `tests/fixtures/execution_content_graphs.py` | `cd1959d54ad7993b837fc51206cb78fbf3b4beb18778532e4060a00b14d707a3` |
