# R2.3：消费者、生产贡献和可用性关系合同

基线：R2.2 `2d6f1d4`。R0 的[资源执行合同](M1_RESOURCE_EXECUTION_CONTRACT.md)
仍是上位关系约束。本文件固定必须连接的关系、判定规则及实施顺序，不把
尚未实现的记录字段命名当成已完成接口。本轮不新增 detector、backend 或 lowerer。

## 1. 审查发现：顺序不是内容

现模型能回答原 Use/StateAccess、实际 state occurrence、work ticket、queue prefix
和条件性的 WorkEnd→WorkStart。ValueGraph 能给出版本、来源、物化及 allocation/
region。但二者的命名空间不能直接合并，以下事实还不能由现接口派生：

1. 一个原端口本次实际表示哪个逻辑内容及物化；传递引用不等于读内容。
2. 同一 host call 提交多个 work 时，哪个 work 读取哪个输入和 selector。
3. 哪些工作确实构成目标内容，哪些只是血缘前提或可能使内容失效的 writer。
4. host 点上的当前状态是否持续覆盖实际资源读取区间。
5. 哪个线程/队列/端点在什么协议条件下可以观察内容。

不采用“在 order path 上增加 ready=True”的设计。先接准确对应和必要依赖，
再判定每个贡献的替代支持；已知矛盾、缺失与协议条件分开报告。

## 2. 规范事实的归属

| 事实 | 唯一规范来源 | 本层新增关系的职责 |
| --- | --- | --- |
| 操作、Value、Use、StateAccess、completion/CFG | ProgramGraph + ExecutionModel occurrence/实际 transfer | 引用准确端口，不能复制另一份 producer 或后态。 |
| logical version/provenance、allocation、region、materialization | 精确 ValueGraph artifact | 映射 denotation、selector 和实现；地址/shape/前几个值不生成相等证明。 |
| 实际 operator/native writer/read、时间、capture 事实 | 精确 provider/EEG artifact | 保留源端点、范围、缺失及多对多对应。 |
| work/outcome/quiescence/retention/order | R2.1/R2.2 | 连接准确生产/消费工作，不能由 COMPLETED 或 retention 推内容完整。 |
| 观察要求 | 真实 Q 合同及其 scoped artifact/准确输出或端点要求 | 定义必要观察根；不是从路径、EXTERNAL facet 或 close 猜根。 |

引用的身份至少包括 artifact 的 hash/schema/byte-size 与原 typed ID。相同裸
MaterializationID、ObjectID 或 AllocationID 不能跨 artifact 自动合并。URI 不由
codec/query 自动读取。缺少图保留 gap；已提供但 digest/schema/FK 矛盾必须拒绝。

## 3. 消费内容、端口和工作

以下是必须实现的关系，不是第二套数据流图：

- **Content denotation：** 原 UseRef/AccessRef 或明确 Q root → 本次实际
  ValueOccurrence/读状态、scoped logical version/MaterializationRef、selector
  和准确 basis。版本及 region/allocation 从原 ValueGraph 派生；若保留独立
  expected version，必须与原物化及 source basis 一致。不能只往 Use 旁填一个 ID。
- **Reference/content 区分：** 对象 identity 的 denotation 不永久绑定初始内容。
  同一引用读取内容必须接当前 state 和 selector；同一 storage 的新内容版本也
  不能自动继承旧证据。Data、Reference、State、Binding 和 Protocol 不互相冒充。
- **Consumer-work correspondence：** 存在实际资源/native work 时，原读取端口 → 确切 ticket、原读取效果及
  native/provider 实际输入槽映射。仅有相同 WithinOperation 不足以选中一个 work；
  wrapper 内多个 kernels/拷贝分别保留对应，缺输入匹配不补默认归属。直接 host
  read 可接原 OccurrencePoint/协议读取区间；真实外部观察根可接其观察点/区间。
  没有实际 consumer work 时不为满足字段伪造 ticket，未知消费方式单列缺口。
