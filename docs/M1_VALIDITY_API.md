# R2.3-V 接口冻结与规范事实归属

状态：**限定声明接口已验收**，见[结果与未闭合项](M1_VALIDITY_ACCEPTANCE.md)。
基线 `f2b4672`，实现冻结 `550496f`；顺序见
[实施计划](M1_VALIDITY_PLAN.md)，全部义务见 [R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)。
V0 三份独立审查保存在 `model_validity/design/`。以下不授予 native 或转换权限。

## 新关系

```text
ValidityPoint = ExecutionPoint | WorkStart | WorkEnd | PrefixEnd | EventSignal

EstablishedProduction(id, write, established:ExecutionPoint,
  actual:RegionRef|ProtocolSelector|Unresolved,
  result:ValueOccurrenceID|ProviderFactReference|Unresolved,
  rule:BytePrefixWrite|Unresolved, source)

TargetLifetimeEvent(id, target:ResourceTarget, kind:LIVE|RETIRED,
  at:ValidityPoint|Unresolved, stage:RawRecordRef|SourceEdgeRef|Unresolved,
  effect:AccessRef|InvokeBoundaryStateEffect|Unresolved|None,
  protocol:ProviderFactReference, source)

OrderAssociation(id, before:ValidityPoint, after:ValidityPoint,
  basis:RawRecordRef|SourceEdgeRef|UseRef|AccessRef|InvokeBoundaryStateEffect|Unresolved,
  protocol:ProviderFactReference, source)

HostDomain(thread:HostThreadInstanceID)
QueueDomain(queue:ResourceInstanceID)
EndpointDomain(target:ResourceTarget)
VisibilityDomain = HostDomain|QueueDomain|EndpointDomain|Unresolved

CompletedVisibility(established:ValidityPoint,
  basis:RawRecordRef|SourceEdgeRef|UseRef|AccessRef|InvokeBoundaryStateEffect|Unresolved,
  domain:VisibilityDomain, protocol:ProviderFactReference)
OrderedVisibility(protocol:ProviderFactReference)

ContributionSupport(id, read:ContentReadID, write:WriteAssociationID,
  production:OutcomeProductionID|EstablishedProductionID|Unresolved|None,
  visibility:CompletedVisibility|OrderedVisibility|Unresolved, source)
```

均为 frozen/slots/exact，字段中的引用在 constructor、codec 与 validator 重新检查。
source 均复用 FactSource。新表为 `established_productions`、`target_lifetime_events`、
`order_associations`、`contribution_supports`，非空使用 execution v6；v1–v5 字节、
字段与 tag 保持，新增独立 v5 golden。ProgramGraph 不增加第二套 producer/Use/state。

## 原效果与实际范围

共享 `resolve_canonical_effect(ctx,effect,path)` 解析原访问/实际 INVOKE 输入、真实
successor/CompletionResult/formal，无 work 参数。读写模式及具体 work 的 membership
由调用者核对。开放 effects 列表缺 pair 是 gap；不能借另一个 ticket 的 effect。

EstablishedProduction 仅接 HostWrite/ExternalEstablishment；WorkWrite 继续接原
OutcomeProduction，不得以新记录绕过已知失败。Host 普通操作用原 AFTER，INVOKE 用
本次实际 EDGE；External 用原 EvidencePoint。实际 prefix 通过同一 BytePrefix parser
与几何 guard 核对，请求、actual 和原返回值分别检查。未知结果或点不补 whole。

实际 Region 与原 write Materialization 的 artifact、allocation 和准确范围关系不依赖
BytePrefix 协议是否已知。已知错接必须拒绝；无法解析的 endpoint→storage 映射保持
gap。派生的 `placement_match` 只有准确匹配为 True 时，actual 才能作为该物化的
有效贡献；不能拿一个 Mat 的版本和另一个 Region 的范围交叉配对。

LIVE 是该点此 incarnation 活着的观察关联，不是永久有效；RETIRED 结束对应 target
的生命周期。handle end 和 BorrowRelease 不变成 target retirement。stage/effect/
point/protocol 要回到原来源；若只有声明或未解析原生协议，保留条件/缺口，不能把
kind 标签当物理证明。无 core effect 的外部事实可用 None；未知本应有的 effect 为
Unresolved。已有 ResourceInstance.CreatedAt/ImportedAt 不再复制。

## 顺序与可见域

OrderAssociation 表示**严格 causal-before 声明**，不是相同时刻或时钟转换。它可表达
host/native 和跨 activation 连接；同点 strict、已知反向实际顺序、已知 scope 冲突及
联合环拒绝。原 CFG/队列协议可派生条件路径；未解析 association 仅为 assumption
路径，不能因 protocol FactRef 存在就消除 order/read-interval 缺口。

