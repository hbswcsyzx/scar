# R3.2：原图、观察义务与执行证据的组合接口

[计划](M1_PIPELINE_COMPOSITION_PLAN.md)。本接口组合已经提供的模型，不自动恢复
全部源码或本机事件，不授权化简。没有新增图节点类型、detector、backend 或执行
wire 版本。核心类型仍是 Operation、Value、StateLocation、Region、Resource；
合同与测量是约束和证据，不能代替原操作、输入端口或状态链。

## 1. 分母是什么

```python
from scar.ir.execution import CompositionScope, ExecutionIndex

index = ExecutionIndex(model, program, semantic_graphs=contracts,
                       value_graphs=values, evidence_graphs=evidence,
                       artifact_bytes=artifacts)
report = index.resource_composition(scopes=(
    CompositionScope(contract_ref, activation_id, fact_source),
), budget=4096)
```

`CompositionScope` 是分析请求，准确指定一个 ContractRef 与一个 RunID、
RegionActivationID 或 OperationOccurrenceID。它不是新增运行事实，也不包含
“相关节点”、root 或 writer 的筛选清单。相同合同适用于两个调用时，使用两个不同
owner 的 scope。不能从 catalog 的存在推断合同适用于所有执行。

作用范围的自动恢复仍待适配器实现；这个接口不能把调用方给定的范围变成已证明的
全程序需求。`scope_inventory_complete` 始终 False。没有 scopes 时依然返回全量
模型及原需求，但 Q 范围为 UNRESOLVED，不是空集合成功。

非法预算、非准确 tuple、错误 scope 类型、重复 scope 或本地 owner FK 在打开外部
工件前拒绝。预算为正的准确 int；bool 不接受。scope 的合同身份使用准确
SHA/schema/size/ContractID，URI 只是定位符。未知合同 ID 报 KeyError；缺合同工件
保留未决与 gap；修改了工件内容却继续使用旧 hash 时拒绝。

## 2. 返回内容与含义

| 字段 | 保留/派生的内容 | 不能说明什么 |
| --- | --- | --- |
| requested_scopes | 原请求，准确 owner 粒度。 | 自动恢复了全部 Q。 |
| inventory | 全部原 ProgramGraph、ExecutionModel，各表准确计数；即使截断也保留。 | 全部源码/native/runtime 已捕获。 |
| observations | 全量原 requirement/root/read；从合同 required_outputs 与 required facets 生成的期望账本。 | 只有已连接路径才算分母。 |
| reads | 全部原 ContentRead 的逐项 V/P 查询；未完成项有 pending/cursor。 | 所有值都有物理读取，或任意 ready=True。 |
| production | 原 writes、outcome productions、establishments 的准确关联。 | provenance 祖先都是当前 Mat 的贡献者，或 writer 集完整。 |
| sources | 原 manifest/projection、准确工件引用和记录计数；独立于 ContentRead 的原 EEG edge 账本。 | 捕获了所有 native writer/alias/外部效果。 |
| routes | 原 operation/有序 Use/result/state access、actual CFG transfer、typed completion/resume/drive、动态 call 关联。 | 路由证明跨调用内容身份、纯度或可复用。 |
| lifecycle | 原 submission/outcome/quiescence/retention、actual host successor、handle 与 target lifetime。 | 返回/RAISE/terminal/quiet/borrow release/close/retire 相互等价。 |
| external_preparation | 一份新外部快照、复用 canonical flow、原 11 阶段刷新范围。 | 所有准备和 replay 都计入派生预算。 |
| gaps | 原验证缺口、Q/route/budget 缺口；逐 read 的细化条件仍在其 validity 中。 | 无 gap 即得到变换许可。 |

`status=DERIVED` 仅表示预算内派生未被截断；不是 CLOSED/PROVEN。
`source_runtime_verified`、`runtime_visibility_verified` 与
`transformation_authorized` 均为 False。未达 root 的原操作仍完整保留；不能据此
判定 dead、无 escape、无异常或无外部效果。

