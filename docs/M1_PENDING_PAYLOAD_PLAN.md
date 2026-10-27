# P4：pending payload 的通用来源连接

2026-10-19，基线 `cd25456357ec3e569d32ad246bd5890ef8fc628f`。
上一 goal turn 为 progress：独立 E0/EL/EM 路径、965 affected focused、归档与推送。
继续原 M0–M2/P4，保 F12–F24/X25–X27 原16组，全部仍OPEN。

## 1. 审查结论与模型不变量

三路只读审查确认：原图已有全部必要实体，不加 wire、基本节点或第二份 producer。
Operation / Value / StateLocation / Region / Resource 不变。缺的是共享来源查询对
以下准确语义投影的解释：

```text
原 payload OwnedUse → PendingCompletionDefinition(token, port, payload)
  → 本次 pending token 经原 Use/formal/SavedInput 传递
  → C1 Enter / Resume 或 fresh Replace + 当前 state / saved context
  → 原 CleanupRoute 的准确 port
  → 原 PendingDispatch 的 selector + edge.port + PendingPayload 位置
  → 原 landing formal → 原 terminal / helper consumer
```

pending token 不是 payload，port 相同也不表示 payload 相同。裸 PendingPayload()
不含 owner/edge/slot，不能成为新的独立 expected source。其位置由准确原 dispatch
edge.argument 与原 landing formal 配对。原 C0/C1/resumption/state 验证继续负责
词法栈、入口覆盖、同 entry context、fresh replacement、当前状态和 saved slot。
本轮查询解释这些已校验的端口，不另建调度或 cleanup 状态机。

## 2. 统一来源算法约束

- 在现 ProtocolFlow/ConnectionContext 的 current-copy 固定点解释 projection，
  不能把 saved_actual_use(PendingPayload)改成某个猜测的 Use。
- 临时派生事实按原 pending carrier + selected ControlPort 区分 payload 的来源。
  同 port 的所有适用来源必须 AND；不同 port 在该 dispatch case 前分开。不能
  ANY 一个好 constructor，也不能用端口集合或无种子环自证 payload 同一。
- 可达性、source 再求值 reset、must/may、guard/caller context、预算和 cache
  都复用原查询。旧 pending 仍可存在，但不能因 source 再求值而冒本次 payload；
  不允许用“删掉旧 token 可达性”伪造成功。
- input_origins 保准确 pack/selector/port/projection witnesses，不能依靠另一套
  不一致的无条件 copy 规则。payload 通过普通原 CALL/INVOKE 可继续传递；private
  pending/context 仍不允许作为任意 call 实参。
- C1 正常恢复保原 token；finally Return/Raise 可选新 pending 覆盖旧结果；应
  分别追踪新 selected payload，不能将旧 E0 未到达终端直接判为整图非法。

## 3. 必做验证，不缩为 frontier-only

| 门 | 交付与自主拒绝标准 |
| --- | --- |
| D | 三路源码审查及本设计冻结；无新 producer/state/wire。 |
| R0 | 既有公开 source_binding 穿原 PendingPayload 的真实缺连接首红；不是新API缺失。 |
| P | 同port两payload、不同port合流、guard A/B、dead-vs-active pending、source/constructor再求值与无种子环。 |
| O | 原 input_origins 的准确来源库存/projection witness，以及投影后进入真实已知 helper 的连接；不可仅本地特判。 |
| C | 新的真实 active C1 两cut图：各自原SavedInput、pending/context/frame/delegate及新current state，最终真实dispatch与终端。旧fixtures不改。 |
| E | Replace/Resume、旧token、新payload、错误context/state、删除/未知/预算的core归属与新连接归属分别说明；不冒动态同次恢复证明。 |
| W | 保原Program1–22/Execution8和旧fixture字节；不增schema来掩盖查询修复。 |
| V | 三路只读复审→所有作者冻结→统一affected focused，保原965义务；原16组未全就绪前不跑组件/full。 |
| A | 计划/证据/反例/源码/保护目录核验，独立WIP commit/push，更新模型/状态/路线。 |

统一验证必须包含真实两cut C1及投影后helper，不用两个互不连接的旧图代替。
有限 query 证明供应模型的来源关系，不证明真实 Python/native/动态 occurrence
或优化权限；这些标志仍False。原X25的完整组合/发生关联及其余15组不会因本门
部分连接通过而关闭。本轮不加detector/backend，不跑重型LeWM，不给新加速比。

## 4. 所有权与效率

A负责共享payload transfer/ProtocolFlow；B负责通用projection反例fixture/tests；
C负责真实两cut C1 fixture/tests；root负责input_origins/共享查询桥、证据及集成。
共享接口先用原端口决定，不并行写同一文件。子代理不启动Python/probe/测试；
root串行运行必要定向、保所有失败。最终source冻结；不按每个函数重复全仓测试。
证据写 `artifacts/experiments/b1_call_operands/model_pending_payloads/`。