原 EEG HAPPENS_BEFORE 仅按其原 span 的 AFTER/实际 EDGE → BEFORE 方向与准确
occurrence 配对。WorkEvidenceBinding 没有 whole-ticket 起止角色；即使只供一条绑定，
也不能将一个内部 stage 的 HB 升格为 WorkEnd → WorkStart。此类关联保留 assumption
及明确边界缺口，等待可解析的原生边界协议。

CompletedVisibility 的 domain 必须匹配原读取：Host 的准确线程/进程；Queue 从实际
consumer ticket 的 Queued/queue access 派生；Endpoint 从原 placement/Q root 的
target/selector/协议派生。EndpointDomain 不强迫所有中间端点都有 Q root。

可机械处理的条件规则为：同线程原 host sequence；已有准确 FIFO/event/wait 到该
consumer Start 的 queue memory dependency。每条规则必须返回匹配的原锚与仍未
证实的适用条件。EndpointDomain 能校验原 target/Q 对应，但当前没有端点 read/
flush/persist 的实际来源协议解析器；只相同 Q FactRef 或 facet 不能使支持成功，
该协议保持 UNSUPPORTED/MISSING。此未闭合项保留到后续实际协议连接。
只有任意 FactRef、未知 basis 或未识别规则时同样不能产生成功 visibility。
不从 host/queue signal 自动提升为 endpoint flush 或 persistence。

OrderedVisibility 仅支持真实 queued consumer。目的必须 WorkStart；取自身贡献的
WorkEnd 及原路径。没有 Outcome 的未来写可使用请求 selector，但必须带成功产出及
错误传播条件；已有 terminal 结果只能用准确 actual，不得以 production=None 绕过。
失败/取消的 actual 部分仍可有独立可见性支持。

“没有 Outcome”本身不足以证明未来 pending。若准确原 stage 已携带已解析的实际
native result，而其 Outcome/Produced 对应缺失，必须保留结果未连接的缺口，并禁止
用请求 whole 作为未来产出。删除关联不能把已见 short result 变成未来完整写入。
这项守卫不从 raw payload 另造 WorkOutcome，也不授予物理 native 结果真实性。

## 查询与组合

`ExecutionIndex.validity(read_id,budget=4096)` 不接完整贡献列表。先复用 P 的全部来源
候选，再接原 writes/results/support；不只看 P 的 exact-whole current_production。
同 raw stage+production+placement+writer 的多种事实可归并；同 ticket 不足以归并。

按准确 stage/write/version/materialization/selector/consumer/domain 内部做 OR，再保留
labels 核对需求各部分的覆盖 AND；因果必需、来源对账、lifetime/stability/domain 条件
同时保留。不同版本的 lineage 或不知兼容的 writer 不能仅因几何 union 覆盖而成功。
复用 G 的准确 address-set 与共享预算；derived intervals 不新建 VG Region。

同时返回 `known_fragment_coverage`、`conditional_fragment_coverage`、
`conditional_support`、`source_reconciliation`、
`validity_conditions`、原 interval/domain、每项 alternatives、invalidators/lifetime、
预算/截断。结构匹配可为 MATCHED/MISSING/CONTRADICTED/TRUNCATED；来源/native 未闭合
与已知匹配分开，不能用单个 alwaysFalse 代替分析。

known coverage 只含准确 actual；pending 请求仅可进入带未来成功/错误传播条件的
conditional coverage。某个准确贡献有一个可匹配替代项时，其余失败替代项不否定
这个 OR；需求能由完整合法覆盖组合满足时，无需选择的旧版本或坏候选也不成为
额外 AND 义务。所有冲突及来源仍须保留，对选中内容的真实 invalidator 单独核对。

invalidator 从独立来源、全部原 canonical WRITE/RW/未知边界、target lifetime 与准确
handle end 分别枚举。producer/consumer 同 owner 不自动排除；整个读取区间均需核对。
已知 unsafe 程序可被建模并报告冲突，不把实际运行冲突当 metadata FK 错误。
不相交、区间外或准确覆盖/version-kill 才能排除；未知 alias/顺序/来源不作无写。

预算覆盖查询派生的来源遍历/关联、几何、order edges 与 invalidator 扫描，剩余预算共享；
记录/FK 与声明校验、工件解析/快照和 detached copying 成本另列，不冒称整个调用的
CPU 成本有相同上界。输出 detached。完整 source capture/native applicability 尚未
证明，source_runtime_verified/runtime_visibility_verified/transformation_authorized
保持 False。free 另需 ownership/pending/quiescence，不由 V 授权。
