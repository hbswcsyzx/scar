# 最终只读复审闭环

本报告把三路限定结论汇总；不是新实验或独立重跑。完整16组继续 OPEN。

## 1. continuation / 首次执行

`value_resource_review` 对最终 `protocol_continuations.py` SHA
`ef26888f07aa6934fe50009a5afc50606dced4f231e52eea8da5d942fa494635`
及原图反例复审：prior case.guard 与当前 guard 联合；互斥静态访次保 None；
must=False 与可能 copy、混合 True/False 不能授 Initial=True；共享预算不足不能
从部分路线推 True。真实首败与修后77P在 continuation 收据，不由本复审冒称重跑。

## 2. codec / 历史 oracle

`cleanup_forward_review` 的独立[closure](continuations/codec-cross-review.md)确认
四种新 rule 即使没有三张可选表也选20；19不能承载新语义，20空能力也拒绝。
独立19 tar、生成器、模块来源及 golden SHA 相符。root另核实际diff：旧 wire
断言保原版本，旧测试只改最大 codec 版本。本轮387P归 A 原 focused，不称独立重跑。

## 3. request / 预算 / 准备开销

`reuse_capture` 最终只读确认 `protocol_async.py` SHA
`6551b7b7fb6b4970e7314cfb7b430fd9e5cad1910f40532117e94198e692072e`：

- `_async_initial_predicates` 按 context 准备，遍历 predicate/frontier 扣共享费用；
  截断返回 None/cursor。
- 历史分支是 L/S 来源选择，不是当前 phase 断言；最初将 stale 历史分支当 bug
  的意见已撤回。源选择报告显式 `current_step_verified=False`。
- `request_state_view` 用轻量 `_Analysis(ctx, prepare=False)`：局部 context、诊断
  列表与 cursor 初始化后跳过全表 maps/inventory。它只调用 support/formal/spend/
  gap；support 的 actual_states/site/use/current 都直接依赖 ctx，无遗漏 map，
  也不递归调用 async_connections。正常主分析与 initial_step 仍默认完整准备。

轻量修复发生在 B 的51P之后，不把旧51P source SHA冒作此最终SHA。最终统一相关
定向负责覆盖两条构造路径；本只读复审未运行测试。root源码检查认同此范围内
无剩余具体阻断，但不扩为完整native/动态/LeWM建模结论。
