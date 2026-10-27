# 当前对象身份与历史 F：限定验收

2026-10-20。基线 `0bf37d2a422f51eec2955fb44611760ef75d868e`。
范围依[冻结计划](M1_FRAME_IDENTITY_GUARD_PLAN.md)，接口见
[API](M1_FRAME_IDENTITY_GUARD_API.md)，原始过程见[进展](M1_FRAME_IDENTITY_GUARD_PROGRESS.md)。

## 1. 本批回答什么

**Implemented：** 新公开 `ExecutionIndex.object_identity` 比较两个准确 Reference
occurrence 的独立、scoped ObjectIdentity 声明。它与 ordinary copy 分开，并接入
已有 `body_state_history`；没有新核心实体、全局 copy union 或新 wire/schema。
五类实体仍是 Operation / Value / StateLocation / Region / Resource。

**Observed：** 基线供采图中目标实例的实际 terminal、ports、call chains 和 host
顺序已完整；普通 copy 不足以连接 creation handle、Drive owner 与当前 READ B。
诊断预算 4505/1048576 未截断，observed branch True、expected None；没有运行
native target 或 LeWM。这些是供采图的查询结果，不是原程序实际身份采集。

**Verified（条件性供采范围）：** 两端同实际 process/run、同精确 artifact
namespace、目录中注册的同 ObjectID 可提供独立的 same-object 依据。当前 frame
仍需自己的 Create/Drive/READ 端口、真实 terminal、当前状态及 no-reset/host-order
支持。声明 basis 未解仍保留；所有 source/native/runtime/value identity 与变换
授权标志为 False。最终 231 项直接相关选集通过；完整结果以本文件第 2 节与
checkpoint 为准。

**Rejected：** 用 RequestAssociation 或 host 顺序假设创建后字段不变；把同对象
当数据版本不变；从 observed bool 猜来源；借兄弟实例；缺端口时以身份补采；
把不同候选的正常不相等写成全局 copy 冲突。原无 denotation 的旧 fixture 保持 None。

## 2. 实际执行与证据

归档：`artifacts/experiments/b1_call_operands/model_async_request_body_history/`。
各 attempt 保存原命令、环境、源码指纹前后、变更源码字节、stdout/stderr、JUnit
与结果；失败没有被后续绿测覆盖。

| Attempt | 实际结果 | 解释 |
| --- | --- | --- |
| current-object-history-counterexample | 1 FAIL，7.62 秒 | 程序/capture 校验通过，真实语义断言 expected None 与条件性预期 True 不符。 |
| first-joint-identity | 12 PASS / 1 FAIL，127.58 秒 | 身份主链及反例已通过；WRITE fixture 错误声称完整 alias effects，在构造校验时被拒，未到实际反例。 |
| corrected-write-and-value-catalog | 2 PASS，16.39 秒 | 修为 effects_complete=False；实际 B2 读取不借 B1 历史，ValueGraph 扫描预算分支通过。 |
| verified-current | 231 PASS，342.58 秒 pytest / 343.4434034684673 秒 wrapper | 23 个模块，保留上批全部 196 项；不计作全仓或整个阶段验收。 |

最终作者冻结为 907 源文件，指纹
`b7a6ad77e48d49e7055e588b75e5d9f4380a8023339f98bfc396b113054fb3aa`。
相对基线只改两个既有产品文件，新增通用 identity helper、一个 fixture 和一个
测试模块。既有 tests/fixtures 字节保持原样；Program26 / Execution8 不变。
独立只读复审覆盖最终五文件，未发现阻塞；不代替实际测试或 native 证明。

原已知目录合计 2121 个 case 身份，本次只重跑直接受影响的选集，未重跑全部目录。
最终 231 项含 217 个既有身份和 14 个新身份；全部 196 个上批直接项均在其中。
这不是对当前版本全仓测试通过的声明。checkpoint 逐项核验原 test/fixture 字节、
旧 case 身份集合、最终源码、独立审查 SHA、各首败及受保护工作树。

## 3. 有区分力的结果与限制

- 两个完整实例各自支持历史 F；ordinary copy 仍 None，mutable content preservation
  仍 None 且保留 blockers，native lifecycle applicability 仍 UNKNOWN。
- 同一个 R 有真实字段 WRITE，当前 READ 独立声明指向 B2：不能沿用 B1 的历史 F；
  第二实例不被污染。该反例验证声明级推导，不声称自动从该 WRITE 恢复了 READ 值。
- 缺当前 READ 身份/Use/state、Create 输入或 Drive 输入，不能借完整兄弟翻 True。
- 同 namespace 不同对象为局部 False，跨 artifact 同名 ID 为 None；缺目录刷新为
  None，已供图的 hash/bytes 矛盾仍由原 fresh snapshot 校验拒绝。
- budget=1 保留两端和全部原历史源；ValueGraph 的 100 个前置 bindings 受共享预算
  约束，固定预算 16 截断不留 True 前缀。
- 删 RequestAssociation 会失去 R 的来源依据，但不能抹掉独立当前 B 身份支持的
  B 历史；删 BodyStateCondition 不能继续推这个历史谓词。原源库存不缩减。

## 4. 未关闭范围

**Proposed：** [下一门](M1_FRAME_IDENTITY_GUARD_NEXT_GATE.md)先核已有合同是否足以
表达通用 store payload → state version → load result，再决定最小接口；不能把
当前声明身份改称自动 stored-reference 来源恢复。

九族限定接受、七族 F19/F20/F22/F24/X25/X26/X27 开放的原分母保持；await A–H
不重开。F19 第 1 项、非 finished 分支、graceful close、illegal yield 后续、
P4 component/full、P5、M2 原 113 构造/196 字段、完整第一阶段均未完成。

没有新 detector/backend、可信自动 TRANSFORM、LeWM-specific 规则或新的 LeWM
profiling/A/B。这里没有可报告的新 LeWM 加速比，也不能把 pytest 耗时当性能结果。
受保护的 `/home/zyf/AAA/le-wm` 和 `/home/zyf/AAA/scar` 原工作树须维持原 HEAD/clean。