- **Read interval：** 对实际资源 work，有 last-read 事实时引用它，否则至少覆盖
  保守的 WorkStart..WorkEnd；直接 host/外部观察使用上述准确点或协议区间。
  host enqueue BEFORE/AFTER 的状态支持不能替代资源 work 的整个读取区间。
- **Observation root：** 引用现存 ContractID 的精确 semantic artifact、准确
  输出/端点要求、selector、真实观察点、协议条件和来源。缺合同或对应时明确
  unresolved，不能伪造一个代码消费者。文件 buffer、flush、持久化要求分开。

INVOKE 沿实际 successor/CompletionResult/formal。其 boundary effect 不自带
read/write/byte-footprint 证明；native 输入/输出映射另列条件。普通 StateAccess
的 Footprint 单位不是当然的字节数，尤其不能直接把 INTERVAL(0,16) 当 16 bytes。

## 4. Selector 与 placement

- Storage-backed 物化从原 mat.region→region.allocation 解析；选择范围是带
  artifact 的原 RegionRef，不复制 shape/stride/offset/dtype。
- Endpoint-backed 必须显式给实际 ResourceTarget、协议 selector 及当前 state/
  源映射；mat.region=None 不表示文件、NVMe 或虚构 CPU allocation。
- 未知 placement/selector 保留 gap，不能当作 whole 或与其他 writer disjoint。
- 几何回答相对声明地址集的覆盖，不回答内容版本、值相等、native identity、
  allocation 有效期、完成、visibility、ready 或可 free。

共享几何实现及精确验收约束见 [geometry 实施门](M1_RESOURCE_COVERAGE_PLAN.md)。
相同逻辑版本的两个物理副本仍有不同 placement；两份 bytes 相同不等于可在
任意消费者/设备/生命周期中互换。

## 5. 生产集合必须从来源派生

EEG 原关系可提供候选清单，但目前仍有缺口：endpoint 的 Mat/Version ID 无
ValueGraph artifact scope，operator instance 无 exact WorkTicket 映射，边没有
写入 selector，且图本身没有完整 write-inventory coverage。因此新增一个
ProductionCoverage(COMPLETE, FactRef) 不能闭合这些缺口。

实施时至少建立：

1. 精确 EEG endpoint ↔ 精确 ValueGraph 内容/物化的 scoped correspondence。
2. 源 edge/native 输出 ↔ exact ticket/原 effect/selector 的对应。保留源事实；
   原 OccurrenceEvidenceBinding 或同 host occurrence 不能独自解决多个 ticket。
3. target/run/window-scoped coverage 来源及可核对 inventory/边界；未知 alias、
   外部写、截窗、graph break 和未解析范围不得被 COMPLETE 标签抹掉。

查询从上述原来源派生 obligation universe，调用方不传可任意删小的 required
tuple。枚举候选时不能只挑 PRODUCES；OBSERVED_WRITE、OVERWRITES、MATERIALIZES
及 ALIASES/已知 storage overlap 都有独立作用。分别归类：

- **逻辑血缘前提：** 解释这个版本如何得到，不当然是本次物化的 AND writers。
- **当前物化生产贡献：** 确实产生目标版本所需 selector 的工作与原输出。
- **潜在 invalidator/conflict：** 可能覆写/别名的工作，不冒称也产同一版本。

同一物理 writer 的多种关系事实保留为该贡献的依据，不能误计为多个独立贡献。
也不能把所有祖先或历史 writer 平铺成当前贡献。仅在准确版本/selector 与完整
覆盖/kill 依据成立时排除旧 writer；可能重叠而未能判定时保留具体冲突/缺口。

删除 contribution 而源 writer 仍在必须被对账抓住；连 work 行也删，源 edge/
inventory 的对应仍缺失，不能变成空集满足。空 selector 的几何可为空，但源
完整性、合同/端点和副作用义务不因空字节集自动消失。

## 6. Produced frontier、失败与取消

实际 produced selector 要回到原 Outcome 的准确 effect_frontier 条目、协议结果
及该 contribution。它不是新结果 producer，也不能用整个 allocation 大小代替。

