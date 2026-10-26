# C02 关系缺口：有界声明审计，未完成全集

实际审计 **exit1 / 180.003484 秒，PARTIAL_BUDGET_STOP**。没有重试、扩大预算或修改原件；不能将下面的部分分布外推为全部 12,541 个缺项。原 `AUDIT.json` 保留中断时的 `BUILDING` 和栈；`ACTUAL_TERMINAL.json` 明确其终态及非原子 counter snapshot。

原 manifest 的 SHA `98faaa2fe721ccd1377dcfdea0ed28278f4577f4a244099d23fe077ec9df91d7` 已对保留 receipt 核实。其原声明为 24,082 work：11,541 有 native/source，12,541 两者未接；本次不重新授予旧 producer 或新版 public query 资格。四个未改 IR/codec/store/navigation 源 SHA 与 C02 receipt 一致，直接 strict codec 解声明；新版 helper 的 producer guard 未调用、未放宽。

| 本次 Observed | 数量 / 范围 |
|---|---:|
| 完整 stored SHA、decoded SHA/bytes/rows 到 EOF 的 work chunks | 75 / 115，15,908 行 |
| strict 解码计数，包括下一个 chunk 的部分行 | 16,087 / 24,082 |
| 其中 native/source 都未接 / 都已接 | 8,477 / 7,610 |
| 已完整完成原因归类的未接 work | 8,476，全部同类 |
| 每个已解码 work 的关系数 / distinct host 数 | 3 / 2 |
| 未接 work host 的索引匹配 | 16,954 条 ETO `cpu_op` scope 路径；8,477 条 Kineto `cuda_runtime` 路径；其 exact native-ID join 均为 0 |

三个 host 关系是同一 ETO scope 的两种准确证据路径（`provider_scope_association`，以及该边接 `submits_work`），加一个 Kineto runtime 的 `submits_work`；两条 scope 路径不应被算成两个动态 host。已解码 gaps 为 `NATIVE_OCCURRENCE_UNRESOLVED=8477`、`SOURCE_CONTEXT_UNRESOLVED=8477`、`STATE_CONTENT_READY_UNPROVED=16087`、`STATIC_BODY_MEMBER_UNREVIEWED=1593`。统计中断在第 8,477 个缺项的 host 详情构造，因此原因分类计数比缺项少一；未把该快照包装成完整事务。

**Observed 机制。** 已完成原因归类的 8,476 个缺项不是找不到原 host，也不是空 pid/tid/raw reference/external id：它们的 provider host 是原 ETO `cpu_op`，但其完整原 `opinst:…:eto:…` 身份不在原 `native` 表的 canonical entry INVOKE 集合。对应 Kineto runtime 也没有该 exact-ID 连接。相关 25,431 条 host 路径的 pid/tid/external id 均为整数，raw reference 为 ETO nodes 或 Kineto traceEvents locator；这只描述保留字段，不证明跨 provider thread ID 等价。

**源码解释 / Inferred。** `scar/analysis/fragment_relations.py:311–327` 只把既有 ExecutionModel 中 canonical entry INVOKE 的原 ETO instance 写入 native 表；`:470` 按完整 instance 做等值 join。`:417–418` 对没有 native 的 host 不进入 source 查询，所以此类 source 缺失是该连接链的下游断口，不能解释为 source inventory 本身缺失。这里尚不能判定是 native batch 的覆盖范围、原 scope 选择，还是本应补充另一种有证据的 occurrence 绑定。仅凭 cpu_op/category、external id、相邻节点或相近时间不能补造此绑定。

典型例按已读原因类别中的最小 relation ID 机械选取，完整 qualified work/scope/host/path 保存在 `AUDIT.json`：`work_relation:000762a2ed16306daa6e1d73509526cecd9fe2bc420d984061de19270986ec94`。其 ETO host 后缀 `eto:21812`，原 nodes ordinal 18123，pid 369749 / logical tid 1，external id 18128，原 raw SHA locator 指向 `#/nodes/18123`；runtime 后缀 `kineto:385811`，pid/tid 369749/369749，external id 18128，correlation 1229，raw locator 指向 `#/traceEvents/385811`。这些值用于解释既有边，未据裸 correlation 或 tid 相等推新边。`scar/trace/native_import.py:417–460` 已区分唯一 runtime correlation 与 CUSTOM0 CPU External id，原边自身带 provider 推断前提，既非 Python direct call 也非 happens-before。

SQLite 是原输出的可删派生索引：nodes=461,242、selected edges=78,171、native=39,796、source=79,592。旧 RETENTION 明确其 SHA 为 `NOT_REMEASURED`；本次一次读取后新测 SHA `9d2ab538685645abc61ab2805adc6677ced91f377bfe7c88fd640889171fc421`，再对相同 bytes 的只读内存副本做 SQL。新测量不能倒授旧 index 历史完整性，也没有重新核原 EEG。新旧 source scope 不互换：此处是原 C02 current source858/runtime858 接线。

完整计划输入为 work stored 46,250,001 B + decoded 911,134,322 B + SQLite 697,589,760 B，主体 1,654,974,083 B。实际计费主体 1,334,213,422 B，另有 81,017 B 四源核读及 1,455 B 旧 preparation receipt；RSS 1,400,920 KiB。源码定向审阅及本目录小报告读取另列，未解 EO/raw、大 native model 或静态 body 图。中断未到最终原输入 stat guard，资格保持 OPEN。

还缺的实证是：剩余 8,174 个 work 的声明审计，以及原 provider ETO host 到某个准确 canonical occurrence/其 source invocation 的绑定证据。当前派生 schema 没有原 ETO node 的 name、RF ID、完整输入/输出及未选边；因此不能从这些 SQL 列进一步判断 host 是否是某个未捕获 dispatch 或由谁调用。最小后继应先完成尚未审计的声明分布，再按真实 host ID 查明确的原录制/投影资格；不新增 backend、不重产全 native，也不把 provider scope 升级为调用关系。本次没有自动启动后继读取。
