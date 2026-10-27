# 原 await A–H 合账（不重置分母）

2026-10-19；原格来自 [M1_AWAIT_COMPOSITION_PLAN.md](M1_AWAIT_COMPOSITION_PLAN.md)。
上一 source-bound 1551 focused 是已有声明连接证据。下列逐格列真实测试，避免
把已有 self/失败/W/incoming 检查重写为“尚未实现”。每格剩余组合仍显式 OPEN；
没有把 native oracle、单条供应图或测试计数算成完整家族。

本轮新增实现连接的准确证据见
[最终链报告](M1_AWAIT_FINAL_CHAIN_PROGRESS.md)：静态
`test_program_await_final_regions::test_real_child_extractor_own_results_return_through_each_exact_parent_slot`
保零/两 cut × depth1/2；动态
`test_execution_await_final_regions::test_child_completion_returns_through_each_exact_call_frame_to_two_parent_consumers`
仅零 cut 的 depth1 NORMAL / depth2 RAISE。它们补 C/D 的局部实现连接；未把
general/W/BodyRaise/C1 或两 cut child 实际整链算成已完成。下表保原组缺项，
本轮仍无关闭格。

| 原格 | 已有准确测试入口（`tests/unit/`） | 原整格剩余 |
| --- | --- | --- |
| A | `test_program_await_pipeline::test_self_await_keeps_create_get_and_driver_call_as_one_original_graph`；`test_program_await_general::test_general_await_expands_real_lookup_call_qualification_and_iterator_return`。 | native/self 完整终端、其余资格类别、三路来源到统一终点。 |
| B | `test_execution_await_outcome_failures::test_expanded_failure_uses_exact_helper_completion_parent_raise_and_consumers`；`test_program_await_qualification_flow::test_known_bad_candidate_keeps_complete_program_and_infeasible_acceptance`。 | 这些失败/current-state 与 child/C1 整条最终链组合。 |
| C | `test_program_await_outcomes::test_conversion_and_extraction_keep_own_normal_and_raised_payloads_separate`；`test_execution_await_outcomes::test_actual_completion_packet_and_final_value_stay_in_their_exact_instance` 的 zero-cut。 | 真 child region 实现连接及 general/native-self/W 零 cut 后半链。 |
| D | `test_program_await_resume::test_two_cut_direct_and_await_calls_share_one_original_body_and_keep_final_extraction`；`test_execution_await_resume::test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction`。 | general/W、BodyRaise、active C1 两 cut 的完整最终后继。 |
| E | `test_execution_await_resume::test_two_same_code_creates_do_not_select_the_other_body_origin` 和 `test_repeated_root_evaluation_never_borrows_a_sibling_body_activation`。 | 各来源 direct/await 最终值/异常、过期 current-state 的整链对照。 |
| F | `test_program_await_wrapper::test_native_wrapper_has_real_constructor_getter_and_nested_driver_ports`；`test_execution_await_wrapper::test_explicit_native_wrapper_routes_distinct_w_to_held_b_without_copy_union`。 | W 多 cut→BodyReturn/BodyRaise→构造/提取 N/R→final/C1。 |
| G | `test_program_await_cases::test_same_iterator_in_both_arms_preserves_two_whole_case_tuples`；`test_execution_await_cases::test_actual_incoming_selects_one_case_even_when_both_carry_the_same_body`。 | shared caller＋loop incoming＋child 最终提取的同一 whole tuple 及删 stage。 |
| H | `test_execution_await_outcomes::test_budget_one_preserves_original_successor_inventory_and_reports_unchecked_work`；`test_execution_await_outcome_boundaries::test_whole_capture_deletion_keeps_static_outcome_and_failure_keys`。 | 上述剩余整链的 shared budget、删除、fresh/reexecution 与 detach。 |

机器台账保存在本轮 evidence 的 `original-obligations.json`；归档时将每个
selector 与最后 JUnit 的 class/name 精确核对（参数化仅接受原名称加 `[`），
同时保全部旧1551 case identities。该核对只授“此源已执行该用例”，不把每格
缺项改成完成。`closed=[]`，原 F12–F24/X25–X27/P5/M2 113/196 继续保留。

当前完整交付顺序见 [M1_AWAIT_FINAL_CHAIN_PLAN.md](M1_AWAIT_FINAL_CHAIN_PLAN.md)：
先接口 E→内部 F own N/R→准确 terminal→逐 parent result→caller consumer 及
实际 CallActivation，再补原三路/BodyRaise/C1 组合。全部实体、状态及控制边取
原规范 IR，不另建可写 producer 图，不增加优化规则。
