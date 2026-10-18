# R2.2：执行顺序接口

实现位置：`scar/ir/execution/order.py`、`order_validation.py`、`query.py`。
按 [实施计划](M1_RESOURCE_ORDER_PLAN.md) 在原 ExecutionModel 追加三张关系表；
静态 ProgramGraph 仍 v14，原操作、Use、producer 和 StateAccess 保持唯一。

## 1. 规范记录

| 记录/表 | 字段 | 含义 |
| --- | --- | --- |
| QueueOrderProfile / queue_order_profiles | id、queue、through、protocol、source | FIFO 声明只适用确切队列实例及 through 的已知祖先链。不是全局队列保证。 |
| RecordedPrefix | queue、prefix（QueuePrefixID / QueueStart / Unresolved） | record 捕获的提交前沿；不是 event 当前最后一代。 |
| EventRecord / event_records | id、event、event_access、marker、captured、generation、observed_at、protocol、source | 一次 record；事件生命周期与本次代次分开。access/marker/generation 缺失可以明确表示。 |
| QueueWait / queue_waits | id、ticket、record、event_access、selection、observed_at、protocol、source | 本次真实关联的 queued wait，选择准确 record；后续重录不更新它。 |

generation 为原 AccessRef 或 InvokeBoundaryStateEffect。普通 record 必须写出
post-state；INVOKE 必须保留 R2.1 的实际 successor/result/landing formal。
event_access 引用原 ResourceAccessBinding，其原 ResourceUse 和 generation 的
ResourceLocation 必须对应。requirement-only Use 可以经本 activation 的确切
ResourceRealization 关联；缺失对应是 gap，不从名字或地址猜实例。

selection 为原 UseRef。普通 wait 必须有匹配的原 READ/READ_WRITE StateAccess；
INVOKE 不造普通 StateAccess，改引用 work 中已校验的 exact boundary effect。
仅传入 state 参数不能证明 read。实际状态经 CFG 传递只沿真实 predecessor Use
追溯，CompletionResult、ResumeInput 或未知写不被任意当成原状态。
已知另一 record 的状态与所选代次冲突时拒绝；未知中间状态变化保留 gap。

event 使用原 ResourceInstance 和协议关联，不增加业务 event 节点或改静态资源
wire。具体协议可以是 CUDA 或别的队列协议；本层不按协议名字硬编码规则。
未展开 native 内部仍能保留 typed 边界，不等于已理解其全部操作。

## 2. 派生关系

查询端点是不同类型：WorkStart(ticket)、WorkEnd(ticket)、PrefixEnd(prefix)、
EventSignal(record)。不存在把 host enqueue AFTER 重命名为 GPU start 的接口。

1. work Start→End；声明 dependency 的 End→Start。
2. 成员 End→PrefixEnd；前项 PrefixEnd→后项 PrefixEnd。这只表示完成前沿。
3. profile 覆盖链中，前项 work End→后项 work Start。
4. 准确 capture PrefixEnd→marker End→本次 EventSignal。
5. 准确事件状态选择及 scope 对应后，EventSignal→wait work End。
6. 目的队列 profile 将 wait End 连至后续 consumer Start。

所有边保留规则及原行支持；联合检查循环，不能靠回路自证严格顺序。
没有协议适用或原对应时，不构造缺失的边。缺前缀头不伪装成空队列。
即使已追到包含 C 的 PrefixEnd，也不能倒推出在 C Start 之前成立。

## 3. 查询与格式

`ExecutionIndex.order_path(source, target, budget=4096)` 返回 detached 原支持、
条件路径、精确 gaps 和预算截断标记。`work_order(producer, consumer)` 固定查询
producer End→consumer Start。无路径是 UNRESOLVED，不证明两个工作无关。
存在路径是 CONDITIONAL；source/runtime/order verified 与 transformation
authority 始终 False。不返回 ready/free，不证明成功产值或 host 可读。

execution v3 引入这三表；v1/v2 的字段、tag vocabulary 和原字节不变。
默认按非空能力选择 v1/v2/v3，显式降级不得丢工作或顺序记录。空表只代表未带
这类关联，不是“没有其他工作/等待”的完备性证明。

R2.3 将在这个条件顺序上另行接消费者 denotation、required contributions、
实际 produced coverage、内容版本/分配/域与错误传播；不会把 CONDITIONAL
改名为无条件 ready。native 事实适用与后续自动恢复需独立证据。
