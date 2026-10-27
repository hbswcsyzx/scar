# V0：visibility、整段读取稳定性与生命期的独立设计审查

日期：2026-10-18。基线：root 指定 clean `f2b4672`；本审查未执行 git。
结论：**Proposed，可进入字段收敛；V 尚未实现/验收。** 只读取文档/源码并写本报告；没有代码、测试、设计 probe、native capture、GPU、LeWM 或全仓运行。下文 Observed 与 Proposed 分开，SourceAuthority/runtime/transform 均不授真。

## 1. Observed：能复用的事实和三个真实接口缺口

1. D 已有 `ContentRead`、准确 `UseRef/AccessRef/Q root`、原物化/selector、当前 state 支持；`HostConsumer` 不需要 Work。`ResourceConsumer` 的默认读取区间是整个 ticket，声明的窄 `NativeWorkRead` 暂有 protocol gap。见 `content.py:199,221,239,249,309`、`content_validation.py:43,308,415–451`。
2. core 的 `current/check_support` 只证明一个 host 点的 StateVersion occurrence，不能证明没有中间写；`point_precedes` 只比较实际 activation 路径中的 **OccurrencePoint**，EvidencePoint 不凭时间戳得到顺序。见 `validation.py:156–232`。`flow.py:210` 对 INVOKE/BODY_DRIVE 清空共同 AFTER，实际后态只沿 completion landing；V 不得重新制造 AFTER。
3. R2.2 的查询只接 `WorkStart/WorkEnd/PrefixEnd/EventSignal`（`query.py:266–317`）；已有队列/事件 order 与上述 host 顺序**没有跨域桥**。因此问题中的 host↔WorkStart/End 对齐确实缺失。`WithinOperation` 只是归属，`DirectExecution` 只是调度声明；host enqueue AFTER 既不等于 WorkStart，也不等于 WorkEnd。
4. P 的 `OutcomeProduction` 必须引用 WorkOutcome。HostWrite/ExternalEstablishment 虽可有 WriteAssociation，但 `placement` 是写/建立位置的关联，不是实际 produced 子集或实际建立点。当前 query 明确报告 host establishment 可无 outcome join（`production_query.py:350–360`）。**完整 V 需要一个小 P 补充关系，不能让 Host/External 伪造 ticket/outcome。**
5. `ResourceInstance` 表示一个生命周期；`HandleBinding.end` 只结束 handle；`WorkRetention.release` 只结束 borrow；`AllocationPlacement` 只是 allocation→pool。VG allocation 的 `lifetime_scope`、mat 的 `validity_scope/ready_event` 是可选字符串，不是退休事件。当前没有 allocation/target 退休的准确关联。见 `resources.py:170,383,497`、`work.py:283`、`v2/values.py:107–174`。
6. P 来源全集先于 Write/Produced joins 枚举（`production_query.py:116,412`），保留 raw/ALIASES/ESCAPES 等候选。已有 `possible_invalidators` 仅是空间/来源候选，**尚无区间稳定性算法**；它不是“所有真实 writer 已闭合”的集合。BytePrefix 只校验数量、原 selector、effect/frontier/result，不解释缓存、同步、flush、退休或数据正确性。

上位依据是 READY_CONTRACT §3–7 与 RESOURCE_EXECUTION_CONTRACT §4–5：几何、内容、完成、visibility、稳定性、retention、可回收相互独立；本设计不缩减这些义务。

## 2. Proposed：最小关联记录，继续引用原事实

以下是待 root 冻结的字段建议，不声称 API 已存在。所有新 ID 仅标识**关联**，不成为新的 Value/Use/effect/state/producer。`source:FactSource` 保留溯源，不充证明。

### 2.1 Host/External 的实际建立范围：一个 P 补充

```text
NonWorkEstablishment(id, write:WriteAssociationID,
  actual:RegionRef | ProtocolSelector | Unresolved,
  at:ExecutionPoint | Unresolved,
  result:ValueOccurrenceID | RawRecordRef | Unresolved | None,
  rule:ClosedEstablishmentRule | Unresolved, source:FactSource)
```

