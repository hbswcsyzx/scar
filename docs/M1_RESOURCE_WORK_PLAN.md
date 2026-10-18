# R2 实施顺序：工作、顺序与消费者可用性

基线：R1 已验收并推送 `3ceb24d`；[R0 合同](M1_RESOURCE_EXECUTION_CONTRACT.md)
保持不变。目标仍是整个程序模型，不把工作返回、资源完成、可读及可释放混合。
本批不增加 detector/backend/lowerer，不跑新的重型 LeWM profiling。

## 1. 依赖顺序及自主验收

| 子项 | 必须落实的连接 | 验收节点 |
| --- | --- | --- |
| R2.1 工作及保留 | 一次 ticket→原提交发生；普通 StateAccess / INVOKE 实际 completion→formal；terminal observation、quiescence、work-holder retention。精确 queue prefix 是 queued 提交的身份基础。 | host RAISE 已提交工作仍保留；不同 ticket；错误真实 successor/result/state；部分失败不抹写；cancel 不蕴含 quiescence；原 allocation/handle、借用释放与缺失 coverage。独立复审、严格 wire/原端口查询、组件及一次 clean 冻结全仓。 |
| R2.2 event 与 order | event 实例与 record 代次；persistent queue-prefix 链、实际 wait 和精确消费工作。 | record 可在 pending 时发生；旧 record 不随重录更新；同队列/跨队列有序消费无须 host COMPLETED；错误队列、run、generation 和循环依赖拒绝。 |
| R2.3 consumer 与 ready | 原 Use/Access 或真实 Q observation root→logical version、物化、allocation/endpoint、selector；生产贡献覆盖与每贡献替代支持。 | AND(每必要贡献的 OR(Completed/Ordered))，允许混合；不能删 writer 缩小义务；旧内容/分配/域不匹配；失败/取消的实际部分 produced coverage 只能支持对应部分。 |
| R2 整门及 R3 | 上述接口组合，继而通用 load→consume→save / flush / close。 | 原 producer/Use/state 唯一，历史 wire/测试保留；缺失、矛盾、条件满足与 native/runtime/transform 授权分离。完整 R2 条件齐全后才宣称 R2 通过。 |

这是按外键依赖实施完整 R2；R2.1 通过不等于 typed ready 已实现。
各子项保留首次失败与修正，自己验收，不等待用户逐门审批。

## 2. R2.1 冻结的机器接口

复用 R1 ExecutionModel/ProgramSnapshot、occurrence、UseRef/AccessRef、资源 target、
ValueGraph allocation 和 Materialization。新增 work 类型不重建 SSA、不将旧 EEG
producer 改名成 core occurrence。新增 opaque IDs：WorkTicketID、WorkOutcomeID、
WorkQuiescenceID、WorkRetentionID、QueuePrefixID。

- `MaterializationRef(artifact, materialization)`：确切 ValueGraph 工件及原 ID。
- `WithinOperation(operation, source)` / `ExternalWorkSource(point, source)`：
  内部提交归属不强制放到 call BEFORE/AFTER；外部工作不捏造 core operation。
- `ActualCompletionState(successor_index, result_index, formal)` 与
  `InvokeBoundaryStateEffect(invocation, state_input: UseRef, post: actual | Unresolved)`：
  input 必须为原 INVOKE invoke_arguments 的 state Use；actual post 必须沿本次
  transfer，选中原 CompletionResult，并到达该 landing 的准确 State formal，
  location 必须一致。普通效果仍为原 `AccessRef`，不复制 mode/footprint/payload。
- `QueueStart(source)` 与 `QueuePrefix(id, queue, previous, work, observed_at,
  protocol, source)`：previous 为确切 prefix / 明确 start / Unresolved；work 为
  精确 ticket，空 prefix 只允许 start。链接持久化，不为每次提交复制完整历史，
  不按表行顺序、ID 数字或时间戳推设备顺序。queue 为实例，角色必须是 QUEUE。
- `Queued(queue_access, prefix)` / `DirectExecution(thread | Unresolved, source)` /
  `Unresolved`：queued 必须有准确 ResourceAccessBinding 与该 ticket 的 prefix；
  direct 不造 stream，未知 queue 不冒充 direct。executor 为准确 access 或 Unresolved。
- `WorkSubmission(id, origin, executor, scheduling, dependencies,
  dependencies_coverage, effects, effects_coverage, materializations,
  materializations_coverage, retention, protocol, source)`：retention 为准确
  WorkRetentionID tuple 或带原因的 Unresolved；coverage 是声明范围，不是证明。
- `WorkQuiescence(id, ticket, observed_at, source)`：单独的停止访问依据，不由 host
  返回、terminal kind 或 output ready 推出。
- `ResourceOutcome(id, ticket, kind, observed_at, protocol_result,
  effect_frontier, frontier_coverage, quiescence, source)`：kind 为
  COMPLETED / FAILED / CANCELLED；结果可为原 ValueOccurrence / 原协议 fact /
  Unresolved。frontier 引用原效果，不承诺整个输出区域已产生；实际 produced
  coverage 在 R2.3 接入。多条 observation 保留，已知矛盾终结种类不可覆盖。
- `WorkRetention(id, ticket, target, basis, start, support, authority, sharing,
  release, source)`：这个关系明确 ticket 为 holder；不将 work 伪装成资源实例。
  target 为原 ResourceTarget、精确 HandleTarget 或 MaterializationRef；basis
  回查原 Use/Access/resource access/materialization 或明确 Unresolved。
  start 为 WithinOperation 或原 ExecutionPoint；release 为
  `BorrowRelease(point, quiescence: WorkQuiescenceID | Unresolved, source)` 或
  Unresolved。支持引用当前 StateVersion occurrence，无第二份状态。

**校验边界：** FK、kind/role、scope、实际 completion、原效果与声明范围可以
机械检查；protocol fact 的存在不表示协议适用或物理覆盖已验证。缺少实际对应的
区域保留具体 gap，不能以 empty effects/retention 宣称 pure、ready 或可 free。
在另一个嵌套 activation 的效果与父提交之间，没有真实调用 pairing 时保留 gap，
不能仅按静态 Region 祖先或标签猜一次动态父子关系。

## 3. wire 与后续闭合义务

静态 ProgramGraph 仍 v14。Execution wire 新增工作能力时显式版本化为 v2；
原 v1 从 immutable 已提交实现生成 golden，原 IDs、字段和值保持，不凭缺省
字段把旧 wire 升成包含工作证据的新 wire。新工作非空不能输出 v1。

R2.3 的 required contributions 必须由物化/selector 的生产覆盖与原 writer/effect
关联派生，Evidence 不能自填较小集合。来源 manifest 未闭合或完整性仅是未经核对
的声明时，查询保留条件和 gap，不授实际 ready。consumer denotation、当前状态、
visibility domain 和 allocation lifetime 必须逐项对应。storage geometry 复用已有
实现，并守住 empty/zero-stride/non-strided/超预算边界；包围盒不能填平 strided 孔洞。

失败/取消可保留实际部分 produced frontier；支持只能覆盖相应部分。旧 ready 证据
是历史事实，新的 content/allocation/consumer 不匹配不意味着删除旧记录。
本门没有一个全局线性 READY 等级，也不返回无条件 `ready=True`。

第一阶段剩余 literal、selector/owner/alias、denotation/provenance、协议家族和 M2
仍按总计划关闭。M0–M2 全部完成后，先按用户要求汇报模型，再进入自动建图。
