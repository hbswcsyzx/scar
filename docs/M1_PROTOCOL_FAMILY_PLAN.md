# C2/D3：协议义务与发生关联实施计划

2026-10-18。审计基线 `08c4cbf`，依据 [实际审计](M1_PROTOCOL_FAMILY_AUDIT.md)、
原 [C2](M1_RESUMPTION_INTERFACES.md)、[D1](M1_DRIVER_CONTRACT_V2.md)、
[D2](M1_DRIVER_LIFECYCLE_CONTRACT.md) 和 [控制协议§7](model/PYTHON_CONTROL_PROTOCOLS.md)。
**当前 P0 审计及 [P1联合合同冻结](M1_PROTOCOL_CONTRACT.md)完成；
P2–P5 实施、D3、完整第一阶段均未完成。**

## 1. 交付目标与固定原则

在同一 ProgramModel 中连接：原请求→实际参数处理/委托→body 或无 body 路径
→真实首出口→host adapter/请求后态，以及本次 Drive→持续 body 的实际发生。
使用现有四 body kind，不增加一套 phase 状态机、permit、第二套 def-use/world。

协议义务的分母由版本化 scope 派生；用户省略的 relation 不会删掉该义务。
每项返回原 sites/Uses/edges/results/state 及明确缺口或矛盾。不存在“重复节点
所以 cache”的规则。结构声明、来源适用、运行发生和变换权限继续分开。

Scope 内部尚不精确的操作保留完整保守输入/效果/正常异常出口；它能被表示，
但不能记成内部已理解。真实 lookup、异常 factory、委托与释放可 callback、
raise、改变状态，不因为被放入协议表就变纯函数。

## 2. 完整验收分母

编号沿独立审计 F01–F24、X25–X28 保持；不是28个测试或28个已实现协议。
每行要有具体原图正反连接、准确 error/gap 和能力范围。同步 generator 还要
保留 Created/Running/Suspended/Closed × Next-Send/Throw/Close 全表，不能只测
成功暂停一次。其他家族按自己的 request/body/当前状态组合验收。

| ID | 必需覆盖 |
| --- | --- |
| F01 | 四 kind 的定义/创建、compile 分类与 scope、参数/环境；创建不执行 body。 |
| F02 | 多 Create 与外部实例、当前启动状态、动态 instance/captures；不猜唯一来源。 |
| F03 | 四 raw kind、1–3 THROW 原参数、omitted/None、真实规范化/回调/失败路线。 |
| F04 | Created Next/Send(None)；non-None 前置拒绝、仍可后续启动，无假 body/F。 |
| F05 | 启动前 throw：校验拒绝、构造回调及实际注入后态、无用户入口终结、独立 adapter。 |
| F06 | Running 重入拒绝，合法嵌套发生与并发 continuation 区分。 |
| F07 | YIELD→本次 item；发送引用→本次表达式；saved 和当前 state 不混。 |
| F08 | Suspended Throw 的 packet/context/cause/tb、捕获继续或传播及准确后态。 |
| F09 | body Return→迭代完成 value；body 内部主动 StopIteration 的不同转换。 |
| F10 | Closed next/send/throw/close；无 body、没有上次 return payload 重放。 |
| F11 | Created/suspended close、返回值/GeneratorExit/其他异常、非法 yield 后续体与重试。 |
| F12 | native coroutine、await iterator 获取/校验、零挂起完成及协议错误。 |
| F13 | AWAIT 中间 scheduler handoff、恢复 iterator、表达式/最终结果的分别连接。 |
| F14 | coroutine 重入、重复使用、throw/close 与各自实际失败后态。 |
| F15 | GENERATOR_COROUTINE 直接驱动与 await 使用；普通 generator 不自动获 await 资格。 |
| F16 | asyncgen 四种 request 创建/驱动、首次发送、request 复用/并发及关联。 |
| F17 | ASYNC_YIELD 的 item/request 完成与 body 暂停；AWAIT 的当前 session。 |
| F18 | asyncgen 自然完成、主动终止异常、源级 nonempty return 非法规则。 |
| F19 | asyncgen closed/athrow/aclose/失败的版本差异；各 native bit、续体与 request 分开。 |
| F20 | YieldFrom 的求值、GetIterator、首次 Advance、零次父挂起及初始失败。 |
| F21 | delegate next/send 的真实 lookup/call/result/state；缺方法及异常。 |
| F22 | delegate throw 原 raw 参数、方法缺失/失败/item/exhaustion、父是否恢复。 |
| F23 | delegate close/GeneratorExit、异常覆盖与父 pending/context，不能先统一 Attach。 |
| F24 | 取消请求、实际交付、捕获/抑制/清理再 await 与最终状态，不新增万能 CANCEL。 |
| X25 | C1/context/pending/local binding、多个 cut/loop/合流与旧状态拒绝。 |
| X26 | 实际终结/publication、session 当前性、partial RAISE、窄 release 与宽 helper。 |
| X27 | 同一 activation 两次 Drive、准确 ingress/outcome/实例、线程/run、缺采与错接。 |
| X28 | strict wire/query/CLI、完整义务 ledger、预算/cursor、旧范围与未证适用条件。 |

core-connections 的 F01–F16、语言报告的机制表与上述编号有重叠；保留其原编号
和报告，不能累计成额外覆盖。完整 M2 还要单独核113构造/196字段原清单，D3
关闭也不自动关闭所有 Python 构造。

