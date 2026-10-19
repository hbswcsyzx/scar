# M1 协议证据合账：结构能力与自动恢复分开

2026-10-19；审计基线 `635c9976120ef2120ce8c1e22a5437b04b03b696`。
原 [family 计划](M1_PROTOCOL_FAMILY_PLAN.md) 第5节已经定义：M1 负责规范关系的
可表达与机器拒错，M3/M4 才从任意程序和实际执行自动恢复并验证。原 M2 的
113构造/196字段、十六组和 P5 范围保持不变。

## 1. 纠正持续报告中的账目边界

已有 general/W 零及两 cut→子实现→消费者、真实 BodyRaise 当前 C1，以及
获取失败→caller C1 的条件结构连接已实测。它们应记为已核的 M1 子义务，
不能仅因 source/runtime/value/transform authority=False 就反复称尚未实现。
这些 False 继续保留其本来含义：没有授予源码适用、native、外部身份、自动
恢复或变换权限。完整家族仍需自己的全部正反组合，而非一个代表正例。

前轮 `model_failure_caller_continuations/verified-final` 在841份源码 SHA
`952cf6d7734f8b10901ba23c3a3dd06279657a9ed81cbdf9d09a9d65b5918ff4`
上1747 affected focused 通过；该证据只属于原源码与实际执行过的 selectors。
本轮最终回归另绑定新源码，不能用这项旧绿测填本轮实施缺口。

## 2. 原 G：已核基础与真正组合缺项

| 已有证据 | 能证明的范围 |
| --- | --- |
| program/execution_await_cases | 首次推进前，两臂同 iterator 的原 incoming 与实际选择；缺 case 仍保义务。 |
| general_final / wrapper_final | 独立来源、0/2 cut、持续 B、真实最终 E/F own N/R 与 consumer。 |
| cleanup_final / post_cleanup / raise_continuations | pending/current source/state 与原终端/调用方关系。 |
| failure_cleanup | 内部失败、获取 own RAISE 与 caller 当前完成的两个接缝。 |

case 图实际止于第一次 Suspend，没有 loop、共享最终 callee 的两个原 caller
或完整终端。G 的欠项是将已有关系放进同一完整共享控制图，并验实际回边、
整组输入、最终返回与删除/预算反例。实施与验收见
[原 G 整链计划](M1_SHARED_TUPLE_FINAL_PLAN.md)；是否整 G 通过由逐项证据裁定。

本轮原 G 最终在846份稳定源码上1780 affected focused通过，原1747 identities
保留；第6节各项经独立核表与机器验收后关闭此 M1 条件结构格。原 E/H 的整条
pipeline 重求值与多次独立获取、其他家族和自动恢复没有被本次 copy-loop 代替。

## 3. 原 F17：已有结构证据与有限剩余

下列基线用例均在前轮1747名单中，最终归档会按原 JUnit identity 重核保留。
不能因为没有自动 collector 就把这些结构能力重新列为未实现。

| 原要求 | 已有精确入口（tests/unit/） |
| --- | --- |
| 同 R/B 三次 AWAIT→ASYNC_YIELD | test_program_async_pipeline::test_main_pipeline_has_one_body_request_and_three_real_latest_state_calls；test_execution_async_pipeline::test_one_body_activation_has_three_exact_await_and_async_yield_occurrences |
| HOLD 与 COMPLETE 分开 | test_program_async_connections::test_known_async_outcome_cannot_publish_the_other_session_post |
| handoff、shared incoming、current state | test_program_async_pipeline::test_main_public_query_keeps_await_handoffs_separate_from_item_completion；test_shared_hold_post_preserves_both_selected_sources_and_exact_incoming_choices |
| request 完成与 body 暂停 | test_program_async_connections::test_suspended_body_is_not_finished_when_its_async_request_completes |
| 删除 update/source 不删原义务 | test_program_async_pipeline::test_removing_whole_session_update_keeps_the_original_await_obligation；test_execution_async_pipeline::test_missing_session_update_keeps_the_actual_body_result_as_missing_work |
| 缺 current state Use、旧恢复、预算 | test_execution_async_pipeline::test_missing_current_state_use_does_not_establish_the_session_post；test_resume_cannot_borrow_another_static_suspend_occurrence；test_tiny_budget_preserves_session_target_denominator_and_unchecked_cursor |
| scope、身份冲突与 catalog 刷新 | test_execution_async_session_edges 的三个原测试 |

