# P4：跨调用的原 copy 消费图进度

2026-10-19；开发基线 `5c8b60a0f81739445fa240224b101197cb93db5d`。
**PROGRESS；完整建模、原 A–H/16/P5/M2 继续 OPEN。**
延续[原整门计划](M1_AWAIT_OUTCOME_PLAN.md)，本轮查询合同为
[D6](M1_COPY_CONSUMER_GRAPH_CONTRACT.md)。

## 模型与实现

五类实体仍为 Operation / Value / StateLocation / Region / Resource。
这轮新增的是原图投影 `ProgramIndex.copy_consumers(source, guard, budget)`，
不是第二套 producer 图，也不是自动恢复全部程序来源的前端。

```text
原 source 的本次求值点
  -> caller 的精确 OwnedUse
  -> call 的完整有序 actual/formal tuple
  -> 独立静态 call-path frame 内部 OwnedUses
  -> callee 的原 NORMAL/RAISE 出口 Use 与 ordinal
  -> parent call 的原结果端口和 landing position
```

同一 helper 被两处调用保两个 frame；frame key 不是 InvocationID。
`RETURN(x,x,state)` 保三个独立 Use/slot；`RETURN(x,y,state)` 不因 y 与 x 无关
而否定 x 自身的消费。view 不把 packet 提取、encode 或其他计算变成 copy 边。
状态读/写之前的 Use 可以消费来源，写出的新 StateVersion 不是旧版本 copy。

| 文件 | 职责 |
| --- | --- |
| `scar/ir/program/copy_consumers.py` | 原调用/端口库存、静态 frame、每 Use 的 may/must 和显式边界。 |
| `scar/ir/program/copy_flow.py` | 从 await 文件移出的原求值相对 flow/必要控制边；复用既有 CFG 求解。 |
| `scar/ir/program/call_returns.py` / `protocol_connection_flow.py` | 复用 callee return 摘要；仅消费者查询可保留未解边界之前的已知 copy，缓存隔离。 |
| `scar/ir/program/await_outcome_flow.py` / `await_outcomes.py` | 在原 ledger/公开 consumer 中引用同一 consumer graph，不授予最终提取语义。 |
| `control_validation.py` / `validation.py` / `protocol_validation.py` | 区分普通 CALL 的 typed packet 载体与 constructor；NoEntry 结构先核，完整语义复制检查共用已验证 core 的 return-aware context。 |

mixed return 的 must-summary 不能使调用前的已证输入关系消失；递归也不能删除
原调用边界。新查询可保留已知 copy 的保守下界；未知返回不制造结果 copy，
未出现在该不完整下界中的项保持 UNKNOWN。可能/必然/未解分开，CONDITIONAL
不等于 CONTRADICTED。原 `source_binding` 和验证默认行为不切到此查询模式。
flow 与 summary cache 含模式；缓存同时保未知原因，不只缓存 Value 集合。

普通 CALL 的 exception-packet 是 callee 已有类型端口的载体，不要求伪造一个
违反 constructor 限制的本地 PacketDefinition。对应 slot/type、完整 call 签名及
原 callee 图仍须校验；pending/cleanup token 保原词法构造限制。真正 primitive
packet 仍须原 constructor，CALL 上伪造 constructor 仍拒绝。协议检查没有跳过
复制验证，也没有全局把 False 改为 None。

## 证据与自主验收

证据根：`artifacts/experiments/b1_call_operands/model_copy_consumers/`。
全部 interpreter/test 由 root 使用现有 conda lewm 串行执行；执行时所有作者冻结。
每次 attempt 独立保存 command、完整日志、JUnit 与前后源码 registry。

| attempt | 实测结果 | 原因 |
| --- | --- | --- |
| first-red | 24F | 19 项通用 API 缺失；5 项真实 ordinary CALL packet carrier 被 core 误拒。 |
| implementation-01 | 38P2F | 新 24 与既有 control graph 16；mixed return 丢调用前证明、recursive 漏内部调用锚。 |
| implementation-02 | 40P | 上述 40；之后另有索引查找修正，不能归给最终源码。 |
| review-regression | 50P | 新 34＋既有控制图 16；缓存缺口重放和 budget1 实际工作反例通过。 |
| accepted-final（原 attempt 名，失败） | 1549P2F | 校验顺序变化暴露 lifecycle 对 NoEntry 的前置依赖；两旧拒错例抛异常，未改旧断言。 |
| no-entry-regression | 86P | NoEntry 结构准入先核、完整语义延后；未解 payload 不授 lifecycle seed。 |
| verified-final | **1551P/0F/0E/0skip** | 793 个源文件前后指纹相同；保旧 1501，再加新编 34 与新增覆盖的既有控制图 16。 |

最终源码 SHA：`2f3580d5b720a26ebe9f6a9b58e9cba2f1671d92b983b7866f265688913d2d49`；
pytest 151.93s，runner 152.8156958548352s。本结果是受影响 focused，不是组件、
全仓或完整 A–H。归档器 `checkpoint.py --write/--check` 核旧 1501 个 case ID、
新编 34 与新增覆盖既有 16 的区别；版本交付再核保护目录及远端 SHA。
旧 tests/fixtures、Program23/Execution8 codec、
D0–D5 冻结合同及所有失败记录均必须保留。历史 5822 full 只属于其旧 SHA，
本轮不借用该结论。

NoEntry 的结构准入只核原 owner/raw、端口、所选 route/edge/slot 与状态形状，
不核 payload copy、不授 seed；完整检查仍用后续 return-aware context。
生命周期 seed 仅来自原局部完整 copy 检查，失败/未解不给 seed。跨 known-return
精化 NoEntry seed 的既有限制不计为本轮已完成，不能由后续 validation 的可表达
性反推此前推导已精化。两旧失败是本轮真实回归，保完整失败日志。

## 本轮未完成的原范围

完整原分母合账和下一整链交付见
[M1_P4_EVIDENCE_AND_NEXT_WORK.md](M1_P4_EVIDENCE_AND_NEXT_WORK.md)。

独立总审把“已有证据待合账”与“真缺连接”分开：原 self 的零/两 cut、同 B
direct/await、多 Create、旧状态拒错及最终 N/R 链已有 resume/outcome tests；
general 资格与合法拒绝、独立 W/getter、共享 incoming 选择/删 case 亦已有测试。
不能再把它们笼统写成未实现；需要按原 A–H 合账。真正下步优先是将 D6 child
中的 extractor 精确 Use 接成最终提取义务，并沿相应 CallActivation 下降核本次
输入、own N/R、出口与回 caller 的 final consumer；缺 child capture 不能借 sibling。
然后把 general/W 三路来源及 BodyRaise、C1 两 cut 后继接到同一整链。

1. 跨 frame 最终提取语义/执行 occurrence 连接；转发 helper 不是 extractor。
2. C1 全后继及原三路来源、W、多 cut、BodyRaise 等组合；完整 A–H。
3. F12–F24/X25–X27 原 16 组齐后才组件/冻结 full；随后 P5、M2 原 113 构造/
   196 字段及完整 M0–M2。
4. M3 自动全程序结构恢复、M4 证据精化、M5 依赖闭合、M6 化简修改指导仍按
   [完整路线](WHOLE_PROGRAM_MODEL_PLAN.md)进行。

**没有自动完成整个 LeWM 的拆解建图，没有新增变换或加速比。**
本轮无新 detector/backend、LeWM 特例、profiling/benchmark 或环境升级。
原 `/home/zyf/AAA/le-wm` 和 `/home/zyf/AAA/scar` 的 HEAD/status 继续受保护。
