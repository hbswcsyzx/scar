# P 前设计审查：来源写、原 effect 与实际 produced subset

状态：**Proposed**，只读设计，不是 P 验收。工作基线由 root 指定为 clean `5ab22f8`；
本代理未调用 git、测试、probe、GPU、LeWM workload，也未改产品/文档/测试。
所有建议保留 `source_runtime_verified=False`、`transformation_authorized=False`；
SourceAuthority 不因结构匹配、协议解码或 COMPLETE 字段变为 True。

## 1. Observed：当前能知道什么

- `work.py` 的 ResourceOutcome 仅记录准确 ticket、kind、protocol_result、
  effect_frontier、coverage 和 quiescence。`work_validation.py:311–349` 校验 frontier
  的原 effect、实际 INVOKE successor/result/formal/location、ticket/run 等；
  protocol_result 为 ValueOccurrence 时仅核 FK/run，**不解析数值，也不证它就是
  本次结果端口**。此为 R2.1 明示边界，不是要求倒改旧门。
- `AccessRef(opocc,index)` 保留原 StateAccess；`InvokeBoundaryStateEffect` 保留原
  state input 和实际 completion/formal。两者都不是 native byte-write 证明。
  `Footprint.INTERVAL/WHOLE/full_overwrite` 没有 byte 单位（`program/model.py:107–126,
  370–402`）；不得把 [0,16) 直接解释为 16 bytes，也不得据 RW 推全写。
- D 的 ContentPlacement 已准确连接 scoped materialization、storage selector 或
  endpoint selector/target；其 state、引用与内容版本的对应仍有 gap。
  它可复用为写目标，但不能把 ContentRead 换个名称当写入证据。
- ValueGraph Materialization 的 producer 只是裸 OperationInstanceID；ready_event、
  validity_scope/evidence 字符串没有 exact ticket/stage/outcome/range 语义。
  ValueVersion/provenance 是逻辑血缘，不自动是当前物化的必要 AND writers。
- EEG 可严格解析 OBSERVED_WRITE/PRODUCES/OVERWRITES/MATERIALIZES/ALIASES 的
  typed endpoints。ValueObservation 有 version/materialization/operation，但 role
  是字符串、metadata 是开放 dict；没有规定写阶段、字节数、exact result ordinal。
  `v2.codec.evidence_from_dict` 是图 parser，不是 short-write 协议 parser。
- 现 `trace.reader` 只重建旧 Event/effect；call_trace_reader 捕获 return_ref，
  没有通用返回整数解码合同。不能把对象引用、ValueOccurrence 或 metadata 中
  随填的 count 直接作为已解析的实际长度。

**决定：** 分开建立两条可检查关系：
`source 写阶段 → 原执行/effect/目标` 与 `准确 Outcome → 该阶段实际产出的 subset`。
禁止 `Produced(COMPLETE, FactRef)` 同时自证这两条关系。

## 2. 最小关联记录草案（命名/字段待 root 冻结）

只加 association，不迁移原 producer/SSA/state/materialization。

```text
WriterOrigin = WorkEffect(ticket, canonical_effect)
             | HostEffect(AccessRef)
             | HostValue(ValueOccurrenceID)
             | ExternalEstablishment(ExecutionPoint, state_support)

WriteAssociation(id, origin: WriterOrigin,
                 placement: D.ContentPlacement,
                 basis: EvidenceEdgeRef | NativeWriteRef | Unresolved,
                 source: FactSource)

OutcomeProduction(outcome: WorkOutcomeID, frontier_index: int,
                  write: WriteAssociationID,
                  rule: ClosedProtocolRule,
                  payload: ScopedProtocolRow | Unresolved,
                  source: FactSource)
```

- `canonical_effect` 原样复用 AccessRef/InvokeBoundaryStateEffect，不增加复制的
  mode/before/after/world。其当前 state 和真实端口通过现 flow/canonical_effect 派生。
- OutcomeProduction 不重复 ticket/effect；从准确 Outcome/frontier_index 派生，
  核对与 WriteAssociation 的 WorkEffect 相同。不同 outcome 的条目不互借。
- `NativeWriteRef/ScopedProtocolRow` 是受 schema/digest/版本约束的**原来源行 locator**，
  由封闭 parser 读取，不能是可执行 provider、任意 Python callback 或字符串规则。
  若本批仅支持 EEG，则 NativeWriteRef 尚未解析时明确 unresolved，不假装已实现。
