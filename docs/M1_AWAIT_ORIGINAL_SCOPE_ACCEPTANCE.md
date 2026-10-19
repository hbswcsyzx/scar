# 原E/H模型结构验收与F15准确残项

2026-10-19。**Verified：原E、H的M1条件结构行关闭；G保持关闭。**
整个await A–H、P4、P5、M0–M2未完成。没有源码自动恢复、native适用、运行
身份或变换权限的新增证明。F17/F21/F23保留；其余十三家族仍未整体验收。

## 1. 验收依据与方法

依据原[M1_AWAIT_ACQUISITION_PLAN第2节](M1_AWAIT_ACQUISITION_PLAN.md)与
[M1_AWAIT_COMPOSITION_PLAN第2节](M1_AWAIT_COMPOSITION_PLAN.md)，两合同原
字节保留。新[冻结N4计划](M1_AWAIT_REEVALUATION_PLAN.md)要求原义务逐项
合账，不能由一个正例自动关闭。三路只读复核后，root直接读关键断言并核
本轮同源JUnit，而不是按source/native=False反复重开结构要求。

`verified-final`：**1845通过，0失败/错误/跳过**；853份源码SHA
`908182cfa79d2fb0609c6747fb4b96fe83a202949af3cb5dbd3e940a1b97da92`，
运行前后相同。`original-scope-accepted`又实际执行0.2413秒的证据合账，
不启动测试；逐条要求有非空green JUnit identity，生成
`artifacts/experiments/b1_call_operands/model_await_reevaluation/original-scope-audit.json`。
该文件保存原合同SHA、每条完整selector、实际参数化identities、旧/新关闭
集合及仍开放范围。checkpoint每次重算，不能用描述性PASS替代机器证据。

供应图的正常关系、core拒错、公开query连接分开计入对应条款。core能准确
拒绝旧SSA/错instance是有效证据，不能伪报为新增协议检测；实际missing需
由query保缺证。原始模型、准确发生、数值/引用身份和优化许可仍分离。

## 2. E：同B direct/await及旧来源拒绝

原E限定generator-coroutine，不要求所有来源的无限参数乘积。下表简称的
文件均在tests/unit；完整可执行selectors在机器审计JSON。

| 原条款 | 准确测试及断言 |
| --- | --- |
| 同GENCORO的direct和await | program_await_resume::test_two_cut_direct_and_await_calls_share_one_original_body_and_keep_final_extraction：首direct、后两await、唯一GENCORO body、两Suspend；不是改标签的两份图。 |
| 持续activation/segments及准确结果 | execution_await_resume::test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction：三Drive/segment同activation，逐entry/outcome/source关联；execution_await_outcomes::test_actual_completion_packet_and_final_value_stay_in_their_exact_instance核本次packet与final。 |
| 当前最终值、异常与state | 本轮pipeline_reexecution的self-two-BodyReturn/BodyRaise：逐完整slot、原state、准确callee/driver；正常完成走E/F own N/R，BodyRaise走真实B包。 |
| 多Create同代码不混 | execution_await_resume::test_two_same_code_creates_do_not_select_the_other_body_origin要求body_instance_source；test_repeated_root_evaluation_never_borrows_a_sibling_body_activation核独立Create/B/source。 |
| 旧Resume/另一Drive | 同文件test_old_cut_cannot_be_used_as_the_second_resume_ingress核transfer_resume；test_same_body_does_not_allow_another_drive_entry_and_outcome核entry/outcome/segment准确拒错。 |
| 旧state | execution_resumable_links::test_old_state_incarnation_cannot_replace_the_new_resume_formal；execution_flow::test_loop_rejects_old_result_and_old_state_from_same_static_definition核stale_incarnation。 |
| 真重执行、不按时间/共同root选源 | 本轮source_visits的latest/earlier，以及pipeline原首节点和完整11参数格；同B双Get与每轮newB两种原拓扑均保留。 |

裁定：已具全部原E所需结构证据。native/self其他完整获取资格、失败/C1及
coroutine phase等仍按其原A/D/F/F12/F14等条款核，不回填成E的新门槛。
E关闭也不自动关闭F15；后者原典型拒例仍有两项确切欠证，见第4节。

