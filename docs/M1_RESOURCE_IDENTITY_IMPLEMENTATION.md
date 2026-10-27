# R1：执行发生、资源实例及原程序端口

本门落实 [R0 合同](M1_RESOURCE_EXECUTION_CONTRACT.md)中身份与对应部分。
范围是规范声明的机器表示、连接和校验；不是新采集器，不代表已从 LeWM
自动恢复这些记录。work、完成、event generation 和消费者 ready 留在 R2。

## 1. 事实存在哪里

| 部分 | 唯一事实及职责 | 不表示什么 |
| --- | --- | --- |
| `ir/program` | Operation、原 producer、ordered Use、StateAccess、Region/CFG、静态资源定义/要求/使用。 | 一次动态执行、实际内存内容。 |
| `ir/execution` | run/process/thread incarnation、activation、segment、block visit、operation/value/Use occurrence；资源实例、handle lifetime、静态到动态对应。 | 另一套可写 producer/use、源码或 native 已验证。 |
| v2 ValueGraph | 已有 ObjectID、StorageAllocationID、region/materialization/逻辑值。 | 用地址判断同一 lifetime，或自动证明内容相等。 |
| v2 EvidenceGraph | 已有独立 definition 空间的观测发生和测量。 | 将其 OperationInstanceID 改前缀就等于 core occurrence。 |

ExecutionModel 引用规范 ProgramGraph 的**确切序列化字节**：现 program codec
的 UTF-8 输出，不补换行，附 schema/version/SHA256/长度。URI 只作来源标识，
构造和查询都不打开它。外部 ValueGraph/EvidenceGraph 以各自 canonical JSON
字节、schema、长度及 SHA256 定位；调用者按 digest 显式提供 catalogue。
未提供的工件是具体 gap，提供但不匹配的工件是矛盾。不存在隐式文件读取。

## 2. 执行坐标及数据身份

1. Run、ProcessInstance 和 HostThreadInstance 不以 raw pid/tid 作为 lifetime。
2. RegionActivation 是一次 body activation；挂起恢复保持 activation，换
   ExecutionSegment，允许在同一 process 的另一个实际 thread 恢复。
3. 一个 BlockVisit 是对静态 block 的一次遍历；静态循环再次进入使用新 visit。
   同一个 visit 中同一 Operation 最多有一个 occurrence。
4. ValueOccurrence 回指原静态定义和这次 producer occurrence、block formal
   visit 或 activation literal。它不是内容身份、ObjectID 或 LogicalVersion。
5. UseOccurrence 的 key 是 `(operation occurrence, 原 UseID)`；原 Use 仍唯一
   决定它使用哪个静态 Value。不能另存一个自由填的静态 producer。
6. ControlTransfer 指原 terminator 的**实际 successor index**和目标 visit。
   有限执行中的循环必须展开为新 visits，不能在发生图里重用旧 occurrence。

验证器按实际记录的 host CFG 推导当前动态定义：每次新 block visit 杀掉该块的
旧 formal/result，再建立本次定义。旧循环 result、旧 formal、其他 activation 的
值不能代替当前值。缺失的操作/Use/result/入口保留 gap，不编造已执行的事实。
target formal 仍是独立定义；查询给出原 predecessor argument、Use 或 typed
completion/resume port，不由此宣布复制前后内容、对象或逻辑版本相同。

状态支持只引用原 StateVersionValue 的 occurrence。当前 state 从原 formal、
StateAccess 和实际边派生，没有第二份可写状态 payload。INVOKE/BODY_DRIVE
没有普通结果和普通 common AFTER state；实际 completion landing 才有对应
formal 状态。返回失败不会被解释为无写入。挂起恢复的 state 使用新 ingress
formal，不沿用挂起前 world。这里的 host 路径先后不推导 GPU happens-before。

## 3. 资源及 handle

- ResourceInstance 表示 lifetime，不另加同义 generation counter；ProcessTarget、
  ThreadTarget、AllocationTarget 复用既有身份，不平行创造“同一分配”的实例。
- ResourceRealization 连接原 ResourceDefinition 的真实声明位置和动态 target；
  requirement binding 连接原 operation/region owner。入口绑定不意味着后续访问
  永久拥有相同权利、capacity 或存活状态。
- ObjectHandle 用既有 ObjectID；NativeHandle 用 Data/Protocol operand、namespace
  和 NativeHandleLifetimeID；缺失 denotation 使用有原因的 UnresolvedHandle。
  不因 fd 是整数就制造 Python ObjectID，也不因 Data occurrence 不同就认定数值
  fd 不同。同一 OFD 可有多个不同 handle lifetime；另一次 open 可有不同 OFD。
- ExplicitHandle、ImplicitBinding 和 Unresolved 是不同 variant。静态指定 handle
  的使用不能借 implicit selection 绕过对应检查。
- 每次 ResourceAccessBinding 回查原 ResourceUse、owner、target、当前状态支持，
  并可记录原 capacity/relation/protocol constraint 的证据。rights、ownership、
  sharing 和 release authority 分开；缺失证据不推导成立。
- AllocationPlacement 将已有 allocation 放入独立 MEMORY_POOL，不把 pool 当
  allocation，也不把文件 endpoint 强迫表示成 DRAM allocation。

## 4. 公开接口

```python
from scar.ir.execution.codec import dumps, loads
from scar.ir.execution.validation import validate, require_valid
from scar.ir.execution.query import ExecutionIndex

report = validate(execution, program, value_graphs=by_sha256)
# report.valid：声明的结构及已提供外键没有矛盾。
# report.gaps：缺失的发生、对应、状态、工件和 runtime 证据逐项列出。
# report.source_runtime_verified / transformation_authorized 始终为 False。
index = ExecutionIndex(execution, program, value_graphs=by_sha256)
link = index.definition_for_use(operation_occurrence_id, original_use_id)
route = index.formal_route(formal_value_occurrence_id)
states = index.state_at(point)
```

JSON schema `scar.execution-model` v1 独立于原 program/v2 wire。封闭类型集合的
record/ID/enum 有准确 tag，Union 不按相似字段猜类型；缺项、多项、重复 JSON key、
错误 ID namespace/wire、非有限数值、嵌套篡改均拒绝。codec 检查 record，跨图
关系由 validator 检查。查询结果脱离内部记录；查询不添加证明权限。

## 5. 自主验收及后续顺序

R1 必须依次有记录构造、真实规范图组合、原端口查询、wire 反例、独立复审、
组件门及冻结全仓证据。首次失败与修改保留，最终数据写入独立验收报告；
本实现说明不预填“通过”或测试数量。

重点反例：同 Create 多 activation、同定义多 loop visit、dup 与 open、
handle end/rebind、错误 owner/target/run/process、显式/隐式选择错接、旧 state、
旧 allocation、错误工件、resume 跨 segment、normal/raise completion。

本门完成后继续 R2 work/ready，再做 R3 load→consume→save 组合；完整 literal、
selector/alias owner、occurrence→denotation/provenance、M2 协议守恒仍有缺口。
M0–M2 全部完成后，按用户要求先停下来汇报模型，再进入自动建图与化简。
本门不产生 LeWM TRANSFORM，不产生新的 A/B 加速比。

最终 [R1 自主验收报告](M1_RESOURCE_IDENTITY_ACCEPTANCE.md)记录实际失败与修正、
302 项组件门和 4,192 项 clean 冻结全仓；原 4,050 测试身份及全部历史 fixture 保留。