有限欠项：尚未找到明确将第三次 ASYNC_YIELD 的当前 item/adapter packet 换成
旧同型值的该族专属反例。generator YIELD 的 host-item 反例不能自动填此格。
因此 F17 进入整组关账审查，当前不宣告整组关闭；后续只补准确缺项，不再写
一个重复 session helper。F16 reuse/competition、F18 终止、F19 closed/version
是各自原义务，不能偷偷并入 F17 让结构验收永远漂移。

## 4. 十六组下一步按真实残项推进

| 原组 | 已核结构与真正剩余 |
| --- | --- |
| F12 | general lookup/call/Q 与合法失败/caller C1 已有；native/self 无 W 的完整最终来源和剩余资格类别仍待核。 |
| F13 | 两 cut、持续 B、恢复和最终消费者已有；按精确 selectors 合账，共享 caller 组合由本轮 G 补。 |
| F14 | coroutine 专属 phase/reentry/reuse/throw/close 全表仍缺；generator 表不填它。 |
| F15 | 同 B direct→await 已有；最终值/异常与旧状态、直接资格拒绝仍须完整映射。 |
| F16 | 四 request Create/association/latent/S 已有；reuse/competition/多 request 实际多调用仍缺。 |
| F17 | 见上，优先有限关账，不重写 session 基础。 |
| F18 | known non-None Return 拒绝已有；主动终止转换与自然完成的消费者组合仍缺。 |
| F19 | closed/athrow/aclose 版本条件和失败后续体尚缺完整图。 |
| F20 | GetIterator、首次推进、旧求值拒绝已有；求值失败/无效 iterator/零父挂起的完整族尚待核。 |
| F21 | NEXT/SEND lookup→call、item/final、错源和删除已有，应直接按原要求合账。 |
| F22 | THROW 1–3参数、matcher 三包、guard/case 与 continuation 已有；parent resume/item/exhaustion 的联合映射待核。 |
| F23 | 原 close 注入包/新包覆盖、C1 真终点与 opaque 已有，可做限定 M1 关账审查。 |
| F24 | Task target/delivery/handler/status 已有；抑制后再 await、C1 Replace、实际 waiter 转发仍缺。 |
| X25 | 两 cut pending/context/delegate→终点已有；local-binding 与 loop/merge 的组合及旧值反例待核。 |
| X26 | publication/current session、宽 helper、partial RAISE/release 已有；async/cancel 终结到同一 release 的合账待核。 |
| X27 | await/general/W/C1、async 三 Drive 已有；delegate/cancel 等其余家族仍须自己的组合。 |

该表是有限源码/既有测试审计，不是所有行的最终验收报告；新源码回归和原
正反例逐项核齐后才能关闭相应整格。没有新增 backend/detector、LeWM 特例或
性能结论。完整 M0–M2 后仍按用户要求先停下来讲解模型。

## 5. 下一节点已收敛到具体残项

G 最终回归期间又做两路只读 exact-selector 合账。F21 确切缺 SEND(None)
分流/非None ordinal、advance 自身非 exhaustion 的异常传播、delegate item
冒最终值三项证据；已有 bound-method、whole tuple、state 和 lookup R 的结构
连接不重开。F23 四项静态原要求已有直接正反支持；缺整 close/C1 附件删除与
delegate-close/X27 动态整链的准确交叉证据，不能以 close lookup fallback
删除或静态 DECLARED 填格。有限自验计划见
[下一组原协议节点](M1_PROTOCOL_NEXT_GATES.md)。不新增家族分母，不进行新后端。