- `write.writer` 必须 HostWrite 或 ExternalEstablishment；WorkWrite 继续使用原 OutcomeProduction，不并存一份可绕过 outcome 的接口。原 stage/production/placement 从 write 派生，不重复字段。
- result=None 仅是该规则真实无返回值的 NotApplicable；外部建立不伪造 return。已知 native result 必须接原 result occurrence 或同一 raw stage/hash/行，不接任意 FactRef。Host INVOKE 使用实际 NORMAL/**RAISE** 的 effect post/EDGE；不能假定 RAISE 无建立，也不能拿另一个未发生的 completion。
- BytePrefix 可复用当前 closed raw schema 和 uint8/rank1/stride1/同 allocation/同起点检查；实际 4/请求 8 只建立 4。普通 Footprint 仍无隐含 byte 单位。Endpoint selector 需要规则解释，否则 gap，不把 ProtocolSelector 当 whole。
- 外部快照可以是“该点已有内容”的条件建立，**不是物理写入事件**；只观察 output/digest 也不自动建立这个内存 selector。其 rule 必须解析原快照/内容及端点映射；现有 parser 不足时保留 exact stage 和 gap。
- `at` 是内容建立的原坐标关联；outer op AFTER/RAISE EDGE 只是上界或粗后态时，不能凭它断言该点仍有同内容。内部 write 后还可能 callback/alias-write；需要下面的对齐/稳定性义务。未知建立点不是任意 AFTER。

### 2.2 精确 target 的生命期事件：不把 close/borrow 当 free

```text
TargetLifetimeEvent(id, target:ResourceTarget,
  action:OBSERVED_LIVE | RETIRED,
  at:ExecutionPoint | WorkEnd | Unresolved,
  stage:RawRecordRef | SourceEdgeRef | Unresolved,
  effect:AccessRef | InvokeBoundaryStateEffect | Unresolved | None,
  rule:ClosedLifetimeRule | Unresolved, source:FactSource)
```

- action 是待核对的关系种类，**不是 unchecked status**。adapter 必须从 stage 的真实结果/操作、准确 target/realm 及必要原 effect 得到该动作；仅有 release 调用/成功 wrapper/标签不够。无 core 事件的真实外部退休可以 effect=None；已知应有而未对应用 Unresolved。
- target 直接引用原 AllocationTarget 或 ResourceInstance/Process/Thread target。AllocationTarget 按完整 artifact+AllocationID；同地址、allocator token、pool、fd 数字均不合并。一个 VG allocation 若尚未对应到本次 run 的真实 incarnation，列 `allocation_incarnation_unresolved`；事件也不能补出该身份。
- ResourceInstance 的原 CreatedAt/ImportedAt 是现有起点候选，不复制一套 creation producer；allocation 无起点时可用 OBSERVED_LIVE 补“当时此 incarnation 活着”的来源关联。没有任何起点/存活依据，不能因没看见退休而推出 live。
- RETIRED 结束对应 target incarnation；异步退休若只声明未来 WorkEnd，保持 order/native 成功条件，不能当作已经观察到 free。必须精确到原释放 effect/实际 completion；失败释放不退休。
- `HandleBinding.end` 只影响经此 binding 的后续访问。dup/shared holder 仍可能使用同 target；它不自动退休 OFD、file、allocation。BorrowRelease 也不退休。退休已发生则旧 ready 不再支持新读，即使另一次分配得到相同地址。
- API 不授权 free：所有 pending borrow、ownership、并发访问、回收协议仍是独立义务。未观察到 retirement 不是“没有 retirement”。

### 2.3 Host 与 work 边界：一类 typed association，多种闭合锚

```text
VPoint = ExecutionPoint | WorkStart | WorkEnd | PrefixEnd | EventSignal
BoundaryAssociation(id, anchors:BoundaryAnchors,
  rule:ClosedBoundaryRule | Unresolved,
  evidence:tuple[RawRecordRef | SourceEdgeRef,...], source:FactSource)
BoundaryAnchors = Submission(ticket)
  | DirectExtent(ticket)
  | HostAcquire(subject:WorkQuiescenceID | EventRecordID | QueuePrefixID,
                effect:AccessRef | InvokeBoundaryStateEffect)
  | ExactReadExtent(read:ContentReadID)
  | ExternalSequence(left:ExecutionPoint,right:ExecutionPoint)
```

- 不存 caller 任填的 before/after 边。adapter 从这些原锚派生允许的有限关系，返回原 source/guard/条件；一个 FactRef 或未知 rule **不产生边**。也不按 timestamp/原 raw 行号跨线程、跨 clock、跨 process 自动排序。
- Submission 的已验证包含关系至多产生 host BEFORE→WorkStart；native 可在 enqueue 返回前运行，禁止自动 AFTER→WorkStart 或 WorkEnd→host AFTER。
- DirectExtent 只有同步协议、准确 thread/process、原 native/canonical 配对均匹配，才能产生 host BEFORE→WorkStart 和 WorkEnd→实际 host completion。INVOKE 的结束是**实际 EDGE**，不是共同 AFTER。host RAISE 也可能在 native 终结之后；需 source/result/协议分开核对。
- HostAcquire 的成功实际 completion 可条件性建立 exact WorkEnd/EventSignal/PrefixEnd→host completion。只借用现 WorkQuiescence/record/prefix 作锚：CANCELLED/COMPLETED 标签本身不提供 acquire；QueueWait 是 enqueue 的设备等待，**不是 host 同步返回**。未 record 的 event、旧 generation、另 queue lifetime 均不能补边。
- ExactReadExtent 仅在解析的 last-read/native 输入对应确实匹配时，把 D 的窄 interval 夹在原 WorkStart..WorkEnd 内。没有该证据，公开 query 继续用保守整段，不能因填了 ProtocolInterval 就缩短。
- 这些关系和已有 host/path/order 合并成**临时派生查询邻接**；引用同一原 occurrence/ticket，不另存长期图/producer。联合环是声明矛盾；不同 source clocks 无对齐则 gap。现 `point_precedes/order_path` 不应被偷偷解释为已经支持 VPoint。

### 2.4 Visibility 是每个 read × 实际 contribution 的域关联

```text
ContentVisibility(id, read:ContentReadID,
  established:OutcomeProductionID | NonWorkEstablishmentID,
  rule:ClosedVisibilityRule | Unresolved,
  evidence:tuple[RawRecordRef | SourceEdgeRef,...], source:FactSource)
```

- 域从原 read/placement/consumer/root 派生，不重新给一组任意 owner/version。host 域保留准确 Process/Thread/address-space 关联；queue 域从实际 consumer ticket 的 Queued.queue_access→binding→ResourceInstance 派生，并核原 executor/context；endpoint 域从原 target/selector/Q requirement/真实 observation interval 派生。
- Host coherent access、queue memory dependency、endpoint read/flush/persistence 是不同规则。相同 ProcessRealm、device 文本、队列先后、已完成 outcome 不单独建立缓存/共享 address-space 可见性。跨 process/queue/context 需要其准确 shared/coherence/protocol 对应；不能只凭 bare ID 或 SourceEndpointBridge 断言。
- queue 规则必须有各贡献的 WorkEnd→**实际 consumer WorkStart**，也必须有该协议的 memory-visibility 保证。end→end 或 PrefixEnd 不够；同 queue 没 FIFO profile 不补顺序。pending producer 可以保留“若按协议产生该内容且错误正确传播”的 ordered 替代，不要求 host Outcome；已知缺失/失败部分不能靠该替代补足。
- endpoint READ/FLUSH/PERSIST 的要求来自真实 Q typed requirement+protocol，不能从 EXTERNAL facet 或规则名猜。pwrite/close/read-cache/flush/fsync 等不存在普遍的自动提升链；对具体 endpoint/protocol 才允许已验证蕴含。持久化要求还需对应 durable endpoint/selector/故障域，不是“发生了任意 flush”。
- 以上四类 rule 都须有内置封闭 schema/parser 与 exact 锚校验；**本轮不要求新增 native detector/capture**。已能解析的部分可以返回 `CONDITIONAL_PROTOCOL`，物理适用/capture 仍是条件；未实现 adapter/只有 FactRef 返回 `UNSUPPORTED_PROTOCOL`+精确锚/gap，而不是同一种成功支持。新 enum 本身不构成实现。

## 3. Proposed：有限、source-first 的整段检查算法

入口建议 `derive_validity(ctx, read_id, *, budget)`，以及 detached `ExecutionIndex.validity(read_id,budget=...)`。validator 只查新关联的 FK/类型/已知 scope/原端口矛盾；真实 unsafe 程序仍是可表示图，**失效事件不是 metadata issue**。

1. **解析需求。** 复用 resolved_content_reads/denotations、resolve_placement、原 Q root。得到关联的一组 `(version,mat,selector,incarnation,domain,readInterval)`；有实际 resource work 才使用 WorkStart..End。host read 和外部 root 直接使用原 interval，不造 work。端点原 selector/state 不被替换为字节区间。
2. **建立全集。** 来源枚举先于 optional joins，继续保留 P 的 raw/EEG、ALIASES/ESCAPES、pending source、未映射 stage。再**独立**枚举本 run 所有已发生 canonical occurrences 的 WRITE/RW、效果不完整/未知 callback/INVOKE boundary，以及 handle end/所有 TargetLifetimeEvent。不能只扫描 Work.effects、Produced、当前 demand version 或已声明 matches；删除一条 join 不得减少候选集合。
3. **建立关系。** 由真实 transfers/visit incarnation 构造 host 条件顺序，接现 order 及已解析 BoundaryAssociation。跨 activation/thread/run 不凭列表顺序连边；实际路径截断保留 gap。每个 source effect 保留 begin/end 的可能区间：普通 op BEFORE..AFTER、INVOKE BEFORE..实际 EDGE、work WorkStart..End；只有归属没有更准坐标的 opaque 内部事件不塞到某个端点。
4. **空间与 alias。** 使用原 scoped allocation/region 几何检查已知不相交；仅 ordinary Footprint 且单位/selector 未映射时不能按 bytes 排除。alias 一侧未知、跨 artifact 未对应、同 endpoint selector 未解析、external writer/callback 没捕获范围时，保留可能失效者。不同 backing 不证明 disjoint；相同引用也不证明内容相同。
5. **每个建立事实分别检查。** 对 candidate `e` 及其确实建立的子集，要求域支持到实际读取开始，并从建立点/必要生产区间覆盖到**最后读取结束**。对相关写 `w`，只有有依据的 `end(w) ≼ establish(e)` 或 `readEnd ≼ begin(w)`，或已证 disjoint/合法独立，才可排除它。其余 known overlapping write 是 invalidator，未定位/不知先后是 potential invalidator+gap；不可线性化未排序工作。
6. **不误排除自身。** 同 ticket/op 内不同 stage 仍分开；producer 的并发干扰、consumer 的 READ_WRITE/in-place 写都不能因 owner 相同被删。whole-work 下无法确定“写在 last-read 后”时保留 gap，需 ExactReadExtent/真实阶段关系方可排除。写 A→B→A 仍有两次写，逻辑值或 bytes 恢复不抹去中间失效；如最后一次有准确新建立依据，可从该建立点重新支持以后读取，不能复活已受扰的前段读。
7. **生命期。** 要求同一 incarnation 在建立/使用期间有效；观察到退休后不能沿旧 mat/handle 继承。只关闭某 handle 时只否定经它的访问，不扩成 allocation dead；other alias 仍可能有效。始点活着但 interval 内 retirement/unknown reuse 不可忽略，WorkRetention 不消除此项。
8. **组合。** 必要内容贡献由来源/实际建立/几何覆盖推导，不接 caller 手填“已完成贡献清单”。同一子集可有 domain 合法的 OR 替代；所有必要子集/贡献做 AND。每一替代始终携带同一 owner/version/mat/selector/incarnation/域/区间；不能把 production 集合与可见 consumer 集合各 union 再交叉。没有 source closure，不形成空 AND 成功；相同 ticket 的不同物理 stage 不去重。
9. **有限性与预算。** 有限已供 source rows、occurrences、effects、目标事件及现 order/host edges；按 run/target/location 预索引，worklist/有界 reachability 与几何查询，无路径配置枚举、无任意迭代上限伪闭合。未知相关性允许保守全 run 候选。候选枚举、关联、空间/路径成本分别记账；截断返回未访问集合/具体 gap，不能当 absence。使用缓存必须绑定 fresh detached snapshots+所有原 source/artifact hashes，不能缓存跨版本 ready。

建议查询返回 `demand,source_universe,establishments,contribution_alternatives,domain_obligations,interval,lifetime,invalidators,potential_invalidators,pending_sources,gaps,budget/truncated`。每项附原 refs/推导路径；不返回无条件 ready/free。结构矛盾是 issue；实际 overlap/退休是已知失效结果；未知映射/覆盖是 unresolved；已核封闭协议的条件支持另列。SourceAuthority、runtime_visibility_verified、transformation_authorized 恒不由本层授真。

## 4. 关键反例与有限验收矩阵（后续实施，尚未运行）

| 真实组合 | 应检查的有限结果 |
| --- | --- |
| Host 初始化 8 bytes→同线程原 READ，无 work | NonWorkEstablishment+准确 host interval；不造 ticket，仍列 physical pairing/capture 条件。 |
| Host native requested8/written4→wrapper RAISE | 实际 RAISE post 可保留 4 子集；whole8 不满足；不把 wrapperRAISE 改 native FAILED。 |
| External 初始内容、无 core producer | exact stage/point/selector 可表示；缺解析建立/clock映射时 unresolved，不伪 operation。 |
| 读取起末都观察 A，中途 host 写 B 再恢复 A | 两个原 WRITE 都保留；端点 equality/最新 state 不能证明整段稳定。末次建立只支持其后的读取。 |
| 同 allocation 另一 alias/external process 写入 | 独立源或 canonical 写应进入候选；删除 Write/Produced join 不减少候选；alias不明是 gap。 |
| old allocation retire→same address 新 alloc→read old mat | exact incarnation 错配/退休使旧支持失效；新内容等值无效。handle close 与 target退休分别测试。 |
| dup handle h1 close，h2 同 target 合法读 | h1 不可继续使用，但不得只因 h1.end 判 target retired；未知 holder仍不授权free。 |
| retention覆盖到quiescence，但中间有aliasWRITE | borrow不代表内容稳定；release/quiescence标签不删除write。 |
| QA P1→r1→QB wait→C，event随后r2/P2 | 精确 r1 state selection 只支持 P1→C；不得支持 P2；queue/resource/context别代次拒接。 |
| producer无Outcome但准确FIFO/event到consumerStart | 保留 conditional ordered 支持及内容产生/错误传播条件；不强迫 CPU completion。 |
| 仅 producerEnd→consumerEnd / 缺QB FIFO | 到 end 的路径不能升级到 Start；host AFTER/host read也不借用这条队列路径。 |
| consumer enqueue时current state正确，nativework中间被写 | anchor校验通过也必须发现整段 potential/known invalidator；需要host↔work桥，不能假定after对齐。 |
| 同ticket两stage / consumer in-place read后写 | 不按ticket合并；无last-read顺序则保守gap，有解析窄区间可排除读后写。 |
| 两贡献分别Completed+Ordered；其中一个失败只产prefix | 正常替代按每贡献OR后AND；已知缺字节不能让order补全，也不强迫singlebasis。 |
| Endpoint read已成功 /任意flush /准确持久化Qroot | 三种义务分别报告；只有对应协议和target/selector/root才可满足所声明域。 |
| 缺source、未知rawschema、旧generation、错实际completion/realm | 缺失留精确gap；已供矛盾FK/schema/实际端口是issue；unsupported FactRef无visibility边。 |

## 5. 现 ctx 复用及实施顺序

- `current/current_definitions/check_support`、before/after/edges 和 visit incarnation 原样复用；state只留原引用。`core_operations/core_uses/uses/results` 提供所有实际原端口；不能再复制 world 版本或 producer。
- `resolve_subject/resolve_placement/native_port/check_target/point_scope`、resolved_content_reads/原 Q registries 提供 D；P 的 resolved_writes/resolved_produced 与来源全集提供独立 source/native候选。`_effect` 当前可解析无 work Host INVOKE，后续若需共享可提成纯原效应 resolver，不改成“先造 work 才能解析”。
- order_steps/adjacency 与原 queue/access/resource/handle registries 提供既有条件顺序/身份；新增边界关系只派生 query 邻接。现有 source parser只能支持已声明 schema；不 execute provider URI、不自动装新采集器。
- 建议门次序：**V0合同**→P补 nonwork实际子集+target lifetime关联→混合边界/协议parser与准确scope→全量invalidator与interval/lifetime检查→Host/Queue/Endpoint联合矩阵。缺任何一项可分批验收具体组件，但不得把该分母改称 full V/R2.3/M0–M2完成。
- 不从“现有 tests 通过/记录已声明”推出语言/native对应。无需全编译器、backend或新detector；未证事实可以完整typed保留并在精确义务中缺失，但不能用它们生成成功的支持边。

## 6. 读取绑定（SHA-256；均为源码/合同审查，非执行证据）

| 文件 | SHA-256 |
| --- | --- |
| docs/M1_RESOURCE_READY_CONTRACT.md（全文） | b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f |
| docs/M1_RESOURCE_EXECUTION_CONTRACT.md（§4–5） | 74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729 |
| docs/M1_PRODUCTION_API.md（全文） | 1c5c8125b0af07bd3253ff238e6afa77afcf0f51ffebb263792d73eb12ba600f |
| scar/ir/execution/content.py（全文） | 1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e |
| scar/ir/execution/content_validation.py（interval/subject/native/placement/consumer） | bd163c92244a06dae9e5756882124cab350ffeec09bbe22e3137278712f5b298 |
| scar/ir/execution/production.py（write/actor/produced records） | cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098 |
| scar/ir/execution/production_validation.py（effect/profile/actual result） | c824c947a3ecf745b95096cdd6b69a529c2563ed02f6b951e261783ce4bb8c1e |
| scar/ir/execution/production_query.py（universe/relevance/groups/production） | 3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab |
| scar/ir/execution/resources.py（realm/target/identity/handle/end/placement） | 657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000 |
| scar/ir/execution/resource_validation.py（lifetime/handle核对） | 3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08 |
| scar/ir/execution/work.py（origin/effect/scheduling/outcome/retention） | c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70 |
| scar/ir/execution/work_validation.py（retention及quiescence部分） | 7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b |
| scar/ir/execution/order.py（全文） | e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a |
| scar/ir/execution/order_validation.py（work/prefix/profile/event/wait/cycle） | e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba |
| scar/ir/execution/observations.py（Qrequirement/root） | 8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882 |
| scar/ir/execution/flow.py（actual definitions/after/completion） | 2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 |
| scar/ir/execution/validation.py（ctx/point/current/support/order） | a59db9e27b4eaa924c1b7973ac995a36cc59c3cfdd63c23d00832447b7d8c0ac |
| scar/ir/execution/query.py（work/order/coverage接口） | cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1 |
| scar/ir/v2/values.py（allocation/region/materialization） | 2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259 |
| scar/ir/program/resources.py（资源definition/role/requirement） | 167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f |

## 7. Root 后续问题的最终收敛：泛化因果关联优于窄类穷举

root 指出跨 activation 的 host read/callback write 同样缺少桥：`RegionActivation.entry` 本身没有 typed parent-call pairing，`point_precedes` 不跨 activation。此点成立。§2.3 的窄 anchors 是足够明确的规则模板，但不应冻结成唯一可表达形状；最终建议用一个泛化关联承载它们：

```text
OrderAssociation(id, before:VPoint, after:VPoint,
  basis:RawRecordRef | SourceEdgeRef | AccessRef | InvokeBoundaryStateEffect
        | UseRef | Unresolved,
  protocol:ProviderFactReference, source:FactSource)
```

1. 该 row 的语义固定为**声明的严格 causal-before**，没有 caller 填的 verified/status。记录表达跨层/跨 activation 的必要关系；不构造 parent operation、Work、Value、state 或 producer。具体同步调用/host acquire/queue提交/native interval仍按§2.3模板检查原锚与闭合协议，不需要为每种 native API 再造一类长寿 token。
2. 它不表示 coincidence、clock offset、同一 native 事件、区间包含或 owner identity。不得用同一对端点的正反 strict 边表示 equality；不同域的实际同点映射若后续确有必要，应是单独 typed endpoint correspondence，不从当前字段猜。区间包含可由分别有依据的因果界限表示；没有依据不补边。
3. `AccessRef/InvokeBoundary/UseRef` 是原端口锚，**单独不能证明跨 activation 调用/返回因果**。已知 actual CFG/严格 phase 顺序可以机械检查；其他规则必须保留具体 call/native pairing 与 applicability 条件。缺 pairing/协议 parser 的 row 可以完整存储为声明，query 明示 `unsupported/unparsed_assumption`；不能仅因有 FactRef 把 V 的缺失顺序、窄读取区间或 visibility 义务删去。
4. 同一个 canonical relation 的派生遍历可带条件标签：已识别结构/封闭协议的 `CONDITIONAL_PROTOCOL` 与“仅声明的 unsupported assumption”分开返回；不需另存第二张图。若路径含后者，整个所需结论仍留该精确缺口。即使前者全通，也不授 SourceAuthority/native执行真实性。
5. 拒绝准确同点的 strict self-edge、已知 actual 反向关系、联合因果环，以及原 FK/realm 已知冲突；未知跨线程/activation顺序本身不是 issue。Scope不同不一律非法：跨 process共享/host-device同步若有正确协议可表达，必须校验协议允许的域，而非强制sameprocess。
6. `EvidencePoint` 的 dataclass equality，特别是同一 MissingEvidence/reused FactRef，并非精确 clock/cut 对齐证据；不能由它推出读区间为空、操作同时或隐式顺序。BEFORE/AFTER/实际 EDGE 可用原精确 cuts；未知 source 点维持未知。

此收敛替换的是§2.3的建议存储形状，未撤回其语义 guards；§2.1非work实际建立、§2.2target退休和全区间独立invalidator仍是完整 V 必需前置。

最终范围：这是 full V 的接口/算法建议及有限验收设计；不是当前 ready、runtime protocol、完整 writer capture、free 或 transformation 的证明。M0–M2整体仍 open，没有 LeWM 性能结论。
