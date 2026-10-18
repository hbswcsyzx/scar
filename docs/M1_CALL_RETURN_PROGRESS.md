# 通用调用返回连接：实施记录

2026-10-18。依据 [冻结计划](M1_CALL_RETURN_PLAN.md)，原 P4 固定 16 组仍 OPEN。

## 发现与修复

**Observed:** 在合法供应 IR 中，`x → identity(x) → consumer` 的原 Use 查询返回
False。首红 `red-identity/` 记录 1 FAIL；并非未定义新 API 导致的失败。
旧引擎能看 entry formal，但没有把 callee 出口接回该次调用。

**Implemented:** `ProgramIndex.source_binding(expected, actual, guard=None, budget=4096)`
复用已验证的 index。expected 是准确单槽原端口，actual 是原 OwnedUse；返回
三态 match、原路径、缺口、未完成 cursor、统一预算及 summary/call 证据。
ConnectionContext 的既有连接查询也使用此能力，历史 ProtocolFlow 默认仍只做局部流。

### 原图如何连接

1. 从每一次原 CALL/INVOKE 当前 fresh 值集合，同时映射全部 actual ordinal；
   同一个值传两次，两个 formal 都纳入，不能只找第一个匹配。
2. 在 callee 自己的 CFG 上分析，逐 kind/slot 检查所有相关真实 RETURN/RAISE Uses。
   返回的是 callee-local 投影；迭代工作表处理依赖，未决递归保具体缺口。
3. CALL 接自身 NORMAL 结果；INVOKE 按真实 edge.kind、CompletionResult.index
   接准确 landing formal。边号、结果槽、formal 位置是三个不同量。
4. callee 内 source 向外导出时，每层保唯一原 caller frame；同一次调用里该 source
   的所有已证结果复制一起进入原 freshness 分析。INVOKE 以 query-local edge seeds
   表达各边自己的复制，不伪造 common AFTER 或新的图 producer。
5. 源求值重执行清除旧结果、旧 loop carrier。复制同一 Reference 不传播旧内容
   状态；某域 WRITE 输出的新 StateVersion 不能以同 Location 冒充旧版本。

**Observed:** 独立审查发现，最初逐槽导出对 `RETURN(x,x,state)` 后的 caller 分支
合流给 False。`red-multiple-exports/` 保留真实首红。修为同 call 分组后，普通双槽
及 N/R 两完成合流均通过。另一个首败来自不合法的无出口夹具；已用真实 C1
cleanup 截留 pending Return 后永久循环替代，保留原失败日志，未跳过 core 验证。

## 预算、缓存与证据

summary 缓存包含 callee、精确 seeds、must/may、当地及完整 query guards。
不能复用另一嵌套 helper 的分支选择；无调用限定的 callee guard 遇多 caller 保未知。
callee 内 source 多 caller 也不按 actual 反选 occurrence。

actual 映射、依赖工作、出口与 terminal、completion slot、ancestor/export 检查均
共享一个预算。原出口 Uses 直接复用 ProgramIndex 已准备库存，查询阶段不额外
排序或先物化整份列表；准备索引与查询收费分列。截断不转换成否定结果。
top-level bind 重置本次诊断；缓存重新播放自身未决原因，避免旧 gap 无关累积。
公开 source_binding 每次独立上下文，因此报告不共享可修改的分析缓存。

报告中的 summary/call inventory 是原图上的派生证据，不是第二套 IR。
`source_runtime_verified`、`runtime_identity_verified`、native applicability 和
`transformation_authorized` 均 False。

## 自主验收

必要定向已分别归档，不覆盖首败。最后统一受影响 focused 的具体结果与源码
指纹写入本轮 `model_call_returns/final-focused-repair/` 和 `checkpoint.json`。
本轮没有组件/full 验收；上一轮 746 和历史 5822 full 保持各自源码归属。

首次统一批次 `final-focused/` 为 786 PASS / 2 FAIL，源指纹稳定；旧的确定性查询
在 4096 预算内截断，声明表重排因此也改变截断前费用。没有提高旧预算或修改
断言。第一版仅缓存出口 projection 仍不足，第二版精确 caller bundle 缓存仍不足，
两轮失败的定向日志分别保留。最后定位到已完成局部 flow 命中被 driver 当新 job
重复收费；原 CFG 实际工作已由原引擎收费，改为只对新 summary 依赖调度收费。
同时复用同 source/完整 guards 的出口投影、该精确 call.id 的输出 bundle，以及
完整扫描过的 ancestor 关系；每个消费者仍重新核对自己的原 Use/freshness。
修后旧 3 个确定性测试在原 4096 下通过，包括八个 hash 进程及声明表重排。
诊断时临时用较大预算完成成本清点的 JSON 明标 not_acceptance，不用作验收。

**Verified:** 最终 `final-focused-repair/` 为 **788 PASS**、零 failure/error/skip；
此前 746 个案例与首次失败批次全部 788 个身份均保留。新增 42 个案例。
pytest 32.22s，外部 runner 33.057580s。全部 **696 份源码** 前后指纹均为
`3274ed528cb59c35d939bdf5d210c9554648098aa0eb2ee56ee2133dfa4eee3c`。
三路只读复审覆盖原连接、状态与最终缓存修复；最终定向期间所有作者冻结源码。

| 验收节点 | 当前结果 |
| --- | --- |
| D | 原图连接审查与计划冻结完成；原 16 组分母保留 |
| R0 | 真实 identity False 首红保留；修复纳入最终同批通过 |
| R1/R2/R3 | 本轮定义的普通 CALL、INVOKE、状态、导出/guard/预算反例全部进入最终 788 |
| V | 独立源码审查、统一 affected focused 与稳定指纹通过；不等于组件/full |
| A | checkpoint 归档核对旧证据、原夹具、保护 checkout；单独 WIP 版本管理 |

## 尚未完成

**Inferred:** 原返回连接缺失会阻断多层 provenance；本修复解决准确 copy 路由的
一部分，不代表任意计算得到的值已完成统一逻辑身份分析。

**Proposed:** 下一步回到方法缺失 fallback 的异常类别 matcher：独立 packet、
handler、自身 NORMAL/RAISE 和真实分支，然后完成原 P4 的 family/组合义务。
lookup RAISE 仍不能直接当 AttributeError。

下一步之前还须审查返回后再次下传的组合：本轮保留的 input_origins 仍可能在
前一个调用的结果处停止；当 consumer 位于另一个 callee 内部时，不能据此宣称
所有跨层 provenance 已闭合。这是源码审查发现的待验证边界，应先用原图正反例
补准确调用上下文，再做 matcher；不能把静态未证连接当值必然不同。

**Rejected:** 依据重复节点、类型或相同 Location 推出缓存；拼接不同 caller；
未知当 NONE；把 must/may 静态连接当运行时等价或改写许可。

完整 M0–M2 建模、自动恢复整个 LeWM、可信 TRANSFORM 仍未完成。本轮没有
新增 detector/backend，没有修改或重新运行 LeWM，没有新的加速比。
