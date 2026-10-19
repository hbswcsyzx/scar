# F16 原义务合账：已有连接、真实边界与本门欠项

2026-10-19。基线 `96b8a322590217151ff6a5e839c7ab17d068f560`。
本文件是原要求审查，不预先关闭 F16。最终新源码/测试结果另写进度与 checkpoint。

## 1. 原分母没有变化

[family 计划第 64 行](M1_PROTOCOL_FAMILY_PLAN.md) 和
[剩余计划 F16](M1_REMAINING_PROTOCOL_PLAN.md) 要求：四种 async request
创建/外来来源→本次关联→交付；首次发送、复用和竞争；不混 R、B、L、S 或 ordinal。
原十六族、P5 和 M2 113 构造/196 字段仍保留。

来源适用性、native 真实性与自动恢复不由手工结构验收推出；也不能用这些
权限未授予为由，反复撤销已经有准确结构与反例的义务。

## 2. 可复用的原证据

下表 selector 的文件前缀均为 `tests/unit/`，已在上一门 2016 项中保留。
本门最终仍须核这些身份的实际同源收据，不能只引用本表。

| 原要求 | 已有精确 selector | 关键结论 |
| --- | --- | --- |
| 四种来源 | test_program_async_connections.py::test_request_origin_projects_its_exact_create_body_and_latent_not_scheduler | NEXT/SEND/THROW/CLOSE 的准确 Create B/L，L 不混当前 S |
| 首步 packet | 同文件 ::test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state | 本次 normalizer own NORMAL packet，独立 RAISE 和全状态 |
| 后续 S | test_program_async_scheduler_packets.py::test_later_scheduler_packet_uses_s_normalization_own_normal_and_separate_raise_states | 当前 S 原 ordinal/normalizer，错 L 有独立拒例 |
| 持续 B 与同 R 多次驱动 | test_execution_async_pipeline.py::test_one_body_activation_has_three_exact_await_and_async_yield_occurrences | 三段实际发生、HOLD/HOLD/COMPLETE、host 与当前状态 |
| 完成后同 R 复用 | test_program_async_completed_reuse.py::test_completed_request_reuses_exact_r_and_latest_states_then_rejects_without_a_second_drive | 同 R、最新全状态、第二调用无 Drive，拒绝 helper own N/R |
| 两 R 同 B 竞争 | test_execution_async_competition.py::test_two_requests_reject_only_r2_then_resume_the_original_body_and_r1 | 独立 R1/R2、R2 COMPLETE、own N/R 后 R1 原 B 继续，缺采不借 sibling |

当前账本中的历史“缺 reuse/competition”文字按原样保留，仅作为历史输入。
当前范围由其 F16_current_scope_review 与准确收据更新，不重复实现这些基础链。

## 3. 四个 R3 阻断是应保留的边界

`test_execution_request_state_history.py::test_old_completed_reuse_has_true_post_and_subject_but_retains_every_opaque_or_write_blocker`
原断言已分别建立 COMPLETE 来源、same R，保留以下四个真实区间因素：

1. adapter.construct 的未展开效果。
2. 不完备 host terminal。
3. 没有独立隔离证明的 context RW。
4. 第二调用的 primitive association。

因此 expected_bool=None，而 captured bool=True 单独保存。该结果验证模型没有
把历史 post、版本路由或观察值当成内容保持证明；原要求不要求将四项变成 True。
主 HOLD→occupancy READ 也须保留准确来源、current support 与实际阻断，不能
宣称已经由 HOLD 推导当前 R2 bool。

独立正例
`test_execution_request_state_history.py::test_independent_complete_post_and_real_ancillary_read_derive_a_conditional_true_boolean`
已核完整当前区间可以得出条件性 True；上一门 CallEffectExpansion 又核精确
suffix→caller→prefix。模型能表达两者，无需为关账给旧 opaque 翻纯或推测隔离。

## 4. 本门真正必须补齐的连接

`test_program_request_admission.py::test_request_initial_step_is_not_body_created_or_general_admission`
准确保持 R.initial 不能单独解释 B.Created 或成功准入。原 request_creation fixture
的 B 刻意来自外部 suspended continuation；它不能填 Created 的正反整链。

本门必须把独立 R.initial、关联 B.Created、有效参数的原 ordinal/None、同一
caller/branch/current support，接到真实 Start、Resume 或拒绝 own N/R/fullstate。
原 `CHECK_INITIAL_ASEND` enum/许可和单个 bool 都不足以代验。

新增本机探针还揭示 S/L 的必要条件，详见[冻结计划](M1_ASYNC_INITIAL_CONTROL_PLAN.md)。
在修复前的 886 文件稳定源码上，两个定向测试均已真实失败：

- 错误 L=None、首次 S=77、实际仍交付 L 被旧校验错误接受。
- 实际交付正确 S=77 被旧校验以 async_delivery_source 错误拒绝。

两份图均有合法 core，错误来自 initial=True 无条件选 L，而非新 fixture 语法。
这是待修的来源模型缺陷，不是性能优化。修复、新正反/缺采/预算收据及旧义务
完整保留后，才讨论本门条件性结构验收和 F16 是否足够关账。

## 5. 停止扩张条件

不能追加“所有 native Unknown 消失”“任意 Python 自动重建”作为关闭这份 M1
声明结构条款的新前置。自动来源真实性、实际物理对应与全程序建图仍须独立
完成，不被条件性结构验收代替。其余八族和 P4/P5/M2 不因 F16 有进展而关闭。