- 真正 write stage 身份由来源 parser 产生：准确原 event/subevent/phase key。
  不接受用户随填 stage=0 或仅 `(ticket,effect,materialization)` 当唯一写。
  一个 coarse effect 可包含多次 native 写；一张 ticket 不是一次 write。
- HostEffect 是真实无 Work 的 host 写，不造 CPU ticket/ResourceOutcome。
  HostValue 仅标 immutable Data 的原逻辑结果/常量；没有明确物化建立依据时不能
  从该值直接推 storage bytes。ExternalEstablishment 保留供应方真实点/内容声明，
  不伪造代码 operation；未知 current/native 对应继续 gap。
- Host/External 分支的已建立范围从它们的准确 source/protocol 派生，不强塞
  ResourceOutcome。它们可成为生产贡献，但没有“伪造 work 已完成”这一中间步骤。

## 3. 机器校验的最小算法

### A. 写来源与执行/effect/selector

1. 用 D 共享 exact detached snapshots 解析 source 与 placement。核 mat/version/
   allocation incarnation/target/FK；known mismatch issue，missing graph 保留 gap。
2. EEG basis 必须是能表示写/物化的原关系；OBSERVED_READ 不作写。源 endpoint
   若仅为 Object/Allocation，不知道版本/selector，不能升级为目标 mat 的生产。
   ALIASES/OVERWRITES 保留为 potential invalidator；并不当然产出所需版本。
3. WorkEffect 核准确 ticket、原 effect 及源 instance 的 exact WorkEvidenceBinding；
   HostEffect/HostValue 核真实 occurrence/definition 的现 binding。开放多对多缺
   pair 是 gap，不凭其它 pair 否定、不借同 host/parent 自动补 join。
4. 普通 Access 必须 WRITE/RW，READ-only 不能当 writer；位置/reference/before/
   after 由原图派生。INVOKE 只得 state transport，不能凭 NORMAL/RW 捏 mode 或
   footprint；需 native/source rule 解释哪次实际状态变化对应写目标。
5. 目标是准确 D placement。Storage selector 必须在原 mat 区域内；endpoint
   selector 必须解释为该准确资源/当前选择协议。Footprint 到 byte 地址/元素序
   的映射必须来自明确且可解析的规则，未知给 `write_byte_mapping_unresolved`。
6. 聚合原来源关系时保留逐行依据。只有 parser 证实是**同一原写阶段**的
   OBSERVED_WRITE/PRODUCES/MATERIALIZES 才归为一个 contribution；不能仅因
   同 ticket/同 effect 去重。缺 stage 则报告 `write_stage_identity_unresolved`，
   不既把两行强当独立 AND writers、又任选一行丢掉另一阶段。

### B. Outcome 到实际 subset

1. outcome/ticket/frontier_index 的 FK 与 exact effect 必须成立；不能只在
   WorkSubmission.effects 中找一个“类似 effect”。若 frontier 未登记该阶段，
   COMPLETE frontier 的确切矛盾 issue；不完整 frontier 则未对齐 gap。
2. actual INVOKE edge 必须一致。RAISE partial state 仍可接真实 FAILED/CANCELLED
   写；NORMAL 不是 device COMPLETED，host RAISE 也不删已提交 work。
3. `protocol_result` 为 ValueOccurrence 时解析其真实 origin/route：OperationResult
   或本次实际 landing 中的 CompletionResult→formal；普通精确 copy 可沿现
   formal_route/UseOccurrence 追溯。不能拿同 run 的旧结果、forwarded input 或
   另一 traversal 的 formal 冒充本次 result。Native slot 复用 P1/D 的准确 position，
   不把 native position 当 core operand index。
4. 仅有 ValueOccurrence **没有数值**。需封闭 parser 读准确 source payload，并
   把 scalar observation 接到上一步原结果端口/本次 ticket+stage；FactRef 仅定位
   不等于完成这项解析。若 protocol_result 是 ProviderFactReference，也必须解析
   所指具体 row；Unresolved/未支持 schema 给具体 result-payload gap。
