# R2.1：work、终结与资源保留接口

完整 R2 的依赖顺序和验收条件见 [实施计划](M1_RESOURCE_WORK_PLAN.md)。
这里是已落实的工作基础，不把它重新命名成完整 ready 或整个程序模型。

## 1. 程序图和执行关系

```text
原 Operation / Use / StateAccess / CFG
    ↕ 精确原端口
WorkSubmission ── WorkTicketID
    ├── WithinOperation 或 ExternalWorkSource
    ├── executor access / Direct 或 Queued + persistent prefix
    ├── 原 access / INVOKE actual completion 状态效果
    ├── 原 ValueGraph MaterializationRef
    ├── 多条 ResourceOutcome observation
    ├── 独立 WorkQuiescence
    └── WorkRetention → 原 allocation / handle / materialization / resource
```

work 是真实资源工作的身份，不是另一个静态 Operation，也不是一条 host 返回。
一个调用可提交多个 work；一个失败的 host INVOKE 也可以留下尚未完成的工作。
表中记录顺序、ID 数字和 timestamp 不推导 CPU/GPU 因果顺序。

## 2. 原效果端口与实际完成

- 普通效果只有 `AccessRef(operation occurrence, StateAccess index)`；mode、
  before Use、after Value、location 和 footprint 仍从原图派生。
- INVOKE 没有普通 access/results，也没有通用 AFTER state。边界效果引用原
  invoke_arguments 中准确的 state Use，以及本次 transfer 选择的 successor。
  ActualCompletionState 的 result index 必须在原边上确为 CompletionResult，
  formal 必须属于实际 landing visit，且 location 与输入一致。
- 未采到 completion 时保存 UnresolvedPost；正常边和异常边不互相替换。
  该边界关联不表示已证明 read/write/物理工作范围；未知精确对齐保持具体 gap。
- ResourceOutcome.effect_frontier 引用原效果，可保留失败/取消时的部分写入。
  frontier 的存在不是整个 Tensor 或请求区域已经产生的证据。

多条终结 observation 独立保存；相互矛盾的已知 terminal kinds 形成诊断，不能
覆盖旧行。观察点已知早于包含提交的 host operation 时拒绝；跨 activation/native
先后未对应时给具体 order gap。结果在其他函数观察可以合法表示，不强制同函数。

## 3. 队列边界与保留

QueuePrefix 用 queue lifetime、previous boundary、当前 work 和来源表达持久链。
它不复制每次提交的完整历史；Queued 同时核对具体 queue ResourceAccessBinding、
实例及准确 ticket。空 start prefix 即使没有 ticket，也须检查已知 queue realm。
本门不据这些声明授设备 ordering、event completion 或 consumer visibility。

WorkRetention 明确 ticket 为 holder，复用原 target。HandleTarget 不造新 handle
lifetime，MaterializationRef 不改旧 producer，AllocationTarget 不造平行资源实例。
direct ResourceAccess basis 必须指向 held referent，Reference handle 与 native
scalar handle 的 direct Use 类型不能混用。同类不同 ValueOccurrence 仍可能 alias，
没有 denotation 时保留 gap，不仅因 ID 不同就否定同一对象。

WithinOperation 只说明内部起点属于哪个操作，不捏造 BEFORE/AFTER 时间。
原 entry/actual-post frontier 用于排除明确旧状态；内部究竟哪个状态有效仍保留
current-point 义务。借用释放与独立 quiescence 关联；FAILED、CANCELLED、COMPLETED、
局部变量消失、host return 都不自动释放借用，也不授权 free。

## 4. API 与 wire

```python
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.codec import dumps, loads
from scar.ir.execution.validation import validate

report = validate(model, program, value_graphs=by_digest)
index = ExecutionIndex(model, program, value_graphs=by_digest)
work = index.work(ticket_id)                 # host outcome / observations / Q / retention 分开
effect = index.canonical_effect(effect_ref) # 原 access 或实际 completion 端口
chain = index.queue_prefix(prefix_id, budget=4096)
```

结果是脱离内部记录的副本，既不提供 `ready=True`，也不提供 free/transform 授权。
工作/效果查询预建 ticket 和 effect 索引；队列历史有预算，不逐次存 O(N²) 前缀。

ExecutionModel 新增 submissions/outcomes/quiescences/retentions/queue_prefixes 五表。
work 非空默认输出 `scar.execution-model` v2；五表为空默认保留原 v1 字节。
显式 v2 可写空五表，v2 缺表拒绝；v1 不接受新表/新能力，有 work 不能降成 v1。
原 program v14 与 v2 ValueGraph/EvidenceGraph 未改。历史 v1 golden 从 immutable
`6fcac0f` 独立生成，88,521 字节和 SHA 均核对，未用当前 codec 自生成预期。

## 5. 已验及仍待验

组件门 `gates/m1_resource_work.json` 最终 **407 cases / 9 criteria / 6.282s PASS**，
480 注册源码指纹不变。包括首批构造/组合/wire/query 和 R1/core 回归；首次失败、
具体修正与独立限定复审保留。clean 冻结全仓在本实现检查点尚待执行。

R2.2 的 event record generation/order-to-consumer-start、R2.3 的 denotation、
生产贡献覆盖和按消费者/版本/分配/域的可用性，以及 R3 组合都仍未完成。
物化与旧 EEG producer 的准确 scoped correspondence 也不因原 ID 存在就完成。
这些声明检查不是自动拆解 LeWM 或 GPU/native 实测；没有新增性能优化/加速比。
