# R3.1：动态调用关联与原端口回查

本接口落实[组合计划](M1_RESOURCE_COMPOSITION_PLAN.md)中的基础连接。
它不是新的程序图，也不代替原静态 callee、Use、结果、state 或实际控制转移。
验收结果另写；本文定义事实归属与公开范围。

## 1. 为什么需要关联

一个静态函数对应任意多次动态执行。即使两个调用输入值完全相同，也不能据此
确定它们各自进入了哪个 activation，或返回值来自哪一次执行。反过来，递归可以
再次调用同一个静态 Region，但每层必须有不同的 activation。

```text
caller OperationOccurrence
  ├─ 原 callee / call_arguments 或 invoke_arguments
  └─ CallActivation
       ├─ child RegionActivation
       ├─ initial entry BlockVisit 或 Unresolved
       └─ actual RETURN/RAISE occurrence 或 Unresolved
```

`CallActivation` 只存原身份与来源：

```python
CallActivation(
    id: CallActivationID,
    caller: OperationOccurrenceID,
    activation: RegionActivationID,
    entry: BlockVisitID | Unresolved,
    completion: OperationOccurrenceID | Unresolved,
    source: FactSource,
)
```

`ExecutionModel.call_activations` 默认为空。空表兼容历史记录，表示没有声明此关联，
不证明执行没有调用函数。`Unresolved` 表示缺采集/缺对应，不能解释为尚未返回、
无限循环、无效果、无结果或可删除。

## 2. 原端口派生

输入按原 caller `call_arguments`/`invoke_arguments` 与 callee entry arguments
的位置派生，保留每个原 Use；`f(x, x)` 的两个 Use 不能合并。动态绑定分别引用
caller 的 UseOccurrence 与 child 的 entry formal ValueOccurrence，不允许用 caller
的动态值直接替换 child 内部 UseOccurrence 的 origin。

输出从 actual child RETURN/RAISE 的 `terminator.values` 原 Use 派生：

- 普通 CALL 对应 caller 原 OperationResult 的准确位置。
- INVOKE 对应本次实际 taken successor 中相同 CompletionResult 位置；继续回查其
  target BlockVisit 的 landing formal。先按 `CompletionResult.index` 选 child 结果槽，
  再按该 argument 的位置选择 landing formal，二者不能混用。状态结果保持 StateVersionValue，不变成
  普通数据结果或虚构 StateAccess。
- 缺 completion、transfer、动态 Use/result/formal 时保留各自缺口与仍可回查的
  静态端口。不能默认选择 NORMAL，也不能套用另一条已发生路径的后态。

这些是显式声明下的端口路由。跨调用的数据版本、对象指代、alias 和物理内容对应
仍由各自原关系和证据核验，路由不授予逻辑身份、纯度或复用证明。

| 未观测的连接 | 查询保留什么 | 不能解释成什么 |
| --- | --- | --- |
| entry | 原 association 中的 Unresolved；静态 input Use/formal 定义仍在，动态 formal 为 None。 | 没有参数或没有进入函数。 |
| completion | view.completion 为 None、outputs 为空，原 caller/callee 静态接口仍可回查。 | 零结果、pending 或不终止。 |
| INVOKE 的 caller transfer | 已见 child 出口及原 Use；caller transfer/formal/edge argument 为 None。 | 默认 NORMAL 或另一条路径的后态。 |

## 3. 结构校验

| 检查 | 错误与未知的区别 |
| --- | --- |
| owner | caller 必须有原静态 callee；child.region 必须匹配。BodyDrive 用其专用入口；内部 callback/native span 不能冒充外围整次同步调用。有独立 canonical caller/callee 的同步 callback 可以按此接口声明。 |
| occurrence | caller 与 child 各只能属于一个该同步调用关联；动态关联不能成环，静态递归允许。 |
| execution scope | 同 process/run；核 caller 与 child 全部已捕获 segment 的 known thread。未知入口或线程不能豁免其它已知冲突，未知仍留缺口。 |
| entry | 原 child 的 InitialEntry 入口 visit；不能用循环回边、resume、capture 或其它 activation 的同名 block。 |
| completion | 实际 child 的 RETURN/RAISE 和原 exit；同一同步 activation 的多个已捕获终止是矛盾。普通 CALL 限其正常出口，INVOKE 核实际调用方 successor 的 completion kind。 |
| capture | 未见 entry/completion/transfer 或值端口保留原未知，不从证据父子 span、时间邻近或相同 denotation 猜关联。 |

返回与抛异常只描述语言完成。某次调用已经返回或 RAISE，不证明它提交的工作
已 terminal、quiescent、释放借用或可释放 allocation；原 WorkSubmission/Outcome/
Retention、handle end 与 TargetLifetimeEvent 分别保留。

## 4. 公开查询

```python
index.call_activation(call_activation_id)
index.call_entries(caller_operation_occurrence_id)
```

参数是准确的独立 typed ID，错误类型拒绝，未知 ID 报 KeyError。查询只使用已验证
的 canonical/execution 关系，返回 detached 原记录与派生输入、输出、缺口。
修改返回字典不会改变 index 或下一次查询。

`call_entries` 按这个 caller 的原关联查找；已声明 callee 而没有关联时保留
MISSING；没有原 callee 的操作报告 NO_DECLARED_CALLEE，不向其它同名 Region 搜索。
NO_DECLARED_CALLEE 只说明 core 没有显式目标，不证明操作无调用、纯或无外部效果；
MISSING 也不等于执行失败。
有记录时为 DECLARED，完整性由缺 entry/completion/端口等具体缺口表示。
`source_runtime_verified`、`value_identity_verified`、`transformation_authorized`
与 `runtime_identity_verified` 均为 False。已有 `formal_route` 继续只表达实际 CFG
transfer，不混入跨调用值。同静态 callee、scope 与类型都相容时，交换两个完整声明
对未必能由结构发现；真实对应必须由后续 runtime adapter 与原始证据验证。

## 5. 兼容和后续

执行 schema v7 只承载新增调用关联能力。v1–v6 的字段与 tag 词汇不变；自动选择
最低已使用能力，显式 v7 可有空表。旧版本不得静默丢弃非空新表。独立旧 v6
golden 从实施前不可变提交的 codec 生成，验证字节而不冒充有效物理执行。

下一步 R3.2 将这些原端口接入完整 Q requirement 分母下的 load/consume/save
组合；实际 source/runtime/native 恢复与 endpoint read/flush/persist 解释仍分别
列为缺口。本接口不宣称自动恢复整个 LeWM，也不产生新的 workload 加速比。
