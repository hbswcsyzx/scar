# Native coroutine：原 F14 结构验收

2026-10-19。原要求为 `M1_PROTOCOL_FAMILY_PLAN.md` 中 F14：
“coroutine 重入、重复使用、throw/close 与各自实际失败后态”。
具体五场景来自上一门冻结的 `M1_STATE_FACT_NEXT_GATE.md` 第2节。
本门计划为 [M1_NATIVE_COROUTINE_PLAN.md](M1_NATIVE_COROUTINE_PLAN.md)。

## 1. 验收方法

root 与独立只读审查逐原条款核对供图、捕获与断言，再核最终同源相关回归。
家族结构验收不等于 source lowering、native runtime 适用性或优化许可。
测试图通过并不能证明 SCAR 已从任意 Python 源码自动恢复这些关系。
具体运行结果见 [本门报告](M1_NATIVE_COROUTINE_PROGRESS.md)，机器清单位于
`artifacts/experiments/b1_call_operands/model_native_coroutine_connections/`。

## 2. 原条款对应关系

| 原范围 | 对应证据和拒绝边界 |
| --- | --- |
| Running 重入 | `test_execution_coroutine_running`：同一次 Create/B、三次真实 Drive、两次 AWAIT；第二 SEND 经 normalizer own NORMAL→SENT_VALUE→inner READ，拒绝后真实处理 context/handler 再暂停，第三 Drive 真正终结。缺 inner CallActivation、当前 sent Use 或当前 raw Use，均不能借完整兄弟实例。 |
| 完成后同 B reuse | `test_execution_coroutine_closed::test_completed_native_same_body_reuse_has_history_and_its_own_rejection_packet`：NEXT/extractor NORMAL/reject NORMAL 与 SEND(None)/extractor RAISE/reject RAISE；只有一个 Create 和一次实际 BodyDrive。真实 terminal/commit 之后准确 forward B、当前全状态，拒绝结果来自本次 helper。缺 retry CallActivation 或原 source gate transfer 不授完整支持。 |
| Suspended THROW | `test_execution_coroutine_packets::test_native_suspended_packets_follow_their_exact_normalizer_and_body_ports` 的 throw 参数：两次真实 AWAIT；本次 normalizer own NORMAL 的包进入第二 cut 的独立 THROWN_PACKET，真实 body RAISE 到当前 host；own RAISE 是 helper 自己的包和后态，不进入 body。 |
| Suspended CLOSE | 同测试的 close 参数：独立当前 CLOSE 包、同样准确的 ResumeIngress；body RETURN 及 CLOSE_RETURN_VALUE adapter 保留自身语义，helper RAISE 无假 Drive。独立同型旧包及删除原 source binding 均保留拒绝/缺口。 |
| callback 历史谓词 | `test_execution_coroutine_closed::test_native_historical_phase_bool_does_not_supply_the_current_gate_snapshot`：历史 bool 控制原 branch 仍合法；callback NORMAL 后 gate 使用新状态，历史 READ 不供当前 snapshot。callback RAISE 保自己的 packet/fullstate，且无假 body activation/Drive。 |

这些 selector 的实际参数、运行身份及是否 green 由 checkpoint 从最终 JUnit
重算；不是仅凭文件名或测试总数判定通过。原17个新增身份全部保留。

## 3. 既有原证据保持

native self/no wrapper 零 cut 的真实供图终结链，以及 native wrapper 的两实例、
两 cut、own NORMAL/RAISE、W≠B、decoy、缺采、旧状态和预算证据，沿用原
`test_program_await_native_and_general_sources`、`test_program_await_wrapper_final`
和 `test_execution_await_wrapper_final` 的既有 selector。它们在最终相关回归中
重核，不能以本轮新图替换原验收，也不重新扩成所有参数的笛卡尔积。

## 4. 模型条件与验收边界

Running 来自本次 Drive entry→READ→首 outcome 的准确区间和同 B/完整调用链。
Closed 来自真实终结及原 DriverLifecycle 的 fixed-native/no-reset 条件；原
LifecycleScope.applicability 仍是 UNKNOWN。普通 state content preservation
独立列出，遇 opaque/write/缺采仍未知。不能把 F 历史的合同扩成 request P
或任意字段的内容保持。

native self 获取关系复用原 source-first AwaitBodyLink 派生投影。它产生独立
条件收据，普通 identity/copy 仍可 UNKNOWN；不合并 ID、不覆盖已知 False，
不把 NativeGet 改成 pure。所有 runtime/identity/transform 授权仍为 False。

最终1907相关测试通过，全部原1890精确身份保留；870源码前后指纹一致。
checkpoint逐条重算green selector及历史字节。F14仅在上述原供应模型结构范围内接受。
原 A–H 和六个已接受家族保留；其余 F16/F18/F19/F20/F22/F24/X25/X26/X27、
P4 完整组件及冻结全仓、P5、M2 原113构造/196字段保持各自未完成项。
自动完整 LeWM 建图、可信变换和新加速比没有因此建立。
