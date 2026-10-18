# P2 协议连接基础：实施范围与验收

2026-10-18。依据 [P1 精确合同](M1_PROTOCOL_CONTRACT.md) 和
[P0–P5 计划](M1_PROTOCOL_FAMILY_PLAN.md)。这是 P2 内部的可复核检查点，
**不替代 P2 的完整同步 generator 矩阵，也不关闭 D3 或 M0–M2。**

## 1. 本批实现为何属于程序模型

程序仍由原 Operation、Value、StateLocation、Region、Resource 及其关系表达。
新增协议附件约束这些原实体之间的连接，不建立第二套生产者、状态链或执行图。
例如 THROW 的连接是原 raw pack 的某个 operand occurrence，经本次处理结果，
到显式 packet 的 component，或直接从原 helper 的完整 packet 到 body ingress。
两个端口类型相同，只满足类型条件；它们是否来自本次同一个结果还要单独检查。

新增 `protocols.py` 定义两个 scope subject、五种局部 contract 及原端口引用。
`protocol_rules.py` 保留 P1 的 11 个固定 profile 和 clause/rule 对应表。
`ProgramGraph` 增加 `protocol_scopes`、`protocol_operations`；自然键为
`(scope, clause, operation, slot)`。来源尚未解决时用显式 StaticProtocolGap。

`protocol_flow.py` 从原 CFG、owned Use、result、completion edge 和 DriveResult
派生端口与 must-copy 关系。一个静态 producer 在循环中再次执行，会清除它上一
次结果的 copy 事实；不能因为 ValueID 相同就把旧迭代的结果当成本次结果。
调用或跨 region 的关系没有证据时仍为 unresolved。

`protocol_validation.py` 检查已知错接；`protocol_query.py` 保留固定 clause 分母、
已知 INVOKE 的每条 N/R 绑定、缺口和共享预算。删除行或删除 scope 不能产生
“空集合即完整”的结论。声明、来源适用、实际发生与变换权限继续分别判断。

## 2. 生命周期连接

PREENTRY_REJECT 不提供 finished-body 事实。两种 INITIAL_THROW clause 只有
真实 transition、准确 selected edge、完整已知 lifecycle domain 的 state sites、
实际后态和最终 payload 路线连接后，才作为有条件的 F/T 来源。
可能分支到其他出口、出现未证终止的环、缺 domain 或只有只读访问时保留 gap。
原 core state SSA 负责沿途以及 host terminal 的最新状态；中间新写状态合法，
不要求最终仍是 transition 刚产生的同一 ValueID。

F/T 在准确 edge 上、并行 actual/formal rename 之前种入，另一 N/R 分支不会被
污染。原 session 分析仍把宽 helper、callback 和未知 INVOKE 当成失效点。
NoEntryOutcome 不因属于协议表就获得 body-only 白名单。

`ProgramIndex.no_entry_publications()` 和已有 terminal release query 返回原
source、owner Use、selected edge、terminal、state sites。release 继续消费原
生命周期 must fact；这些静态来源不证明实际运行实例、引用释放或 native 等价。

## 3. 兼容与公共范围

Program wire 最大能力版本为 17；仅使用旧能力的图仍序列化成原 v1–v16。
v16 golden 来自冻结的旧提交 `85aee70` 的隔离源码，不由新 codec 自证。
Execution 仍为 v7；P3 的持续 activation/segment 关联尚未实施。
本批没有新增 collector、detector、backend 或 LeWM 特殊规则。

## 4. 同步 generator 完整矩阵仍保留

以下是本批范围，不能按测试条数累计为整行语义通过。所有 native/source
适用条件仍未证明，表中的连接检查使用 supplied IR。

| 当前条件 | NEXT | SEND | THROW | CLOSE |
| --- | --- | --- | --- | --- |
| Created | Start/YIELD 原端口 | **OPEN**：None 与 non-None 准入 | 部分：初入 N/R、前置拒绝、edge F | **OPEN**：旧 CreatedClose 与新 scope 组合 |
| Running | **OPEN** | **OPEN** | **OPEN** | **OPEN** |
| Suspended | **OPEN**：准确 None 交付 | 部分：本次 SENT、Return 与真实 adapter N/R | 部分：本次 packet 到 body/host RAISE；捕获后继续 OPEN | **OPEN**：GeneratorExit、非法 yield、重试 |
| Closed | 本次 helper 输出连接 | 本次 helper 输出连接 | 本次 helper 输出连接 | 本次 helper 输出连接 |

Closed 四列仅核当前结果到 host、无假 Drive/F；没有证明 Closed/source 分支。
完整 28 组 F01–F24/X25–X28，以及 M2 的 113 构造/196 字段保持原分母。

## 5. 本批验收顺序

1. records/codec/原端口/ledger/生命周期组合的定向正反例，保留初败和修订。
2. 独立复审已知错接，运行 `gates/m1_protocol_foundation.json` 组件门。
3. 完成干净实现提交，冻结作者写入；只运行一次完整回归。
4. 只读核对旧 case identities、旧 fixtures、源码、保护目录和完整证据；归档、
   提交、推送。完整回归活跃期间不改源码、文档、报告，也不并行其他测试。

当前结果以同目录的验收报告及机器记录为准；本文件不预先授予 PASS。

## 6. 后续顺序

先补第 4 节的完整 P2 矩阵及源条件，逐项写连接反例；再实施 P3 的持续 body
发生关联，随后 P4 家族组合与 P5 公共面/完整 D3，最后核 M2 原清单。
完整 M0–M2 后先向用户讲解模型，再进入自动恢复和化简阶段。
本批不产生新的 LeWM 自动优化结论或加速比。
