# 原状态事实到当前读取：实际进度与验收

2026-10-19。基线 `fa7b769e34adf5ef39c27103c11b6cb75f796f7b`。
[冻结计划](M1_STATE_FACT_CONTINUATION_PLAN.md)的有限状态连接门；不是完整建模、
自动源码恢复、LeWM 优化或性能报告。结果为 **VERIFIED_PROGRESS**：1890 项
受影响相关测试通过，原1865精确身份全部保留，新增25；862份源码运行期间稳定。

## 1. 模型落实到代码

Operation / Value / StateLocation / Region / Resource 五类实体不变。
没有新增 canonical identity、状态副本、schema、codec、detector 或 backend。

| 新派生查询 | 作用 | 不代表什么 |
| --- | --- | --- |
| `ExecutionIndex.state_preservation(start,end,locations=...)` | 从准确 AFTER/实际 EDGE 到准确 BEFORE，逐原操作、实际调用、N/R 全部状态端口和所选 transfer 列出内容保持证据与阻断 | 相同 SSA 版本或 Location 名称不等于内容保持或隔离 |
| `ExecutionIndex.request_state_history(readOccurrence)` | 枚举原 SessionUpdate/实际发生，核原输入、post/support、同 R、区间保持，再核当前 READ 自己的 bool/branch | 当前分支选 True 不建立历史 post；完成 post 不等于输出值、native phase 或变换权限 |

实现仅新增 `scar/ir/execution/state_preservation.py` 和
`request_state_history.py`，在旧 `query.py` 增加两个只读入口。
输入、状态、效果和调用全部指向原图，不另存影子程序。

原 `SessionPublication.support` 全部域与 READ 全部实际 StateAccess 域取并集。
不取交集，不丢辅助 READ，不凭不同 LocationID、field 名或地址描述宣称无别名。
outer effects 不完整与 child 不完整独立阻断。WRITE/RW 未证明隔离就保未知。
缺捕获不是 False，输出不能补缺失的原输入，partial 前缀不充当完整区间。

## 2. 真实发现、首红和修复

全部 Python/pytest 由 root 串行运行；每次运行前作者冻结。协作者仅写其唯一
新文件或只读复核，没有执行解释器/Git。旧测试、fixture、codec 均保留。

| 归档 attempt | 实际结果 | 原因和处理 |
| --- | --- | --- |
| `first-unwired` | 22 fail | 14 个新 generic 测试的 None 引用构造违反旧字面量约束；8 个 history 例尚未接公共入口。只修新测试构图并接入口 |
| `first-wired` | 20 pass / 2 fail | 两组新测试对 blocker.operation 的 ID/对象返回类型理解不一致 |
| `corrected-blocker-ports` | 18 pass / 4 fail | 首次对象化修复使另一组 ID 断言失败；随后统一 operation=原 OccurrenceID、occurrence=原对象、operation_id=同 ID |
| `normalized-blocker-receipts` | 22 pass | 原两组新测试均过；尚未覆盖随后独立审查发现的缺口 |
| `source-input-gap-counterexamples` | 7 pass / 3 fail | AFTER/NORMAL post 缺原 state input 仍被建立；预算1漏列辅助 READ 域。先留实际首红，再修全部 publication.state_inputs/current BEFORE 和原域库存 |
| `missing-branch-transfer-counterexample` | exit4 / 0 tests | root 拼错 selector；保命令和 stderr，不记为产品反例或成功证据 |
| `selected-missing-branch-transfer` | 1 fail | 缺 child 分支 transfer 后清空坐标再 unwind，触发 TypeError；保原 visit，再记录不完整的准确 parent 边界 |
| `repaired-original-ports` | 25 pass | 15 generic +10 history，3.32s pytest /4.05705342721194s wrapper，862 稳定源码 |
| `verified-final` | 1890 pass | 原1865精确身份全部保留，新增25；715.48s pytest /716.5066839372739s wrapper；862稳定源码 |

