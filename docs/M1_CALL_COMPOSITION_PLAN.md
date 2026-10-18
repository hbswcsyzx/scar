# P4 返回后下传：调用路径组合计划

2026-10-18，基线 `ea13ecf0d2bf4117e5e378e5774211d109bc3e3a`。
上一轮是实际进展：原返回连接、42 新例、788 受影响定向与 WIP 推送；不是完整
模型完成。本轮继续原 M0–M2/P4 工作，固定 16 组仍不缩减、不关闭。

## 1. 建模连接决定

Operation / Value / StateLocation / Region / Resource 不变。调用入参、callee
entry formal、RETURN/RAISE 和 caller 结果是原图的不同端口；同 callee 的两次
静态调用不能合并，顺序调用也不能被写成嵌套 caller context。

```text
independent expected source
    → known CALL/INVOKE returns → exact next-call actual
    → that call's entry formal seeds
    → local CFG / another known return → next exact actual
    → ... → final consumer Use
```

input_origins 的原配方仍是候选路径库存，不是身份或改写许可。当前 leaf 在
OperationResult 停止；本轮不凭 leaf 反选 expected，而用 return-aware fresh
flow 验证每段实际操作数。沿已有原 CALL_ACTUAL_TO_FORMAL、CFG_COPY 组合；
不加 producer、绑定事实表、状态 SSA、wire family 或优化 backend。

## 2. 必须实现的规则

1. 从每条 recipe 的原序列取得准确 caller/callee/ordinal/actual Use/formal。
   不搜索同 region 的“第一个类似调用”。逐段验证 actual.value 是否 fresh，
   而非 source 仍存活或集合非空。
2. 在一个准确调用点，同时映射所有已证复制的 actual ordinals 为 formal seeds。
   重复实参及多个复制槽不能丢。None 的来源不当 False；已证 seeds 能独立
   完成 must 时可给有限正例，缺失部分影响结论则保未知。
3. 来源在另一个 helper 时，沿原唯一 caller 链上返到独立确定的共同 caller，
   再下传。复用已实现 exact export；多 caller/动态 occurrence 不得按 actual 猜。
4. 每个下传段仍使用原 freshness/reset 和同时 CFG rename。INVOKE 入口只消费
   调用前 actual；自身未来 completion 不能供应自己的 entry。新 state 版本
   不能冒充同 Location 的旧版本。
5. 原 recipe 的 CFG 选择按完整 caller prefix 归属该段；与用户全局 guard 区分。
   不把某次 callee visit 的选择施加给前一个 sibling 调用。保原 choices/context
   给整组输入关联，条件结果不宣称实际 visit 已选择。
6. 每条适用 recipe 都进入分母；所有完成且为 True 才给整体 True。混合、缺口、
   未决递归/STATIC_CYCLE、无法确认的上下文或预算截断保 None/gap/cursor。
   原生/opaque 无 copy summary，不能凭类型、内容或同 ordinal 穿透。
7. 与既有 ConnectionContext 共用索引、return summaries 和单一预算。缓存键保
   源求值阶段/复制集合、精确 caller/frame 与全部适用 guard；截断不缓存否定。
8. 报告保准确每段 actual/formal、原 Use、局部 guard、match 与 support。所有
   native/runtime/identity/transformation 权限仍 False。

## 3. 自主验收节点

| 节点 | 证据 |
| --- | --- |
| D | 三路只读审查、原端口/上下文/状态规则与本计划冻结 |
| R0 | 原合法 H(H(x)) 到 helper 内真实消费者的首红，不是缺 API 的错误 |
| C | serial/nested/sibling、不同 actual、重复 ordinals、guard、旧循环值与 opaque |
| S | N/R 后新旧 state、未改域、内部新版本 unique-export 再下传、自身未来 completion |
| Q | 所有 recipe 分母、准确 frame/条件证据、共享预算、准备索引与缓存隔离 |
| V | 三路只读复审，冻结作者后统一受影响 focused；旧 788 与原夹具/证据保留 |
| A | 保护 checkout、源码/证据指纹、独立 WIP commit/push 与报告 |

测试串行，只跑解决具体风险的必要定向；首次失败、修后与最终统一各自独立目录。
不因当前源变化重跑/改写旧报告。全部原 16 组就绪前不运行组件/full，也不运行
重型 LeWM 或产生新加速比。新证据在 model_call_composition/。

## 4. 后续顺序

先闭合这里的调用返回/下传，再继续异常 matcher 的 packet/handler/N/R/branch
连接与原 P4 family/组合矩阵，之后 P5/M2 和原整体验收。不能把一轮正例通过
当成所有逻辑值 provenance、整个 LeWM 自动恢复或优化方案生成已经完成。
