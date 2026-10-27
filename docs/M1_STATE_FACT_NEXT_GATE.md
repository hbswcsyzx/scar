# 状态连接之后：原 F14/F16 的有限后续

2026-10-19，只读源码审查与下一步规划；没有新增运行或家族关账。
[本门冻结计划](M1_STATE_FACT_CONTINUATION_PLAN.md)与
[实际结果](M1_STATE_FACT_CONTINUATION_PROGRESS.md)保留原范围。

## 1. 当前能力的准确边界

`state_preservation` 提供原区间的效果、全状态端口与缺采证据；它不发明事实。
`request_state_history` 只将原 SessionPost.COMPLETE 条件地连接到
RequestStateCondition.IS_COMPLETE。BodyStateCondition.IS_CLOSED/IS_RUNNING
不是它的同义词。`admission.py` 仍区分历史 READ 快照与当前 gate 资格。

因此下一步先组合现有记录和准确供采路径，若需要再补 body-phase 的派生
关联。不能新增可写 phase、用捕获的 True 反推事实、假设 native contract
已经实现，或重建另一套状态。只有具体原端口确实无法表达时才讨论 schema。
当前只读审查没有找到 schema 阻断。

## 2. 下一有限门：native coroutine 五个主场景

| 主场景 | 最小原关系 | 验收与失败边界 |
| --- | --- | --- |
| Running 重入 | 一次 Create 的 B→多次真实 Drive；当前 SEND 的 operand0 从 caller 经 CHECK_SEND own NORMAL→SENT_VALUE ingress→B 内部 inner driver | READ 位于当前 Drive entry 之后、该 Drive 首 outcome 之前；准确同 B 和 inner CallActivation；拒绝路径不新建 B 或 BodyDrive。错 owner/缺 association 不借前次 Drive |
| 完成后同 B reuse | native 零 cut→真实 Return/commit→转换/提取→独立 forward 同 B→真实 IS_CLOSED READ/branch→本次拒绝 helper | 固定 NEXT/SEND(None) 的重用拒绝；B 在完成用 RAISE landing 及 extractor N/R 都有准确原 forward/full state。不能重 Create B，不能以 request COMPLETE 代替 body terminal |
| Suspended THROW | 当前 raw→本次 normalizer ownN packet→THROWN_PACKET；ownR→自己的 host RAISE tuple | packet 来源、原 ordinal、selected edge 与最新 state 都准确；旧 packet 不能代换 |
| Suspended CLOSE | 同一原接口的当前 CLOSE，保持自己输入、包和异常路线 | 独立核其语义，不套 generator 的 closed 表，也不将完成后的 CLOSE 一律当 reuse 拒绝 |
| callback 后历史 bool | 原 READ→callback WRITE/opaque→原 bool 控制历史分支→当前 native gate | 历史控制仍合法，当前 snapshot 资格保未知；列出 callback/不同 Location RW 阻断，不能用 history True 修补 gate |

只在这些原图内对同 B、错包、当前状态和缺 association 做必要反例，不铺新的
参数笛卡尔积，不借已有 generator 矩阵自动验收 native coroutine。

## 3. 可复用源码位置

- `tests/fixtures/program_await_resume_graphs.py` 的 `_body`、`_stage`、
  `await_resume_program`：三次调用、两 cut、持续 B。当前 factory 是 GENCORO；
  native 迁移须完整采用 `test_program_await_native_and_general_sources.py`
  的 `_native_program` 中 COROUTINE_BODY_V1 与对应 return conversion，不能只改 kind。
- `tests/fixtures/execution_await_resume_graphs.py::await_resume_execution`：
  一 B、三 segments、准确 BodyDriveExecution；inner driver 增加真实 CallActivation。
- `tests/fixtures/program_generator_reentry_graphs.py` 的 `_inner_driver`、
  `_body_with_reentry`：复用 call/handler/context RW 结构，holder heap READ 改为
  原 SENT_VALUE 明确 copy；不能保有条件 heap READ 又宣称同 B 已证。
- `tests/fixtures/program_generator_admission_graphs.py` 的 `_guard`、`_driver`、
  `_later_admission_program` 与原 request processing normalizer：保真实
  READ/bool/branch、ownN/R helper、完整状态 tuple，并采用 native profile。
- `tests/unit/test_program_admission_routes.py` 的历史 READ/callback 负例：
  已有快照规则保留，只补其与真实 native gate 的原关系。
- `scar/ir/program/lifecycle_flow.py` 已有 BodyOutcomeCommit→terminal F；
  `scar/ir/execution/admission.py` 已有快照到 gate 兼容性。它们不由本门
  request COMPLETE 查询取代。

## 4. 有序开发和原分母

1. 先逐原 F14 条款与上述五场景对照，冻结完整输入/出口/状态/控制合同。
2. 最小供图与准确捕获，所有作者冻结后 root 串行首测。结构、实际来源、
   phase 条件与当前值分开列收据；真实失败先归档，再修公共关系。
3. 必要 body-phase 查询复用原 Create/Drive/activation/effect，不能用新
   canonical phase 或凭结果倒选来源。缺 native source 仍明确是条件结构证据。
4. 独立按原条款核表，再做必要相关回归、checkpoint、版本与远端核验。

F16 的原 COMPLETE→reuse 图四个真实阻断继续保留，不靠修改 opaque fixture
消除。R1/R2 竞争同 B、初始 ASEND 的 R.initial / B.Created / nonNone SEND
仍是独立原义务，不能仅有 rule enum。后续 scheduler S 的 THROW/CLOSE 源桥接
已在上一门验过，不重做它来充当上述状态/竞争验收。

A–H 和 F12/F13/F15/F17/F21/F23 原条件结构验收保留。F14/F16 及另外八族、
P4 组件/冻结全仓、P5、M2 原113构造/196字段均未完成。模型阶段齐备后先按
用户要求讲解，再做 M3 自动 lowering/M4 采集对应；没有新增 backend 或 LeWM 加速比。
