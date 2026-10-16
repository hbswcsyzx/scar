# C0 control validator：独立静态审查

基准 HEAD：`618cf83fff4e82ed0e873db0d2f4e9a14d6e4ab5`，审查工作区新增实现。
范围：`control.py`、`control_validation.py`、`model.py`、`validation.py`；
同时只读检查相关 binding/environment validator 的接口假设。未运行测试、目标程序。
codec/public exports 正在接入，不作为语义缺陷；不要求本批完成 C1 cleanup。

## 结论

发现两项具体问题：一项允许错误 loop 目标，已看到 root 修复；一项错误拒绝
known-callee INVOKE 的本地 pending 保活，已立即通知 root。下列结论是静态代码审查，
不是自动图或语言执行验收。除这两项外，当前检查范围未发现另外的确定阻断问题。

## F1：内层无标签 break/continue 可指向外层 loop（高，修复已读）

原实现只检查 `ancestor(port.scope, owner)`。构造：

```text
FUNCTION F
  LOOP outer: outer_header
    LOOP inner: inner_header, inner_body
  after_outer
p = Break(port=outer_break) in inner_body
outer_break.scope=outer; outer_break.block=after_outer
```

outer 是 inner_body 的祖先，break landing 在 outer 外，原两条检查都成立；
但 Python 内层 body 的无标签 break 必须选择最近活动 inner。Continue 同样可错连。
这不是 source 名字匹配问题，也不是待实施 finally 语义；是所声明 scope/target 自相矛盾。

已看到 `target_active()`（当前约153–162行）：先验证 ancestor，再向上寻找最近 LOOP，
要求其 ID 等于 port.scope。constructor 与 dispatch 都调用此 helper。
因此 inner body 错指 outer 被拒；inner else 若按规范归 outer 而不归 inner，仍可跳 outer。
最终反例测试应分别覆盖 constructor 与 dispatch，不能只让前者错误掩盖后者。

## F2：known callee 的本地 pending 转发被当成跨 Region 逃逸（中，已通知）

当前约247–250行：

```python
bound = selector_use or use_on_successor_arguments
if not bound or operation.callee is not None:
    pending_escape(...)
```

最小合法构造：在 caller 中构造 `p=Return(x)`；INVOKE 已声明 callee g，
`invoke_arguments` 仅包含 g 的普通参数与当前 state。NORMAL/RAISE 两条完成边各用
一个独立 UseID 将 p 转发至 caller 的私有后继 BlockArgument；p 不进入 g 的入口。
正常的结果/异常/各自 post-state 均按原 INVOKE 协议产生。

该图 pending 全程在 caller Region，依然满足 C0 不支持跨 Region pending 的限制；
但仅因 `operation.callee != None` 被拒。相同 CFG 将 callee 改成未知 None 却不触发此项。
建议只禁止具体 pending Use 出现在 call_arguments/invoke_arguments 或 region exit；
不能以 operation 是否有已知 callee 判断所有后继转发 Use。现 `bound` 检查本来就
能排除纯 call 实参，但补显式 actual-membership 检查更清晰。
配套对照：本地两条 completion edge 转发合法；给真实 callee formal 传 p 仍必须拒绝。

## 已核查的固定点和共享合流行为

- `facts` 集合与 `incomplete` 只增加，构造种子有限。dispatch 某 case 的启用条件随
  已知 ports/incomplete 增长只会开启；`selected == source` 的固定 case 交集也是单调。
  未发现状态反复撤回造成不收敛。最坏成本随图及 port 数增长，不是常数次遍历。
- 自身 token 经 dispatch 转发只携该 edge.port；其他 pending token 保守携自身并集。
  同块多个真实 incoming edge 都被遍历，不按目标 block 去重，因此不会漏 phi 入边。
- shared block 可接同类型多 case 投影，这是 canonical 逐边 phi，并非自动错误。
  Return Reference 与 Raise Packet 不能投影进同一个同类型 formal：每条边分别执行
  projection_type 校验；两者分占不同端口且各有完整实际参数的共享合流则可表达。
