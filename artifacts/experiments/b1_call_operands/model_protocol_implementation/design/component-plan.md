# P2 protocol foundation 组件计划

日期：2026-10-18。状态：**仅计划，NOT_RUN**。

本次仅新增 `gates/m1_protocol_foundation.json`，不修改既有 gate、产品或测试，也不执行 Python、pytest、组件或全仓。本计划不能作为通过报告。产品实施基线为 `85aee70`；实际组件必须另绑定执行时的 revision、全部注册源码 SHA 和精确 selectors，不能把开发期聚焦日志当作最终冻结证据。

## 1. 交付边界

这是 **P2 部分基础检查点**：Program17 的 F 声明、原端口连接、部分无入口路线、精确 EDGE 的终结来源和 session/release 组合。完整 P2、P3–P5、D3、全程序第一阶段均未关闭。Execution8 的 O 发生关系及其 host HB 不在本 gate 的验收范围。

既有原 Operation/Use/StateAccess/CompletionResult/producer 是唯一规范来源。选择同型 payload、相同 source 名称或相同 port 类型不能替代精确连接；conditional F/P 不是真实 native/source/runtime 证明，frame release 也不是对象 free 或 GPU completion。没有优化、转换或自动恢复授权。

## 2. Runner 约束与固定 selections

依据只读审阅 `scripts/run_gate.py` 和 `gates/m1_lifecycle_composition.json`：manifest 使用 `gate/scope/limitations/criteria`；每条 criterion 的 tests 非空、ID 唯一。runner 对去重 selectors 运行一次 pytest，再逐 selector 回查 JUnit；零匹配、失败、error 或 skipped 均不通过。执行前后注册源码指纹必须相等。注册集包括 `scar/tests/scripts` 的 Python、所有 gate JSON、`pyproject.toml` 及存在时的根 `sitecustomize.py`。

本 manifest 固定 **11 条 criteria**。完整节点以 JSON 为准；本表说明选取理由，不声称用例数或状态已经通过。

| # | Selection | 必要性 |
| --- | --- | --- |
| 1 | 新 protocol records 全文件 + 既有 protocol values 全文件 | exact nested records、canonical model port hook、不可变规则分母；RAW/packet 等值仍保持原 producer/type。 |
| 2 | 新 protocol codec 全文件 | Program17 能力隔离、所有新 variant、旧 v1–v16 拒偷渡及独立 v16 bytes。 |
| 3 | 新 protocol connections 全文件 | raw ordinal、同型错误 packet、原处理结果、loop 旧值、N/R、adapter 和无入口准确 EDGE。 |
| 4 | 新 protocol ledger 全文件 | 删一条 edge binding 后义务仍在、完整 clause 分母、预算 cursor、未实现 source inventory 仍缺口。 |
| 5 | C 新 protocol release connections 全文件 | 准确无入口来源与既有终结、session 和窄 release 的真实组合；不拿旧独立测试代替新连接。 |
| 6 | 9 个旧 driver graph 节点 + driver queries 全文件 | 原 raw/capture/gate 后态、无插入 landing、Start/Resume、first frontier/发散，以及原输入输出查询不被 F 覆写。 |
| 7 | lifecycle flow、session flow、session composition 三个旧文件 | F 新 EDGE seed 直接影响 must/rename/forget/循环定点；当前 session post 的失效规则必须保持。 |
| 8 | 6 个旧 no-body graph 节点 + no-body queries 全文件 | 不把 false/reject/同型 owner/旧 state 当终结；旧 predicate-only 不虚构 finish。 |
| 9 | 固定 FrameRules 构造节点、6 个 session/release graph 节点及其 queries 全文件 | 旧终态 owner、合流来源、partial RAISE、callback 失效、suspend 不等终结及原 release 来源仍成立。 |
| 10 | 5 个旧 driver/no-body/session-release wire 节点 + literal codec 全文件 | 保留相关历史 golden 与 CompletionResult/profile 差异；Program17 最大版本不改 v16 literal family/wire。 |
| 11 | 旧 lifecycle scope queries/CLI 两个全文件 | detached 查询仍附原 rule/operation/真实 edge，旧显式 scope 的 conditional 分析不升级为适用性、runtime 或 transform。 |

没有整仓加入原 lifecycle 大 gate；未选旧测试没有被豁免，必须在最后全仓中运行。这里不预报参数化展开总数，实际数量只来自执行日志/JUnit。第 5 文件在规划时尚待作者交付；其精确路径为 `tests/unit/test_program_protocol_release_connections.py`。只有实际落盘、非零收集且通过才能满足该项，不得用占位/skip/删 selection 填补。

## 3. 执行次序与自验收节点（后续由根代理执行）