所有 attempt 独立目录保 commands/logs/JUnit、前后源码清单和 result；runner
在执行之前保存相对原858源码发生差异的全部准确文本，不靠事后猜测失败版本。
零测试选择错误也保留。归档位于
`artifacts/experiments/b1_call_operands/model_state_fact_continuations/`。

这几秒/最终相关回归用时是测试耗时，不是 LeWM 性能数据或加速比。

## 3. 原 R3 为什么仍不能推出 True

首个 COMPLETE post 确有准确来源，第二次 READ 使用同 R；这些单独可以证明。
但以下原始中间操作仍阻断内容保持，N/R 两个旧例都要求具体列出：

1. `adapter.construct`：primitive INVOKE，原 effects 不完整。
2. 首次 host terminal：原 effects 不完整。
3. caller 的 `request.first_completion.context`：WHOLE context RW，没有独立隔离。
4. 第二 driver 的 association READ：primitive INVOKE，原 effects 不完整，也无 callee 可臆造。

没有把它们标 pure、移动 post 或改旧 fixture。其正确返回是
`post_established=True`、`subject_binding.match=True`、
`preservation.preserved=None`、`expected_bool=None`；观察到的分支 True 独立保存。
这些是原供图中具体的缺失效果证明，不是“模型无法装下该操作”。

另外独立的完整效果图有正例：真实 world post 与辅助 context READ 均保留，
准确状态端口和区间都齐备时，原 COMPLETE→IS_COMPLETE 合同可条件地推出 True。
它不伪装成修好了 R3，也不授 SessionUpdate 的 native implementation 权限。

## 4. 自主验收

| 节点 | 当前状态与证据 |
| --- | --- |
| H0 | 三方原合同/别名/效果/调用审查，冻结计划；旧图与全部原分母保留 |
| H1 | generic 正例 N/R 全 slot，准确 entry/completion/selected transfer；25 新例已通过 |
| H2 | outer/child 独立、同域/异 Location 写、实例局部缺采与缺 child transfer；完整 sibling 仍能通过 |
| H3 | 原 R3 四阻断、独立 COMPLETE 正例、NORMAL/RAISE、错 R、缺 source 和 AFTER/NORMAL 缺 input |
| H4 | budget1/中段截断保库存与 cursor，拒绝成功前缀；最终1890相关回归与单独XML核验确认原1865精确身份全部保留 |
| H5 | 最终源码独立复核冻结；source-bound checkpoint核档、不启动测试；版本由包含本报告的commit标识，root随后串行提交、推送并核远端SHA |

最终候选源码指纹：
`7507b89dc06ee215386c67e3ecb25ff369e7f78dc2ae352e8810d0fc443b3701`。
运行前后指纹一致，单独核验的测试身份与当前源码也一致。机器收据见同门
`checkpoint.json`；`checkpoint.py --check`只核已有来源，不执行测试。

| 状态 | 本门含义 |
| --- | --- |
| Observed | 供图/供采上的实际首红、回归与准确原端口；不是自动采到的LeWM运行 |
| Implemented | 两个复用原IR的派生只读查询与公共入口 |
| Verified | 本有限门25新例、原1865身份及最终1890受影响回归；并非组件/全仓总验收 |
| Rejected | 缺输入、未知效果、未隔离写、缺路或预算截断不得取得内容保持；原R3仍保未知 |
| Proposed | 下一门五个native场景及独立body-phase关联，尚未实现 |
| Inferred | 不从bool、相同Location或同类型对象新增事实 |

## 5. 完成边界与下一步

本门新增的是状态事实连接能力。F14/F16 不在本门关账。此前 A–H 和
F12/F13/F15/F17/F21/F23 的条件结构验收保留；其余十族、P4 组件/冻结全仓、
P5、M2 原113构造/196字段继续开放。下一步见
[原残项审查](M1_STATE_FACT_NEXT_GATE.md)。

自动从整个 LeWM 恢复该图、实际 native 对应、可信变换和新的加速比尚未验证。
原 LeWM 和原 SCAR checkout 未修改。
