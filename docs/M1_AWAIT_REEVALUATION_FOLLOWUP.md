# N4后续：按原义务关账，再进入总模型验收

2026-10-19。本文件是只读审查与后续任务，不是新的范围冻结或通过证明。
本轮计划/结果见[M1_AWAIT_REEVALUATION_PLAN](M1_AWAIT_REEVALUATION_PLAN.md)与
[验收记录](M1_AWAIT_REEVALUATION_PROGRESS.md)。不能继续用新增局部图数量
代替整个程序的建模完成度。

## 1. E/H已按原条款关账，不重写helper

直接回到原[M1_AWAIT_ACQUISITION_PLAN](M1_AWAIT_ACQUISITION_PLAN.md)及
[M1_AWAIT_COMPOSITION_PLAN](M1_AWAIT_COMPOSITION_PLAN.md)第2节。原E要求
同generator-coroutine的direct/await、准确持续B、多Create及旧Resume/Drive/
current state拒错；原H要求共享预算、原分母与cursor、reexecution/fresh与
detach。它们不是所有source、cut、缺采、cleanup的任意笛卡尔积。

本轮回归后已完成“原条款→准确selector→本轮同源JUnit identity→判定”，
见[原范围验收](M1_AWAIT_ORIGINAL_SCOPE_ACCEPTANCE.md)。root裁定：native/self
其他来源、资格或失败义务归各自原A/D/F/F12/F14，不扩成E/H的新门槛。
原E/H模型条件结构行已关闭；下表保留所用证据入口，不再作为新一轮待查门。
M1声明边界缺失仍应在M1修，不能挪给采集。

| 已合账内容 | 已核已有入口（tests/unit/） |
| --- | --- |
| 一持续B的direct/await、零/两cut | test_execution_await_resume::test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction；本轮pipeline self两cut仍保direct NEXT→await SEND×2。 |
| 多Create与旧Resume/Drive | 同文件test_two_same_code_creates_do_not_select_the_other_body_origin、test_old_cut_cannot_be_used_as_the_second_resume_ingress、test_same_body_does_not_allow_another_drive_entry_and_outcome。 |
| 当前state、共享incoming旧值 | 原program_shared_final的test_pre_get_state_is_a_core_stale_state_error_not_a_protocol_gap、execution_shared_final的current merge/source反例；不能拿类型不同替代旧值反例。 |
| 真同caller两轮与同B双Get | 本轮source_visits及pipeline_reexecution的新38项；两种拓扑不能彼此替代。 |
| budget1、原N/R/outcome分母与实际半成本cut | 原execution_outcome_boundaries/shared_final；本轮source_visits两个budget/detach项和pipeline固定1/128项。 |
| 全capture缺失、snapshot、fresh/detach | 原execution_outcome_boundaries::test_whole_capture_deletion_keeps_static_outcome_and_failure_keys、shared_final::test_whole_capture_deletion_preserves_static_keys_without_fabricated_pairs、test_fresh_external_context_rechecks_the_actual_source_copy_after_the_loop，以及原snapshot/copy合同测试。 |

上表与机器审计核定原E/H，不新建“同一图换一个标签”的重复helper。剩余
条款若有缺口，只列其原要求和实际失败/缺selector；先最小实验，再决定是否
修产品。预算不要求穷举每个整数cut；截断不能抹掉已证矛盾，未查工作不能
捏造True或False。

## 2. 原十六家族保持分母

E/G/H与F17/F21/F23已通过各自原M1结构验收，不因未有自动采集而重开。其余十三
组仍为F12/F13/F14/F15/F16/F18/F19/F20/F22/F24/X25/X26/X27；逐原
[M1_REMAINING_PROTOCOL_PLAN](M1_REMAINING_PROTOCOL_PLAN.md)及
[范围合账](M1_PROTOCOL_SCOPE_RECONCILIATION.md)记录已有准确selectors。

F15已收敛到两个准确反例：ordinary GENERATOR不能获得direct/self await
资格，以及另一Drive的adapter结果不能替代当前final结果。主链和旧state
已有证据；不拿反向general资格或错误O关联冒充这两个缺项。

顺序：逐原合账→仅补真实缺口→受影响同源回归→逐家族报告→原P5组件与
冻结全仓验收。不要为通过一个局部例反复运行全部测试；也不能把旧源码的
full或本轮1845项定向称作当前源码的全仓通过。原C1、其他协议、状态/资源及
native边界仍各有自己的义务，不能由await矩阵代验。

## 3. 总模型与自动建图分开验收

M2仍是原113构造/196字段分解合同。逐条解释怎样映射到Operation、有序Use、
Value、StateLocation、Region、Resource、控制/完成和effect接口；导入、模型
文件读取、参数初始化、推理、环境交互、视频编码/文件写均必须有位置。
UNKNOWN表示具体知识/证据缺口，不意味着代码可以不进入模型。

M0–M2真正齐备后，按用户要求先停下来讲解模型、范围与限制。然后才进入
原M3自动source/provider lowering和M4真实execution对应：从真实程序入口
建立规范图，复用既有FX/Export/profiler等能力，跨package/call/break连接，
恢复数据/状态/资源来源并显示未覆盖边界。真实LeWM是外部testcase；手写其
特殊规则或供应几张图不构成自动拆解。工具适用性须按本机版本核验，不以
展示图、profiler事件或Tensor样本相同授化简合法性。

本轮不开始这些后续实现，不新增backend/detector，不授LeWM优化或加速结论。
后续仍由root自主验收、归档、commit/push，不等待用户逐门确认。