- PendingPayload 不创建全局 OperationResult；它只在对应 Successor 的参数位置定义
  目标 BlockArgument。投影次数、对应 case 类型和 Return 引用未知精度均被检查。
  不需要为了沿用 INVOKE 规则而把所有 pending shared targets 一律禁止。
- `PendingFacts.complete` 是对声明 CFG 的 port 覆盖完整性，不是动态路径可达性、
  payload 身份来源、cleanup 完成或执行次数证明。未见实现将这几者直接合并。

## 边界、异常与崩溃路径核查

- pending entry 参数会进入 incomplete；INVOKE Produced pending 也进入 incomplete；
  无构造来源的 token 得不到 complete。pending 普通 producer 必须有唯一构造表行。
- constructor 要求自身唯一结果、精确 owned Uses、无 callee/terminator/state accesses；
  此为逻辑 aggregate 构造，不是对来源 Python 计算/引用生命周期的纯性证明。
- state 没有装进 packet/pending。每 block 完整域、当前 SSA Use、state 类型与
  逐 completion 后态仍由原 validator 检查；PendingPayload 若投成 state 会类型失败。
- Return exit shim 必须准确转发选中引用；Raise shim 转发选中 Packet。替换成其他
  支配且同类型的值会触发 pending_exit_payload，而不是仅靠类型相等通过。
- packet 两个字段是本次声明传播的 exception/traceback 引用；类型检查不证明它们
  是实际有效 Python 异常/traceback，也不冻结异常属性或 active handled context。
- 关键直接索引前存在 core registry/origin/CFG/owned-Use 检查；scope 阶段错误先返回，
  parent 循环与缺失被隔离。当前公开 validate 调用顺序下未找到确定 KeyError 路径。
  `derive_pending_facts()` 自述要求先完成结构校验，不作为任意 malformed graph decoder。

## 本报告不能证明

没有验证源码 scope 是否与 AST/symtable 对应、loop landing 是否真实源码 header/after、
异常 normalization/handler context、cleanup 顺序/覆盖/生命周期，或 runtime occurrence。
这些不是用 C0 accepted graph 暗示已完成的能力。尤其 CLEANUP scope 声明本身不授权
执行 finally；本报告也不把 temporary codec 接线或尚未跑的测试结果记为通过。

## 审查终点源码 SHA256

- `scar/ir/program/control.py`: `6e72a155b807dfe0058bbe2d0ae1bf3920752555ddcf51749817182a59677e25`
- `scar/ir/program/control_validation.py`: `73415377dee70aca0f2f844b5e6bdcad6ec18cff44ca7859c77492db08643642`
- `scar/ir/program/model.py`: `f10d06f817cd49ac44b0e3d253815612dd03057ad56c9e36ee62c525d1949104`
- `scar/ir/program/validation.py`: `061a48fcfde5852ed00d61424a64978a2de33898469d48787d97e4e1f2e6a5b0`

## 追加：两项修复的只读闭环（保留上面的初始失败条件）

F1 原条件为任意 `ancestor(port.scope, owner)`；现 constructor/dispatch 均改用
`target_active()`，对 BREAK/CONTINUE 检查首个 LOOP ancestor 必须等于目标 scope。
F2 原条件为 `not bound or operation.callee is not None`；现条件精确为
`not bound or use.id in (*operation.call_arguments, *operation.invoke_arguments)`。
后继专用 Use 不再因已知 callee 被拒；真实跨函数 actual 仍受拒绝。上述两个变更已读，
当前 `control_validation.py` SHA 为 `73415377dee70aca0f2f844b5e6bdcad6ec18cff44ca7859c77492db08643642`。
结论：两项代码层修复成立；本次有限静态范围未再发现确定阻断项。root 将运行反例，
本报告未运行或代报这些测试，不升级 C0 的 source/runtime/cleanup 权限。
