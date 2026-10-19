# Native coroutine：模型连接、真实失败和本门证据

2026-10-19，基线 `f26829c126f519043943af85c0faa62a9c76dd3b`。
[冻结计划](M1_NATIVE_COROUTINE_PLAN.md)范围为原 F14 的五场景。
本门结果为 **VERIFIED_PROGRESS**：1907项受影响相关测试通过，原1890精确身份
保留、新增17，870份源码运行期间稳定。原 F14 条件供应模型结构验收通过，
不是 P4/P5/M2 或整个程序自动建模完成。

## 1. 从模型到实现

核心五实体仍是 Operation / Value / StateLocation / Region / Resource。
新增 `ExecutionIndex.body_state_history(read,budget=4096)`，由原图派生当前
READ 与实际 Drive/终结历史的联系；没有新 canonical phase、identity、schema、
codec、detector、backend 或 LeWM 规则。

| 原模型关系 | 本轮如何连接 |
| --- | --- |
| 一次 Create 与多次执行 | 原 B、BodyActivationOrigin、各 BodyDriveExecution/segment/ResumeIngress 分开；不因同一静态函数就合并动态发生 |
| Running | 本次真实 active Drive entry→inner READ→该 Drive 首 outcome；准确同 B、SENT_VALUE 与完整同步 CallActivation 链 |
| Closed | 本次实际 terminal/BodyOutcomeCommit、原 lifecycle F 来源与固定 native/no-reset scope、同 B 和完整 source/read caller 链 |
| 状态内容 | 独立调用上一门 state_preservation；opaque、未隔离 RW 和缺采继续阻断，不把 F 历史当当前 P/字段内容不变 |
| native self 获取 | 复用原 source-first AwaitBodyLink 投影并核本次 own NORMAL、资格、iterator→本次 Drive；普通 copy 仍 Unknown，另附条件关系收据 |
| 错误与缺采 | 原 Drive/commit/NoBodyFinish 库存先保留，再列实际缺口；预算截断不把已扫描前缀当全量成功 |

Closed 的 F/no-reset 条件来自旧 DriverLifecycle 合同及旧 lifecycle_flow。
LifecycleScope.applicability 仍 UNKNOWN；没有新增“永远稳定”标签。回调之后
历史 bool 可以继续控制原分支，但不自动供应当前 gate 所需的 state snapshot。

新增产品只有 `scar/ir/execution/body_state_history.py`；旧 `query.py` 仅加只读
入口和 FK 检查。新共享 capture fixture 按当前图重建实例、调用与各次恢复，
是测试工具，不是自动源码 lowering 或真实 profiler。

## 2. 实际首红、修复和复测

所有 Python/pytest/probe 由 root 串行执行，源码作者先明确冻结；协作者只写
隔离新文件和做只读审查。旧 tests/fixtures/合同/codec 均不修改。

| attempt | 实际结果 | 原因与处理 |
| --- | --- | --- |
| first-authored | 12 fail /3 pass | 新 Running 图 Region.parent 错；Closed 缺 native 来源桥；packet 新 helper 返回类型/错误码定位与 capture literal 去重未重绑 Use 等问题。保首红，修新供图/工具，不改旧断言 |
| authored-fixture-repairs | 6 fail /9 pass | 全部新图和捕获结构有效；Running4/Closed2 仍因 native Get 的普通 copy 未知而缺条件来源桥 |
| conditional-native-source-bridge | 15 pass | 复用原 source-first 投影；没有把 Get 标 pure 或合并 B/iterator identity |
| original-capture-gap-counterexamples | 2 fail | 独立审查补具体缺采：missing raw Use 仍错误期望 True；missing source gate transfer 的全局期望已 Unknown，但 source_chain 仍错误标完整 |
| repaired-original-capture-ports | 17 pass | 所有 owned Uses/landing/state 口、source Drive caller 链、原 structural gaps 及准确 entry→completion 路径纳入支持条件；23.91s pytest /24.69885187409818s wrapper |
| verified-final | 1907 pass | 原1890精确身份全部保留、新增17；744.67s pytest /745.7452823938802s wrapper；870稳定源码 |

