# R3.2：完整观察需求与执行依赖组合

基线：`f0dbbd478095b07a684fe4d35ba3b53be20ed17c`，干净工作树；上轮
[R3.1](M1_CALL_ACTIVATION_ACCEPTANCE.md)的 591 项组件和冻结 `881cbfb` 的
4,951 项全仓通过。上一轮是有效进展，不是完整 M0–M2 完成。

本门落实[原 R3 计划](M1_RESOURCE_COMPOSITION_PLAN.md)的全过程组合公开面；
不增加 detector、backend、lowerer、LeWM 规则或新 profiler。
本文件是执行计划，验收数据另写。

## 1. 事实归属与审查决定

核心仍是 Operation、Value、StateLocation、Region、Resource。组合是原图的派生
投影，不再保存一套 producer、Use、state 或通用 lifecycle 图。

### Q 适用范围先于已连接路径

`ObservationRequirement` 只验证已经存在的行，不能反向发现整行需求被删。
`SemanticGraph` catalog 也可能含不适用于当前执行的合同，不能全部自动激活。
增加 query-only `CompositionScope(contract: ContractRef, owner: RunID |
RegionActivationID | OperationOccurrenceID, source: FactSource)`，作为分析请求的 Q
边界，回显在报告中；不冒充运行事实，不增加 ExecutionModel/wire 表。

每个显式 scope 从原合同的 required_outputs 和 required facets 建立期望账本，
再与原 requirement/root/read 对账。Run、activation、operation 各自具有准确粒度，
不能把两次调用压成一个 run 级义务。缺少 owner/实例对应时保留准确未决。
不接受 roots、writers 或“相关操作”的筛选列表来缩小完整性分母。

facets 只声明类别和 required，不定义端点目标或基数。必须保留尚未解释的 facet
义务；现有 RequiredEndpoint 行不是全体目标的穷举证明。没有 scope 时保留原需求
和可见关联，但 scope 未恢复，不能以空集合宣布成功。

### 依赖的类型不能混同

- 原 UseOccurrence 是有序的数据/引用/状态/协议输入端口，不把相同值的 Use 合并。
- 原 producer、实际 CFG transfer、CompletionResult/BodyDriveResult/ResumeInput/
  PendingPayload/SavedInput 与 R3.1 call routes 各自保留来源。没有 source_use
  不等于没有依赖，跨调用声明路由不证明值或对象身份。
- provenance 祖先是逻辑前提，不自动成为当前 Mat 的生产贡献；物理贡献和支持仍
  由原 P/V 查询派生，不能接受调用方指定的完整 writer 集。
- 原 operation/effect/escape 与资源、顺序、生命周期都列在完整账本；未达某个
  root 的操作仍保留，不能据此宣布 dead、pure 或可删除。
- OutputValue 没有 ContentRead 不自动意味着发生了物理读取，也不证明不需要读取。
  保留其原 value/端口依赖和未解释的观察协议；不能为 scalar/ref 造 ticket/Mat。

### 一份新证据快照与一个总派生预算

现 `_content_context` 只刷新 D/Q/P/V，不足以对整个组合信任资源/work/order 的旧
派生。复用原 canonical flow，抽取既有 validation 的外部关联阶段，使用一次新
ExternalSnapshots，重查完整 source/resource/work/order/evidence/Q/D/P/V。
每 read 不重复 replay/copy，也不重置总预算；只在公开顶层 detach 一次。
准备、记录/FK 校验、受限工件重放和 copying 成本单列，不声称总 CPU 受 4096 限制。
预算耗尽时保留原全量身份/计数及未检查项，不将截断当成独立或安全。

## 2. 自主验收节点

| 节点 | 交付 | 必须验证 |
| --- | --- | --- |
| P0 连接审查 | Q 分母、原端口路径、证据/生命周期三项独立源审及公开 API。 | 原图归属不重复；真实缺口与已有能力分开；不把新增表当默认答案。 |
| P1 请求与 Q 账本 | typed query scope；逐 scope 的原输出/facet 义务与全部现需求/root/read。 | 删整个 requirement/root/read 仍不空成功；错 run/owner、重复调用、缺外部图；端点基数未定义不伪造。 |
| P2 依赖与证据组合 | 原 value/Use/state/CFG/call 路径，独立来源 P/V，work/order/lifetime 及完整 inventory。 | partial/RAISE/pending、前后覆盖、unknown effects/escape、cleanup/close/borrow release 分开；无 consumer 不授删除。 |
| P3 新快照与预算 | 一次完整刷新，单总预算、只在顶层 detach；所有未检查项及准备成本明确。 | mutable catalog 突变不借旧关联绕过；跨 read 不重置预算；缺 join 不缩分母；历史单 read API 保留。 |
| P4 联合验收 | 通用正反模型与独立复审，准确 source/native/endpoint 缺口。 | 不是手工业务路径冒充自动建图；逐端口/逐需求可回查，原失败与推导保留。 |
| P5 冻结归档 | 组件验收、干净实现提交、一次冻结全仓、守恒报告及推送。 | 原 4,951 case ID、68 fixtures、555 source 全保留；full 期间不改源码/文档或另启测试；仅清理 owned temp。 |

各模块冻结后统一组件，不为每个小编辑跑全仓。必要的原失败原样保留，独立审查
发现的风险与实际运行失败分开记录。R3.3 的通用 load→materialize→compute→consume→
write→flush/close 完整模型和有界 OS 见证仍在原分母；如果本门组合能一并验证则
按完整证据报告，不能因一个单 region 正例就提前关闭跨调用/异常路径。

## 3. 停止点与剩余阶段

本门不测 LeWM 加速比，不以测试耗时充当 benchmark。自动 source/runtime/native
恢复和 endpoint read/flush/persist 解释分别记录。R3 之后仍有 selector/literal、
C2/D3 等接口及 M2 全构造分母；完整 M0–M2 经逐项验收后，按用户要求停下讲解。
当前不宣称整个程序建模完成，也不提前启动新的优化变换。