## 3. H：共享预算、原分母及证据生命周期

| 原条款 | 准确测试及断言 |
| --- | --- |
| index/flow不重建 | program_connection_flow::test_prepared_query_does_not_construct_a_second_program_index禁止二次构建；program_input_origin_pairs::test_origin_route_indexes_are_built_once_and_reused_across_source_and_joint_queries核仅构建一次；composition_refresh核canonical flow复用、派生map不共享。 |
| budget1原source/branch/N-R/jobs/cursor | program_await_outcomes::test_budget_one_preserves_all_original_drive_successors_and_unknown_job_total；pipeline_reexecution::test_shared_budget_retains_both_round_anchors_and_all_original_outcome_keys核两轮计数与checked+pending守恒，未查总数None。 |
| 共享预算贯穿后续join | execution_await_outcomes::test_late_budget_exhaustion_never_reports_a_complete_tail_or_unchecked_compatibility用实际cost−1；program_await_raise_continuations的parent join截断；source_visits实际半成本截断。root源码核同一ConnectionContext/ValidityBudget传入，无子查询预算重置。 |
| 准确copy ancestry有界 | execution_await_outcome_boundaries::test_each_conversion_packet_is_joined_to_its_exact_terminal_before_parent_delivery；program_copy_consumer_budget_work::test_budget_one_stops_before_query_time_callee_return_join禁止免费展开；source_visits历史port预算截断保原False收据。 |
| fresh denotation/snapshot/detach | execution_await_wrapper::test_wrapper_query_detaches_returns_and_rechecks_a_changed_external_identity_catalog；execution_body_values::test_query_rechecks_mutable_external_value_artifact_instead_of_using_old_denotations；本轮pipeline detach/fresh核两轮。 |
| reexecution保准确发生 | source_visits同static Get两次、pipeline同caller真实回边两轮；来源、B及current consumer分别核。 |
| 全缺采/删除保原分母 | execution_await_outcome_boundaries::test_whole_capture_deletion_keeps_static_outcome_and_failure_keys；pipeline删全部AwaitBodyLink，不删除原义务。 |
| 无capture不假称预算不足 | execution_await_inventory::test_wholly_missing_capture_preserves_source_and_never_invents_a_drive四格：budget1也保source/job、零occurrence、PARTIAL，明确truncated=False、cursor=None。 |

裁定：原H的横向结构合同齐备。无需把缺采乘每来源/每cut；未测所有整数预算
cut不等于原要求缺失。已观察到的candidate内部预算接缝本轮实际修复并绿测；
没有把所有budget后的False无条件改成None，未查工作不授True或授权。

## 4. F15：主链已有，两个原反例仍缺

**Observed（源码/测试审计）**：主链已由E、actual outcomes及新self-two
Return/Raise准确连接；wrapper不能凭类型拼接有独立held B/copy冲突反例。
此前“所有来源的direct/await final矩阵”宽于原F15，应收敛回原条款。

**Rejected（整族关闭）**：没有找到以下两个准确M1 negative selector：

1. 已知ordinary GENERATOR误获direct/self **await acquisition**资格后仍
   成功推进。普通generator被next直接驱动本身合法，不是这个反例；general
   `__await__`错误返回GENCORO的拒例方向也不同。现源码有坏kind检查，但
   “代码看起来会拒绝”不能代替实际core-valid图上的测试。
2. 另一个Drive的adapter结果替代当前准确final结果。错误O关联、其他helper
   result或另一wrapper terminal包相关，却不能改称已测这个字面替换。

**Proposed**：只补这两个最小准确变体，先核原图/core合法，再实际运行公共
校验；已正确拒绝则只增加证据，真失败才修公共规则。没有新backend，也不
扩成nativeB全路线。F12/F13等下一轮同样按原义务合账，已测基础不重写。

## 5. 剩余范围与版本边界

A/B/C/D/F仍逐原合同整体验收；十三家族、P5和M2原113构造/196字段保留。
M3/M4自动建图/实际采集不代替M1/M2，也不阻止已齐结构条款关账。
整个M0–M2真齐后先按用户要求解释模型；LeWM自动全过程拆解、TRANSFORM及
clean A/B加速均没有因本轮结构验收而获得新结论。
