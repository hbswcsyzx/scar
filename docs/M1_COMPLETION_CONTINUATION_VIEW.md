# Completion continuation 查询合同

2026-10-19；落实 [本轮计划](M1_AWAIT_POST_CLEANUP_PLAN.md)，不新增规范记录或图实体。
接口尚未实现/验证，不能据本合同授通过。

## 1. 静态与动态入口

```python
ProgramIndex.completion_continuations(
    source, *, start=None, choices=(), cross_resume=False, budget=4096)
ExecutionIndex.completion_continuations(
    source, anchor, *, cross_resume=False, budget=4096)
```

静态 source 为既有准确 source-port，当前只处理 Python Reference 或 whole
EXCEPTION_PACKET 完成载荷；state 等其他类型保明确不适用/缺口。start 是原
`(BlockID, operation_index)`，省略时由 source 原位置得到。跨 region 显式 start
不授来源可用性，copy 仍需原 caller/actual/formal/exit 关系支持。choices 为该
source/case/token recipe 的原约束，不是完整路径或按名称推断的条件。

动态 source 是准确 ValueOccurrenceID，anchor 是当前调用的准确
OperationOccurrenceID。它检查该 CALL 自己的 CallActivation/完成对应，沿本
activation 实际 ControlTransfer 续接。cross_resume=False 在原 Suspend 停止；
True 仍须本次实际 Suspend→ResumeIngress/transfer，缺采不搜索另一实例。
静态 True 模式只表达声明后继，绝不能赋予实际执行证据。

## 2. 共享已有计算，按需保 receipt

复用 packet continuation 的 token/possible-port/Replace/known-call 关系，
新增 Reference 起始角色和显式停止选项。原 packet_continuations 默认输出/
计费行为保留；只在新查询及 await 整链连接启用补充 receipt，按共享预算收费。
不另写同义图求解器。原 Source/Use/CFG/状态仍只有一个规范来源。

terminals 的每行保：

```text
terminal: HostTerminal        actual: OwnedUse
root_source                  current_source
role: packet | reference     choices: 原已知约束 tuple
binding: 当前 source 到 actual 的 copy
root_binding: 原 source 到 actual 的 copy
root_preserved: root_binding.match
crossed_suspend              context: 查询内原状态 key
status / gaps
```

checks/actions/projections/overrides 同样保本行 source/choices/context。
补充 transitions 只引用已有查询状态与原动作，保合流前的关系；它不复制 producer/
状态 SSA，也不枚举完整路径。公共 report 的空未知、预算 cursor 和全部原 source
keys 必须守恒。未查 receipt 不得被解释成 non-copy、dead work 或纯操作。

动态 terminal 另保准确 operation/use/value occurrence、root/current binding，
报告实际 segments 与 transfers。身份未声明可使 status=PARTIAL，即使结构
copy=True；已知 scoped ObjectID 冲突必须 False。所有 source/runtime/value/
transform authority flags 为 False。

## 3. 接入已有 await conversion

每个原 whole-packet candidate 给 conversion leg 增加：

```text
continuations[] = {packet: 原 _packets 项 dict, start, choices, continuation}
```

NORMAL 先核原 exception Reference 到 PacketDefinition.exception；RAISE 用自己
的 whole packet。终点按 receipt 的当前 role/来源和真实 RETURN/RAISE 接 parent
同 kind/full slot。保原包的 completion 才可能要求原最终提取；合法 Replace 后
不复用旧来源、不错误授该提取，也不将 root_binding=False 本身当程序矛盾。
wrong terminal 的当前 binding=False 与合法覆盖是不同事实。

**状态正确性不是状态不变性。** C1 的 whole-domain 写产生新版本，constructor
post→terminal 的 copy=False 可以是合法更新。structured continuation 的必要
收据放 `terminal.states`：当前 terminal State Use→准确 parent state result
slot，分别核每个 location。constructor 旧 post 的 lineage/invalidation 单列，
不能继续以“必须相等”判正常 C1 非法。旧直接路径的原测试与视图不改变。

动态 `_terminal` 须核该 receipt 自己的 choices 与准确调用完成；相反边未选、
缺 transfer 未知。同步 D 的查询不跨 future resume；父 P 的两 cut 另由上面
通用入口及实际 segment/Drive 关系证明。opaque/unknown helper/cycle/缺身份
保明确边界，不从“没看到更多 consumer”宣布 dead work。