- COMPLETED 不意味着整个请求范围写完；short write 仍只有实际长度。
- FAILED/CANCELLED 不抹去已发生的部分写入，也不自动 quiescent。
- 有准确 Produced + visibility 支持的部分可支持相应部分需求；不能扩大到 whole。
- 正确的 order path 不能修补已知失败造成的缺失内容。
- 尚无 Outcome 不是失败。Ordered 支持保留成功生产/错误传播条件；不假装已观测
  数值产生。已知失败与条件矛盾时不能继续沿该替代项授权。

## 7. 每个必要贡献的 AND/OR

对由来源派生的集合 D：

```text
AND(c in D : OR(匹配 c 的 CompletedVisibility,
               匹配 c 且到本 consumer Start 的 OrderedVisibility,
               该协议明确允许的其他准确支持))
```

A Completed、B Ordered 是合法组合，不要求全部走同一 basis。缺 B 的支持仍
是缺失；存在一条 A 的顺序不能覆盖 B。不同 contribution、content、placement、
consumer 和 domain 的支持不能分别 union 后交叉配对。

CompletedVisibility 仍须准确 Produced 和域建立依据。OrderedVisibility 复用
R2.2 的 producer End→实际 consumer Start 条件路径，不能用 ConsumerEnd 或包含
consumer 的 PrefixEnd 替代。path budget 截断是 unresolved，不是 independence。
ReadyEvidence 可服务多个匹配消费者，不是一次性 permit。

## 8. 有效期和 visibility

内容有效性覆盖生产/建立支持至实际读取区间；核对 current state、alias writes、
allocation incarnation/retirement 和端点选择。保留 allocation 的 work retention
只保证借用关系，不保证内容稳定；两个端点状态一致也不证明中间无写入。

visibility 是 Host / Queue / Endpoint / Unresolved 的判别联合：

- Host：准确 process/thread/address-space 以及建立点/协议。
- Queue：确切 consumer work/queue/context、读取映射和到 Start 的顺序；不授 host
  read 或其他 queue。
- Endpoint：确切资源、selector、观察/flush/persistence 条件；不自动提升层级。

旧证据保留为历史事实；新的逻辑版本、物化/分配生命周期、run/process/domain
需要重新匹配。结果报告原需求、贡献、替代项、冲突、条件和逐项缺口，不输出
无条件 ready=True。native/runtime/applicability 与 transformation authority
单独验收，free 还须独立的全部 pending access/ownership/quiescence 义务。

## 9. 有序实施和关闭条件

| 顺序 | 必须接通 | 关闭依据 |
| --- | --- | --- |
| G 共享 selector 几何 | 原 scoped RegionRef；MatRef 公开查询；预算/精确 byte-set 覆盖。 | holes、empty/zero/negative stride、dtype、不同 artifact/分配、missing graph、预算反例；独立复审及冻结回归。只是几何子门。 |
| D 内容/读取接口 | 原端口→denotation/placement；Q root；exact consumer work/read interval。 | mutable buffer、同 host 多 work、错误版本/selector/实际 completion、endpoint 无伪 storage。 |
| P 来源/实际生产 | scoped source endpoints、writer inventory 与贡献分类；Outcome 实际 produced。 | 删 contribution/work 不缩 universe、重复关系去重、partial failure/cancel、未知 alias/截窗。 |
| V 有效性/可见性及 Ready 组合 | 每贡献 AND/OR、读取区间、Host/Queue/Endpoint。 | 混合支持、consumer Start、旧内容/分配/域、稳定借用反例；整个 R2 联合验收。 |
| R3 全过程组合 | load→consume→save/flush/close 与合同观察根。 | 原 producer/Uses/state 唯一、共享资源和错误路径；最后核对完整 M0–M2。 |

上述义务不会因当前实现顺序删减。字段尚未收敛的 D/P/V 不抢先堆表、声称
implemented 或启动新 backend；先用本合同及真实有界反例审查必要对应。完整
第一阶段完成后按用户要求先停下来讲解模型，再进入自动全程序建图/化简。