## 3. 自主验收节点

| 节点 | 交付 | 验收及拒绝条件 |
| --- | --- | --- |
| P0 当前审计 | 三路源码审读、旧 IR 五观察、新启动 throw 六观察及初败、完整分母。 | 已有关系/真缺口/推断撤回分别记录；不得把旧泛型结构当 native 等价。已完成审计，不授产品 PASS。 |
| P1 联合合同冻结 | [精确合同](M1_PROTOCOL_CONTRACT.md)：F 固定 profile/原端口与 O 两自然键关系；以下五项决策均有落点。 | 已以 PASS_WITH_SCOPE 自主关闭设计门；保留初稿及修订。只证明设计可实施，不算 F/O 产品或全家族通过。 |
| P2 F 基础闭环 | 同步 generator 全表，原 raw→处理→gate/body 或无 body→source→host adapter。 | 正确类型但错来源、前置拒绝误终结、初入/内部异常混同、close 错后态必须发现；其他家族分母仍保留。 |
| P3 O 发生闭环 | 一持续 body 两次 Drive，Start/Resume、instance/captures、当前/saved inputs、实际首出口。 | 不放宽 CallActivation；错 activation/generation/run/状态/来源拒绝，缺捕获保 gap；可逐次换线程。 |
| P4 全家族组合 | coroutine/generator-coroutine、async request、delegation、await/cancel 与 C1/session/release。 | 逐项映射 F12–F24/X25–X27；普通 opaque 边界不冒充内部协议已验证，不能只贴家族 label。 |
| P5 公共面与完整 D3 | X28、完整 F/X ledger、独立复审、兼容/预算/版本与冻结全仓归档。 | 旧 case/fixture守恒；手工 IR 不冒自动恢复；实际未实现项目保持 OPEN。满足整门才写 D3 通过。 |

有实质源码变更的实施关卡按原规矩：有意义的定向测试→组件→干净提交→一次
冻结全仓→归档/只读核验→commit/push。全仓活跃时所有作者停止源码/文档/报告
写入，不并行 SCAR 测试/profiler、不自动重试；仅清理独占且进程已结束的临时目录。
纯审计/文档节点复用已冻结源证据，不为了增加计数再跑完整回归。

## 4. P1 必须冻结的五个决定

五项现按[联合合同](M1_PROTOCOL_CONTRACT.md)冻结：下文保留原始问题及候选，
其中“尚待冻结”是P0历史措辞，具体实施以联合合同为准。启动路径用准确
NoEntryInputPort/selected edge/当前后态；11个fixed profiles及原scoped来源；
五种局部contract与派生consumer义务；两O表及实例/capture/segment逐端点核对；
Program17/Execution8、完整ledger及预算。当前进入P2，不等待用户逐门审批。

1. **启动异常路径。** 采用明确的 no-user-entry 初入注入路线，不伪造函数形参、
   SEND 或进入未执行的 finally。不能用“规范化失败”一个标签决定是否关闭；
   原 helper 的实际产出/失败路线、当前状态、终结提交与 host adapter 必须相连。
   尚待冻结：成功注入/前置拒绝/构造回调后异常的确切契约锚和部分后态。
2. **协议入口与版本。** 按现 family/receiver/raw 角色和准确 source/provider
   选择适用合同，区分 direct driver、await wrapper、async request；不是同方法名
   或任意 FactRef 即可匹配。代码/编译上下文继续引用原 artifact，不重建 registry。
3. **局部契约与效果。** 冻结 raw 选择、规范化、delegate/await、异常构造/转换、
   host adapter 的最小原 site/Use/result/edge 引用。优先派生；确实缺语义锚才加
   附件。真实用户协议调用保留 INVOKE 的 N/R 与 callback 后新 state/gate。
4. **持续实例和发生关联。** 候选形状为 drive occurrence、activation、entry visit
   或 Unresolved、outcome occurrence 或 Unresolved、现 FactSource；segment 从
   visit 派生。当前 instance→creation/captures 的必要关联也必须有落点；不按同
   Region/内容猜 owner，不套同步调用的一 caller/一 activation 或全历史同线程。
   O 仅用于真实 BodyDrive；no-user-entry/delegate-only 锚原 host/helper/adapter
   的 F 路径，不要求或伪造父 Drive。instance/segment 能派生时不复制为第二事实。
5. **完整 ledger 与兼容。** 原协议 clause 不可随 optional joins 消失；旧 D1
   保原 scope。新能力显式版本化，query保具体缺口/矛盾/截断与原端口，准备/校验/
   外部快照/copy 成本另列。声明完整不变成 source/native/identity/transform 已证。

P1 未收敛时继续查源码、已有见证或最小新反例，自主修订；这不是需要用户确认
的外部阻塞。不新增完整编译器、调度器、collector 或任意 Task 框架。

## 5. 后续阶段与停止边界

M1 负责这些记录的可表达与机器拒错，M2 负责构造协议的完整分解；M3/M4 才从
任意程序入口与实际执行自动恢复并验证对应。M5 闭合观察依赖，M6 给具体化简
指导。不能将模型阶段的缺接口推迟为“以后采集”，也不能把声明 IR 当自动建图。

整个 M0–M2 完整矩阵验收后，按用户要求先停下来讲解模型。当前尚未到该点，
不增加 detector/backend、LeWM 特殊规则或新的重型 profiling；没有新的加速比。
