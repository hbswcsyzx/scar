# P2-B：Suspended / Closed 有界结构矩阵

2026-10-18。这是 supplied ProgramGraph 原端口连接验收；不等于 native/source/runtime 适用证明，不关闭完整 P2。

## 终态与源码

仅运行 owned `tests/unit/test_program_generator_admission.py`：attempt006 **57 passed / 3.56s**。原 18 项 case identity 保留，新增 39 项。命令、原始 stdout/stderr、JUnit、逐文件 source hashes 位于 `attempt006/`；registered source 前后均为 `76a9e0cd17ac59716ddb3df751d4af34d0491c2edc86d437a1e206578c1cfd2f`，未变化。本次没有组件、full、工作负载或 GPU 运行。

- fixture：`91a188b42319f375c14aa96f80fc058aad1c2ea72e767860098b95ae1582e8e0`
- tests：`dbe6a4478651e0a95cb0c9e13380d92659886b6da6b1d840b06a16079db54474`
- root protocol_validation：`f0e47e680b529b8b30a6753e429293446674fa49b197d00c51e2efaffc0e8651`
- root protocol_flow：`8d378be283c7001d6b0b65546a18f499046360c224b613256fc6f43656f18ec2`
- request_inputs：`f92acc5fb14b51c852bd2d553cdd26c00a06f01752b0dbb032481a363dfef2b1`

以上两个 owned 文件自本报告起冻结，后续 Running 嵌套 body 补验使用新文件。

## 八格的真实连接

共同 selector：`test_suspended_closed_cells_have_real_phase_branch_known_raw_and_current_host_route[kind-stage]`。每格都有实际 phase READ → 自有 bool → 原 BRANCH；caller 的原 raw pack 实际传入 driver scheduler formal；不为 phase 操作虚增 raw 输入。

| cell | 原输入/目标/本次 host |
| --- | --- |
| Suspended NEXT | 零参 raw；本次 `matrix.suspended.next.none` Reference result + exact None 附件 → Gate actual/forward → BodyResume SENT slot → 本次 YIELD item |
| Suspended SEND | raw ordinal0 与 driver entry payload 是同 caller 的独立实际 Use；joint query 逐 context/CFG/leaf 连到 Gate → SENT → 本次 YIELD |
| Suspended THROW | 原 ordinal0 expanded Reference → 实际 callback-capable normalizer N/R；本次 NORMAL packet → THROWN_PACKET；两种 canonical body 分别捕获后 YIELD 或传播 RAISE |
| Suspended CLOSE | 原 C close fixture 的正常化/Return(value)/ignored YIELD 多 frontier；只加真实 IS_SUSPENDED branch；不重复其 15+5 close/retry 逻辑，不增加 CreatedCloseTest |
| Closed NEXT | 零参 raw → 当前 helper N/R packet → 对应本次 host RAISE；无 Drive/F seed |
| Closed SEND | ordinal0 actual → 当前 helper；当前完成 packet → 本次 host；joint query 保留原 caller/ordinal |
| Closed THROW | ordinal0 actual → 当前 helper/NORMALIZE_THROW_CLASS 声明；当前选中 packet → 本次 host；构造/native 适用仍条件化 |
| Closed CLOSE | 零参 raw → helper NORMAL Reference 附件 None → 本次 RETURN；helper RAISE packet → 本次 RAISE；无 Drive/F seed |

Suspended THROW/CLOSE 的 phase read 发生在 callback 前；到 Gate 时旧支持不再 current，查询必须保留 `admission_gate_support_changed_or_unresolved` 与 `target_compatible_at_snapshot=None`。这不否定历史 bool，也不将旧 phase 保证跨 callback 延长。

## 反例与公开查询

- 八格各自用另一可用同 type bool 替换实际 condition：先排除 core 不可用假阳性，再要求 `admission_bool_source`。
- 八格各自将实际 host 输出 states 换回 driver entry pre-helper states：要求 `stale_state`。
- Closed 四格以额外旧 packet / 旧 Reference 替代当前 helper result：core 仍合法，要求 `protocol_copy`。
- Suspended 四格将本次 YIELD item / close Return(value) 换为旧 owner Reference：core 仍合法，要求 `protocol_copy`。
- SEND/THROW × Suspended/Closed：保持 raw operand 的原 source，另给 input 一个独立同 type caller producer；模型可合法表达未知对应，但 joint query 不得配对，保留 `request_input_binding_unresolved`。
- Suspended SEND 正例要求 joint bindings 精确 ordinal0/同 caller recipe；NEXT 正例要求当前 None producer 经原 copy 到 SENT，而非 raw 虚构 ordinal0。
- 所有查询保持 source/runtime/native/transform false；body packet/Ref 内容与对象运行身份没有据此合并。

## 原失败保留与归因

attempt005 **28P21F** 原输出保留：owned 字段名/断言错误（`operand_bindings`、predicate view 返回原 row）及传播 RAISE fixture 恢复了无真实 NORMAL 的 exit；均在 owned 文件修正。另有实质产品误拒：同 scope 拒绝分支的 CHECK_NEXT/CHECK_SEND result 不可达 Drive，却被拿来否定 direct None/SEND delivery。root 按原 selected result → Drive 的局部可达性过滤 False，Unknown 保留；attempt006 在该修复版本通过。没有通过给 None producer 增加假 processing/raw 输入规避问题。

## 未关闭分母

本文件不替代父计划 16 格的所有变体、consumer 组合、完整 F01–X28、P3–P5 或 M0–M2。原 Running outer continuation 仅 ordinary root Compute，尚需新 fixture 将真实 resumable outer body → reentry driver → RAISE handler → 真实 YIELD 接起来；root 已明确下一项。当前 THROW 的 normalizer/source native 规则属于声明，未自动识别异常类、重放 CPython 或恢复动态实例。close C 的原细分矩阵由其 own gate 保留。本次没有独立增加 Suspended 的另一个旧 PACKET carrier 反例；当前证明范围是所列 current packet 正连接、原 delivery guard，以及逐格 host 来源/状态反例，不将这些相加冒充全部异常 freshness 变体。