1. **Focused**：各 owner 完成自己的有限聚焦，保存原命令、完整 stdout/stderr、首败归因、修正及 source before/after。本计划不执行、不覆盖既有原始日志。补齐第 5 文件并完成独立有限源审。
2. **Component**：停止本批共享源码写入，确认所有 11 条 selectors 实际存在。用 lewm 环境执行 `python scripts/run_gate.py gates/m1_protocol_foundation.json --out artifacts/experiments/b1_call_operands/model_protocol_implementation/component/foundation.json`。这是拟执行命令，**本轮未执行**。任一零匹配、跳过、失败或指纹变化，保留该次结果并修复具体问题；不缩小分母、不转成通过。
3. **Freeze**：组件通过只关闭本文件限定的 foundation 检查点；停止所有 source/test/gate 写入，记录 revision、全部注册文件及联合指纹、实际 case 和 11 条独立 criteria。若随后改变已测试源码，原组件结果不再代表新源码，须在最终候选上重新取证。
4. **Version management + full**：根代理按既有流程建立干净 implementation commit，在该不可变源码上运行**一次包含所有既有测试的全仓回归**，保留源码/命令/原日志/旧 case identity 与 fixture 守恒证据。组件 selection 不能替代 full；full 失败须如实保留，不能用组件通过宣称整门通过。
5. **Archive/push + bounded report**：归档组件、独立源审、full 的各自范围与指纹后，由根代理管理版本及推送。报告 foundation 的真实状态和下表 OPEN 分母；不把测试时间报作 LeWM 加速比。

## 4. 同步 generator 完整 16 格（未关闭）

本表是完整 P2 必须进一步落实的状态/请求分母。当前 foundation 的部分路线覆盖不关闭任意整格；每格还须实际原端口正反例、准确错误/gap、adapter/后态及来源条件。

| State | next | send | throw | close |
| --- | --- | --- | --- | --- |
| Created | OPEN | OPEN | OPEN | OPEN |
| Running | OPEN | OPEN | OPEN | OPEN |
| Suspended | OPEN | OPEN | OPEN | OPEN |
| Closed | OPEN | OPEN | OPEN | OPEN |

## 5. 父计划完整固定分母

沿用 `docs/M1_PROTOCOL_FAMILY_PLAN.md` 及 `docs/M1_PROTOCOL_CONTRACT.md`。以下是 **28 个完整义务组**，不是 28 个测试、不是已通过清单。本 gate 只提供其中部分连接证据；每个完整义务组在本计划仍为 OPEN。

| ID | 完整义务 | 状态 |
| --- | --- | --- |
| F01 | 四 kind 定义/创建、compile 分类/scope、参数与环境；创建不执行 body | OPEN |
| F02 | 多 Create/外部实例、当前启动状态、动态 instance/captures | OPEN |
| F03 | 四 raw kind、THROW 1–3 原参数、omitted/None、规范化回调及失败 | OPEN |
| F04 | Created Next/Send(None)、non-None 前置拒绝及后续启动 | OPEN |
| F05 | 启动前 throw 的校验/构造/注入、无用户入口终结、独立 adapter | OPEN |
| F06 | Running 重入拒绝、合法嵌套与并发 continuation | OPEN |
| F07 | YIELD 本次 item、sent 表达式、saved 与当前 state | OPEN |
| F08 | Suspended throw 的 packet/context/cause/tb、捕获或传播后态 | OPEN |
| F09 | Return 完成 value 与主动 StopIteration 转换 | OPEN |
| F10 | Closed 四请求无 body、无旧 return payload 重放 | OPEN |
| F11 | Created/suspended close、GeneratorExit/异常、非法 yield 后续体与重试 | OPEN |
| F12 | native coroutine、await iterator、零挂起完成与协议错误 | OPEN |
| F13 | AWAIT scheduler handoff、iterator 恢复与最终结果 | OPEN |
| F14 | coroutine 重入/复用/throw/close 实际后态 | OPEN |
| F15 | generator-coroutine 驱动/await 资格 | OPEN |
| F16 | asyncgen 四请求创建/驱动、发送、复用/并发及关联 | OPEN |
| F17 | ASYNC_YIELD item/request 完成与 AWAIT session | OPEN |
| F18 | asyncgen 完成、主动终止异常及源级 nonempty return | OPEN |
| F19 | asyncgen closed/athrow/aclose 版本差异、native bit/续体/request | OPEN |
| F20 | YieldFrom 求值、GetIterator/Advance、零次父挂起及失败 | OPEN |
| F21 | delegate next/send 的 lookup/call/result/state 与异常 | OPEN |
| F22 | delegate raw throw、缺失/失败/item/exhaustion 与父恢复 | OPEN |
| F23 | delegate close/GeneratorExit、覆盖、父 pending/context | OPEN |
| F24 | 取消请求/交付、捕获/抑制/清理再 await 及最终状态 | OPEN |
| X25 | C1/context/pending/local binding、多 cut/loop/合流、旧状态拒绝 | OPEN |
| X26 | 终结/publication、session 当前性、partial RAISE、窄 release/宽 helper | OPEN |
| X27 | 持续 activation 多 Drive、ingress/outcome/实例、线程/run、缺采/错接 | OPEN |
| X28 | strict wire/query/CLI、完整 ledger、预算/cursor、旧范围及未证条件 | OPEN |

P3（O 发生关系和 conditional host HB）、P4（其余家族与组合）、P5（完整公共 ledger 和总验收）均为 OPEN。没有以增加 family enum、FactRef、手工声明 IR 或有限 fixture 取代这些实际连接义务。
