# R2.3-P 来源与产出接口

本文件描述本门接口；通过情况见后续验收报告。[实施计划](M1_PRODUCTION_PLAN.md)
与 [R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)限定其职责。本接口不签发 ready。

## 1. 独立来源清单

`EvidenceInventoryBinding(id, run, manifest, index, source)` 把给定来源集合接到原 Run。
manifest 的 streams 从实际提供的源文件集合建立，不从 Work 或 WriteAssociation
反推。`build_inventory({stream_key: raw_bytes}, scopes=..., metadata=...)` 是离线封存
入口，返回两个 ProviderArtifact 与 `sha256 -> exact bytes` 字典。它不声明自己已经
捕获程序的一切写入，也不启动程序。

manifest 使用 `scar.capture-source-manifest` v1，内容为 run_metadata 与 streams；
stream 包含 key、raw artifact、profile、scope 和 metadata。index 使用
`scar.normalization-index` v1，精确引用 manifest，每个 stream 恰好一项；projection
为 normalized(recipe/bundle/coverage) 或 unresolved(reason)。字段闭合且 JSON 严格，
禁止重复键、非有限数和 bool 冒充整数。

`InventoryResolver(ExternalSnapshots(..., artifact_bytes=...)).resolve(manifest,index)`：

- 校验原 bytes/hash/size/schema。原始 JSONL 以物理 LF 分行，不使用 splitlines。
- 仅重放固定本包的 SCAR_NORMALIZE_V2 recipe，比较完整 bundle 和 coverage。
- recipe 源码指纹来自固定本包 normalizer 文件；不读取其声明的任意路径，不执行
  调用者代码。版本未知保留 gap。
- 一次 resolver 的 bytes/artifact/line/line-size 预算独立计量；截断源保留 pending，
  不把已扫描前缀冒充完整集合。没有 bytes 是 gap，已提供但矛盾是 issue。
- format_replayed 仅表示这些输入文件投影一致。dropped events、截窗、opaque、
  未知 alias/外部写入及跨进程边界继续保留缺口。

同次查询中相同 manifest/index 的重放复用；不同清单各自受上述预算限制。
这不是全模型来源解析总量的上界，不能把 production 的遍历预算描述为总解析预算。

原始 artifact hash 对应解压后的逻辑 JSONL 字节，不混用压缩载体 SHA。URI 不打开。

## 2. 端点与身份

`InventorySourceRef(inventory, stream)` 选流；`RawRecordRef(source,line,sha256)` 选准确
物理行；`SourceEdgeRef(source,edge)` 和 `SourceEndpointRef(source,endpoint)` 选原 EEG
边/端点。源 bundle 的 strict decoder 已核对其 EEG、ValueGraph 等跨组件关系，所以
同 bundle 的版本/物化/region/allocation 对应可直接派生，无需手填每条桥。

`SourceEndpointBridge(id,endpoint,target,source)` 用于独立 artifact 范围之间的显式
关联。target 为 VersionRef、MaterializationRef、ObjectRef、RegionRef 或 AllocationTarget。
同一 exact ValueGraph 中矛盾的原身份是 issue；ObjectRef 也可接精确 EvidenceGraph
的 object registry。不同 artifact 的裸 ID 不比较。
跨图声明仍需实际身份依据，不能当相等证明；多个可能映射不擅自选第一个。

## 3. 写入与结果

`WriteAssociation(id,stage,writer,production,placement,evidence,source)`：

- stage 引用原 raw 行、源边或 native 输出槽；未知为 Unresolved。
- writer 是 WorkWrite(ticket)、HostWrite(occurrence)、ExternalEstablishment(point)
  或 Unresolved。直接 host 写入无需虚构 WorkTicket。
- production 是 ValueProduction(原 ValueOccurrence) 或 StateProduction(原 AccessRef /
  InvokeBoundaryStateEffect)。INVOKE 必须接本次实际 successor/CompletionResult/formal。
- placement 复用 D 的 StorageContent/EndpointContent；shape/strides 等从原图解析，
  不复制一份 producer 或状态。源 PRODUCES 表示结果观察，不自动证明实际写入。

`OutcomeProduction(id,write,outcome,frontier,actual,rule,source)` 引用原 Outcome。
StateProduction 的 frontier 是原 effect_frontier 下标或 Unresolved；ValueProduction
没有适用的 state frontier，必须为 None。actual 为原 RegionRef/协议 selector/Unresolved。

固定 `BytePrefixWrite` profile 解释原行 metadata.scar_native_result 的五个字段：
schema=`scar.native.byte-prefix-write`、schema_version=1、stage、requested_bytes、
written_bytes。计数需 exact nonnegative int，written≤requested。Outcome.protocol_result
须指原 raw artifact 的准确 `#L{line}/metadata/scar_native_result`，或可解码的原整数
结果；任意 FactRef 不形成证明。只有同范围/分配/起点、uint8、一维连续的原请求和
实际 Region 才可解释为字节前缀。其它布局和协议保留具体 gap。

COMPLETED 不扩大实际范围；FAILED/CANCELLED 保留已观察的部分。wrapper 与内层原生
阶段分开。尚无 Outcome 不是失败；任何结果也不自动证明 quiescence 或可 free。

## 4. 只读公开查询

`ExecutionIndex(model,program, value_graphs=..., evidence_graphs=..., semantic_graphs=...,
artifact_bytes=...)` 使用新建严格快照；每次内容查询重新核验调用者可变 catalog。

| 查询 | 返回与限制 |
| --- | --- |
| `production(content_read_id,budget=4096)` | 从读取与相关 Run 的全部独立来源清单枚举；返回 demand、lineage_prerequisites、candidates、current_production、possible_invalidators、unresolved_relevance、pending_sources、gaps、budget_used、truncated。 |
| `write(write_id)` | 原 writer/value/effect/placement/stage/evidence 及逐项关联缺口。 |
| `outcome_production(id)` | 原 Outcome/frontier/protocol_result、实际 selector、请求 selector、parsed profile 与条件。 |

production 查询不接收“完整贡献列表”。候选 ID 由 inventory/stream/原 edge 或
raw line+SHA 派生，不依赖提交的 Write/Work 行。缺 inventory 不作空集满足。
lineage 是来源前提，不等于当前物化的 AND writers；重叠和 alias 另作潜在失效关系。
只有精确源边或物理 raw stage 对应才能关联贡献，不借同 host/ticket 猜测。多个来源
事实仅在同准确 physical stage、production 和 placement 时合并为一个关联视图。

查询预算用于 lineage、源边/raw 行与关联遍历；源工件重放/快照另有预算，不把其
成本藏进 graph traversal 计数。截断保留 unresolved。所有结果 detached；
source_runtime_verified、readiness_verified、transformation_authorized 均为 False。
current_production 是声明关联视图，仍需原生来源、完整性、整个读取区间与可见性核验。

Execution schema v5 增加四个默认空表；v1–v4 字段/tag/字节保持，ProgramGraph 不变。
这一步接的是图之间的关系，没有添加优化规则，也没有声明完整自动建图完成。