## 3. Q 账本不能靠删行通过

每个准确合同的 required_outputs 先形成期望输出槽，再查找原 requirement 和
scope 相容的 root。因此删除整个 requirement/root 不会消除期望义务。
准确 run 不符可以排除；同 run 下没有 owner 对应证据，保留 ROOT_SCOPE_UNRESOLVED，
不能把另一次 activation 的 root 当成本次调用的输出。

合同 required facets 没有端点目标和基数定义，统一保留
FACET_TARGETS_UNINTERPRETED。已有 RequiredEndpoint 行只提供候选，不能证明全体
目标已枚举。输出槽存在 root 也只是 ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED，不证明
其绑定和 runtime 对应；scope_complete_for_request 仅指这份请求的结构账本。

root 没有 ContentRead 时报告
NO_CONTENT_READ_DECLARED_PROTOCOL_UNCLASSIFIED。标量和引用返回可以没有 Mat/read；
不得为它们虚构 ticket、Mat 或物理读取，也不能把缺 read 推断成没有内容依赖。

## 4. 原图如何连接

组合不另造 producer、状态版本或任意 lifecycle 边。UseOccurrence 按原顺序保留，
`f(x, x)` 有两个 Use。值指向原 producer，状态 access 保留原 before/after；CFG
只沿已记录的 actual successor，不能默认 NORMAL。CompletionResult、BodyDriveResult、
ResumeInput、PendingPayload 和 SavedInput 保留各自类型；无法直接找到 source_use
时保留原 marker，而不是当成无依赖。

R3.1 CallActivation 连接原 caller 与准确 child activation，再派生输入与返回端口。
同静态函数的多次调用不会合并。缺 entry/completion/动态关联仍保留缺口；声明关联
不是 runtime 对应证明。物理 contribution、actual prefix、支持与可见性继续使用
原 P/V 内核，Completed 与 Ordered、known 与 conditional 分开。

## 5. 预算、复制与证据时效

一次公开查询刷新 source/resource/work/order/evidence/Q/D/P/V 的全部外部关联，
不修改构造时 ctx/report。canonical 与 call 的已校验基础复用，外部 mutable catalog
使用新的 ExternalSnapshots 核验。每个不同的 manifest/index 工件对在本次准备中
重放一次，不随 read 数量重复；多个不同来源仍各自重放。

Q 扫描/joins → 所有 read 的 V/P → production → source 摘要 → routes → work views
共享一个 ValidityBudget。私有 P/V 不调用公开接口、不重置预算、不逐 read detach；
最外层统一 deepcopy 一次。原公共 production/validity 保留签名、默认 4096 与布局。
observations.budget 是 Q 阶段结束时的普通字典快照，顶层 budget 是整个查询的总账；
前者不再随后续阶段变化，控制器本身不会作为公共结果返回。
原始 inventory、准备/FK 校验、受限 artifact replay 和末次复制成本单列，不能宣称
整个查询 CPU 都受 4096 限制；原图也可能很大。

每节准确保留未检查计数与 cursor。reads.pending 包括已经看到 ID 但 V 尚未完成
的记录；sources.pending 与 lifecycle.pending_work 只数未访问的父行，行内还有
pending_sources、evidence.pending_edges 或各 relation 的 pending，不能只看父计数判断完整。routes 中
scan_complete 也只表示原端口扫描完成。预算耗尽保留 TRUNCATED 与准确原 inventory，
不能把剩余部分当成独立、无消费者或可删除。

## 6. 下一步的接口边界

R3.3 仍需通用 load→materialize→submit→consume→write→flush/close 的完整模型与
有界 OS 见证；source/runtime/native 恢复、端点协议、selector/literal、C2/D3、
全构造分母仍按原计划推进。当前组合为这些任务提供原图回查，不以手写测试图
冒充自动拆解 LeWM，也不产生新的 LeWM benchmark 或加速比。
