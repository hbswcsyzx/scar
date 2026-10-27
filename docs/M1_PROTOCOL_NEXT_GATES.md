# 原协议剩余项：下一组有限自验节点

2026-10-19。原 G 共享整链最终1780定向回归通过，原1747 identities保留，
此 M1 条件结构格关闭。
本计划承接原十六组、P5、M2，保原验收分母；不新建 backend/detector 或运行
LeWM/GPU profiling。五实体与规范图、执行发生、条件合同、优化权限继续分离。

## 1. 先合账，再补具体缺项

本轮三路只读审查按原 FAMILY_PLAN / REMAINING_PROTOCOL_PLAN 将现有 selectors
与原条目对齐。已核的声明结构应计入 M1；没有自动 collector 不会撤销它。
源码/运行适用旗标不单独阻止结构验收；确实没有连接或反例则不能拿旗标代替。
当前 G 不代替下表任何整族，下一门仍逐原要求自行验收并出报告。

| 节点 | 有限工作 | 自验条件 |
| --- | --- | --- |
| N1 / F17 | 复用现三 Drive、同 request/body 的 async pipeline，补准确旧同型 item/adapter packet 的反例。 | core 图与捕获均先合法；当前 ASYNC_YIELD/request 完成不能重放仍可引用的旧 item/packet。既有 AWAIT/current session、HOLD/COMPLETE、body 暂停与删除/预算/刷新证据合账；缺项全齐才关 F17。 |
| N2 / F21 | 补 SEND(None)→NEXT 与 nonNone 不丢原参数；调用自身 RAISE 的原包传播；delegate item 冒充最终表达式值。 | next/send 的真实 lookup/call/state、item/final 已有 selector 必须保留。调用自身 RAISE 与完成提取器自身 RAISE 分开。三个有限缺项先真实首红或已正确拒绝，再决定改公共 resolver。 |
| N3 / F23 | 整个 DELEGATE_CLOSE 可选附件删除后保两腿 C1 原义务；delegate-close 的准确发生整链/同实例缺采与 X27 合账。 | 原注入包、own 新异常、父 pending/context、最终 consumer 不混；原本无 body 的 delegate-only 不伪造父 Drive/Attach。有实际 BodyDrive 才关联其 activation/ingress/outcome。静态四原条目已核，不重写已有 C1 helper。 |
| N4 | 原 E/H 整条 pipeline 重求值与同 B 多次获取来源；其余 F12–F24/X25–X27 真正残项。 | 来源由原端口与确切发生链选择，不按同 root/相同内容/唯一可见 body/最新时间猜。各自完整原矩阵保留；原始执行和具体未知边界始终存在。 |
| N5 | 十六组齐全后组件与冻结全仓、P5、M2 原113构造/196字段总核。 | 不用供应图宣布任意源码已自动建图；M0–M2 真齐后按用户要求先停下解释模型。 |

N1–N3 不要求新的 wire；如果真实首红显示规范关系无法表达，先记录具体原端口
缺口，再审查是否需扩型。不得为同型负例制造不支配引用或过期 State SSA，
然后把 core 拒绝伪报为新的协议查询能力。

## 2. F21 的既有结构与准确欠项

只读依据原 FAMILY_PLAN 第 F21 行及 REMAINING_PROTOCOL_PLAN 对应行。
相关整文件已在当前 affected selection；最终实际通过情况由本轮 JUnit 核。

| 原关系 | 现有精确 tests/unit/ 入口 |
| --- | --- |
| NEXT/SEND lookup own N bound method → call receiver；lookup R/state | test_program_method_lookup_connections::test_method_own_normal_result_is_the_real_callable_receiver（next/send、formal/ContractResult 两种）；test_same_type_or_completion_substitutions_do_not_choose_the_expected_lookup_from_actual |
| SEND ordered ordinal、whole tuple/branch、错 state | test_program_continuation_connections::test_two_lookup_request_tuples_merge_upstream_of_the_real_send_call；test_receiver_and_send_operand_cannot_come_from_opposite_merge_predecessors；test_item_exhaustion_packet_and_state_are_not_interchangeable_metadata |
| 独立 method sources 与 crossed 拒绝 | test_program_method_lookup_connections::test_independent_lookups_on_real_branches_keep_method_receiver_and_raw_operand_paired；test_crossed_same_kind_method_sources_from_opposite_branch_are_rejected |
| item/exhaustion、提取 own N/R | test_program_continuation_connections::test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct（next/send-delegate） |
| lookup 重求值当前性、删除、预算 | test_program_method_lookup_connections::test_reexecuted_lookup_cannot_use_last_iteration_bound_method；test_deleting_method_inputs_or_consumer_targets_keeps_the_known_lookup_obligations；test_program_continuation_connections::test_deleting_the_paired_call_attachment_keeps_both_selected_call_rows_required；test_tiny_shared_budget_retains_unchecked_sites_and_resume_slot_denominators |

三个有限欠项不能互相冒充：现 next/send 主图 exhaustion=True，其 extractor
自身 RAISE 不是 advance 自身异常；AWAIT 的 iterator-as-expression 负例不是
delegate item 的专属反例。SEND(None) 分流已有产品条件，但缺精确族内 selector。
缺采是 X27 的交叉要求，不额外无限扩张 F21。

## 3. F23 的既有结构与准确欠项

| 原关系 | 现有精确 tests/unit/ 入口 |
| --- | --- |
| close N 延续原注入、R own 新包覆盖 | test_program_continuation_connections::test_close_normal_continues_old_injection_but_raise_overrides_with_own_packet；test_shared_cleanup_pending_cannot_use_close_none_or_lose_the_new_close_exception |
| C1 真终点、两 cut、pending/context | test_program_packet_continuations::test_close_selected_normal_and_raise_continue_through_real_c1_to_the_host_packet；test_program_continuation_connections::test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace |
| 不统一 Attach，恢复后当前 state | test_program_continuation_connections::test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct；test_resumption_cleanup::test_resumed_cleanup_invoke_normal_resumes_and_new_raise_replaces_pending；test_resumed_cleanup_invoke_rejects_old_pre_attach_or_pre_failure_states |
| opaque 与截断 | test_program_packet_continuations::test_close_route_does_not_stop_successfully_at_c1_before_a_later_opaque_operation；test_a_truncated_full_continuation_retains_a_cursor_and_cannot_close_its_consumer_inventory；test_program_packet_continuation_edges::test_known_packet_helper_copy_does_not_hide_an_opaque_operation_inside_the_callee |

原 F23 四条静态条件结构已经有直接正反支持；不能又称未建模。尚未映到
delegate-close 专属动态整链及整附件删除的两个精确交叉证据。现 close lookup
fallback 删除测试只证明其自身分母，不自动填整 close/C1 删除义务。

## 4. 执行与版本

每个有限节点先确定原图和拒绝条件，作者只读/新文件职责明确；作者冻结后由
root 串行运行解释器。首红、作者 oracle 错误与产品缺陷分账。修复只针对真实
公共关系；一次最终定向保本轮所有已核 testcase identities/原 fixture 字节。
实际充分验证后归档、checkpoint、commit/push/远端精确SHA，自主进入下一节点。
尚未实现的项目留具体残项，不因临近结束或测试数增长而宣告整个阶段完成。