第一个 probe 在第二次 attempt 的准确源码上重现：Drive 的 active 区间和 inner
调用已完整，但普通 creation/body binding 未建立；原 await 投影则有独立选择、
资格和来源证据。第二个 probe 在15绿版本重现上述两项缺采错误，随后先加
两个真实失败用例再修产品。全17身份包含原15，没有用替换测试掩盖失败。

每次运行前保相对原862源码发生差异的全部准确文本；每次 command、log、
JUnit、前后源清单、result 和两次 probe 原结果均保留在
`artifacts/experiments/b1_call_operands/model_native_coroutine_connections/`。
probe 原 shell 命令未单独收据化，脚本、结果和其对应 attempt 的准确源快照
保留；不把后补的复现命令冒充原执行记录。

这些数字是测试运行结果和测试耗时，不是 LeWM wall-clock 或加速比。

## 3. 三方审查与原条款

审查分别负责 Running、Closed/callback、THROW/CLOSE，另交叉只读核产品。
最终均冻结：普通 False 不被条件投影覆盖；普通 Unknown 旁保条件收据；完整
原端口与调用路径缺采不能授 True；F 的条件合同不扩展成 P/内容保持。

原 F14 五主场景、既有 native self 零 cut/wrapper 两 cut 等具体证据逐条见
[原条款验收](M1_NATIVE_COROUTINE_ACCEPTANCE.md)，机器 acceptance 从最终
green JUnit 逐 selector 重算。不是17绿就自动关闭整个家族或程序模型。

共享预算覆盖实际派生 copy、path 和 projection 工作；部分原库存/FK 扫描
仍按图大小执行。因此不声称总 CPU 成本严格由 budget 参数限制。

## 4. 验收边界与下一步

最终 source 指纹：
`07028c2c92e5e915ae9e7ac9877331790ca46d9a938a2c71a8a4bb63e1680e4f`。
运行前后指纹相同；checkpoint 单独重算1907准确 JUnit 身份、全部原1890子集、
新例5/6/6分账，以及所有原条款的非空 green selector 匹配。旧源码只允许
query.py 入口变化，全部旧 tests/fixtures/codec 字节守恒；失败 attempt 则核
各自执行前的准确 source-bytes。原16族、A–H、P5、M2 原113构造/196字段
分母不变。checker 不启动测试；版本由包含本报告的 commit 标识并核远端 SHA。

原 F14 在独立条款审计、最终同源相关回归与归档核验范围内接受；既有六族和
A–H保留，其余九族保持OPEN。本门未运行完整组件或冻结全仓，不能以1907
相关通过替代它们。F16旧remaining文字保留为历史输入，并另列已覆盖的
sameR两调用/scheduler packet和实际未完成项，不重做已验证关系。

| 状态 | 本轮含义 |
| --- | --- |
| Observed | 供应模型上的真实失败、条件查询和回归；不是自动采到的 LeWM 图 |
| Implemented | body_state_history、原 native 投影复用、完整原输入/调用路径支持检查 |
| Verified | 原F14五主场景/反例、最终1907受影响相关回归、原1890身份守恒及独立源码审查 |
| Rejected | 缺原 Use/路径/association、错当前包、旧 snapshot 或预算截断不能获完整支持 |
| Inferred | 没有凭 bool、类型、函数名或相同地址建立来源/纯性 |
| Proposed | 下一有限门 R1/R2 竞争及初始 ASEND 联合控制，不算本门已实现 |

下一步见 [原剩余门](M1_NATIVE_COROUTINE_NEXT_GATE.md)：F16 已有的同 R 两次调用
和三次 stepping 不重做；四个真实内容 blocker 保留，缺的竞争/Created入口
关系分别实现。其余九族及 P4 组件/冻结全仓、P5/M2 仍须各自验收。

自动完整 LeWM 拆解建图、可信 TRANSFORM 和新的 clean A/B 加速比尚未建立。
原 LeWM 与原 SCAR checkout 保持保护。M0–M2 真齐后先按用户要求讲解模型。