5. rule 派生实际范围，核请求范围、计数单位、结果 kind、target offset、整数
   exactness/bounds；比较所有声明与来源，不能让 caller 自选一个结果范围当证据。
   缺/未知计数不能变成 0，终结 kind 不能变成 requested whole。
6. FAILED/CANCELLED 可保留准确非空部分；不推出剩余部分已写、不推出 quiescence。
   COMPLETED short write 只产实际前缀。多阶段各核各自结果，不用最终累计 count
   重复授予给每个阶段；若协议仅有累计 frontier，adapter 必须按原阶段区间作分解，
   分解未知则保留 aggregate gap。

## 4. 一个可实施的有界 native adapter

建议首个 profile 是抽象 `COUNTED_CONTIGUOUS_PREFIX_V1`，不是宣称任何 OS/CUDA/
LeWM API 自动满足它。其 applicability 必须有准确版本/source 条件，不能按函数名猜。

- 输入只接受已核 source row、原 output/result route、请求 selector、单位与
  effect/target binding；source payload schema 为闭合 keys/types，不执行应用代码。
- schema 明确 `requested_count`、`transferred_count`、unit=BYTE、准确 offset、
  terminal kind、stage identity 和 result-port association。拒 bool/负数/超界/重复
  JSON keys/未知字段；解析量和整数位宽受预算限制。未知类型/超预算为明确 gap。
- 真正 scalar payload 必须来自原被引用 artifact。可以把规范 LiteralOrigin 的
  exact int 当声明内已知值，但非 literal 返回值必须有 source scalar observation；
  不能仅因 DataValue 类型是 int、或给 ValueObservation.metadata 加 `count=4` 就采信。
- 对连续 byte selector `[b,b+n)`，source 计数 q 且 `0≤q≤n` 时，派生 `[b,b+q)`；
  q=0 仅是已知空写，不撤销源完整性/副作用/持久化义务。若 rule 声明请求是
  “元素”或源 layout 非连续，则不适用；不以 bbox 填洞。
- 派生 range 是**原 placement 的计算结果**，不是新 StorageRegion/Materialization
  或 state producer。首门可只核准确原 RegionRef 候选，无需新增几何描述系统，
  具体决定见下节。现 G 公共入口仅收 RegionRef；若将来允许原图没有对应 region
  的任意 prefix，需要单独的薄计算视图支持，不能声称现 G 已自动支持。
- Endpoint byte prefix 使用准确 target+协议 cursor/offset；不是 memory allocation。
  不支持的 endpoint 选择/单位继续 typed gap。

这种 adapter 证明的是“按所供闭合来源/规则推得这个声明范围”；来源是否真实捕获、
native applicability、写值是否就是所需 logical version 及整个区间稳定/visibility
仍独立。它不设置 SourceAuthority=True，也不取代后续 V。

### 4.1 与 root 收敛：首 profile 只核原 RegionRef，不新增 range/producer

root 提案 `RawRecordRef` 的 whitelist metadata result + 原 requested/actual RegionRef
可以作为上述 profile 的最小实现，**不要求实现任意 computed-selector 接口**。
必要 guard：

1. RawRecordRef 经原 raw bundle manifest/normalize index 找到准确 event row、native
   stage 和 source scope；tuple 顺序、同 host/相邻 event 不能代替真实关联。
   metadata 只按有版本的闭合 schema 解析；任意 payload 中同名 count 不受信。
2. requested/actual RegionRef 核同 artifact identity、同 allocation incarnation；
   均为原 mat 内准确 rank1 uint8、stride=(1,)、layout 已支持、同起点的连续 byte
   region。shape 分别准确等于原 native requested_count 和解析 produced_count。
   `0≤produced≤requested`，exact int 非 bool，处理预算/溢出，未知 geometry 不降 whole。
3. selector 是核对**原来源计数**的候选，不是调用方自填 actual 后反过来决定结果。
   错 shape/offset/allocation、错 outcome/frontier_index/effect、错原 result/native stage
   是 issue；缺原记录或 scope/current-state/native pairing 为精确 gap。
4. COMPLETED/FAILED/CANCELLED 与 count 适用条件来自该封闭 profile；FactRef/source
   status 本身不证明成功、长度、完整 writer coverage 或 content version。

**受控 witness 的两个语义界限：**

- 若真实 `pwrite` 返回 4 之后 wrapper 主动 raise，这是 native write 完成与 host
  RAISE 的分离见证，不能标成“pwrite 原生失败且部分写 4”。若 ticket 定义为包含
  后续失败的 aggregate 动作，需明确该 aggregate 合同和各真实 stage，不挪用 syscall
  的 terminal kind。它能证明 host raise 不抹去已写内容，不能证明所有 OS 失败语义。
- 若实际 `pwrite(fd,payload[:4],offset)` 请求的是 4，不能把 desired output 8 或外层
  wrapper request 8 当成本次 syscall requested_count。应分别保留 desired/requested
  层级；4/4 的成功阶段相对需求 8 仍不足，但不是该 syscall 的 8→4 short write。
  真正 8→4 的 adapter 正例必须有对应真实协议来源，而不能靠 metadata 改写请求。

以上是 Proposed guard，不是本代理已运行的 OS/CUDA witness。

## 5. 建议查询/validator API 与范围

```text
production_errors(ctx)                         # 追加 issues/gaps，不递归建 Index
ExecutionIndex.write(id)                       # 原 source/stage/effect/placement/links
ExecutionIndex.produced(write, outcome=None)    # 原 Outcome/frontier/result route、派生范围
```

结果应分别列 `requested_selector / derived_produced_selector / result_route /
source_rows / stage_key / correspondence / derivation_conditions / gaps`，不返回 ready。
资源分支没有准确 outcome 时 actual produced 为 unresolved；可以保留 pending 的
条件生产关系供 V 的 Ordered 分支审查，但不把顺序当已观测实际写入。
查询每次重核可变外部图并 detach，沿用 D 的 artifact identity/authority 边界。

P 的 source-inventory/universe 子门仍必须与这些关系对账：删 association/Work 行
不能删掉源 writer；不能靠 COMPLETE 枚举字段声称 exhaustive。当前建议聚焦
生产范围与 effect/result 接线，没有声称只做这两张表就关闭完整 P。

## 6. 必要验收反例（本轮未执行）

| 场景 | 正确结果 |
| --- | --- |
| COMPLETED，请求16，准确返回4 | 仅[0,4)，请求whole仍缺；full_overwrite/COMPLETE不补足。 |
| FAILED/CANCELLED，阶段1写4、阶段2结果未知 | 保留阶段1；阶段2未知，不擦成空或whole，不授quiescence。 |
| 同ticket两个真实阶段，或一阶段三种EEG关系 | 前者不去重；后者仅按已解析同一stage归组，未知不猜。 |
| 旧NORMAL count/另一visit formal接当前RAISE | 原actual completion/result路线冲突issue，不能靠同run通过。 |
| READ-only access或普通Footprint(0,16) | 前者不能当写；后者无byte映射不得推出16 bytes。 |
| 目标旧mat/version/另一allocation/event代次 | 已知身份冲突issue；source适用缺失具体gap，不按地址复用。 |
| Host初始化、external establishment，无work | 保留准确原effect/value/source点；不伪ticket/outcome，缺内容/物化对应仍gap。 |
| 同host两work，另一个result/source | 缺exact pair保持gap，不补join；明示错outcome/frontier/result端口issue。 |

## 实际读取源码 SHA256

| 路径 | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` | `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729` |
| `docs/M1_CONTENT_CONNECTION_API.md` | `894c22d9a724981e049dc5e7b1fafa4092beb3834753fc7dfdd7c4da1eb4ae27` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `scar/ir/execution/content_validation.py` | `ebff98a37d99583fe1c2a103e25639bba1e536697bdcf60d9276474754d59a23` |
| `scar/ir/execution/query.py` | `b5c56756e7d81e162c71edf32da477092b2d3daba09450b59a94fa142396ea8a` |
| `scar/ir/execution/coverage.py` | `43a0f21c7a5e5815f3e4408dcf76ff39eeb96f30f4fc0af655a8ccf0aff3a32b` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `scar/ir/program/native.py` | `17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/evidence.py` | `dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5` |
| `scar/ir/v2/codec.py` | `511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b01b4224c0ba751fcc1` |
| `scar/trace/reader.py` | `a36b508f5a4744570af2b9b095ffce9045b4a3c83e5e0dc90d4f6a3359c2d8b3` |

无实现/运行验收、无 backend/detector、无完整 P/V、无 M0–M2 关闭结论。
