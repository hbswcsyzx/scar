# C2B body 字段合同独立审查

2026-10-17；源码基线 `b4bc1a4`。本轮以新 `docs/M1_RESUMPTION_BODY_COMPONENT.md:1–135` 为审查对象，旧 C2 讨论仅作背景。
只读设计与现 core；没有修改产品/测试，没有运行探针或回归。以下是结构机制审查，不是新 validator 已接受/拒绝某图的实测结论。

## 结论

**字段可以冻结，未发现仍需先修的结构矛盾。** 此结论要求新文档全部约束共同生效，不能只实现 records 或两种边投影便宣布 C2B 完成。
此前指出的当前 Detach 片段精确锚、Reference 精化与 LocalBinding 转发三项，分别已由该文档 `44–45`、`49–51/100–103`、`100–101` 闭合。
“完整 body 结构组件”与完整 C2 的边界明确：新文档 `4–6,111–122` 保留实际 driver ingress、host outcome、实例/代次、source/runtime 与最终释放为未验收事项；没有要求先实现完整编译器。

## 1. 关键反例及本合同如何排除

| 最小机制 | 必要约束及新文档位置 |
| --- | --- |
| landing 收到 f0 后 Attach；body context 改成 H；当前 Detach 产 f1，但再次保存 f0，下一次恢复丢失 H | FRAME_CONTEXT 槽必须精确是紧邻当前 Detach 的结果；Attach 必须消费该 source 槽转发的 formal。`44–45,64–65`；类型或构造来源集合不够。 |
| yield 前未知引用，经保存后 formal 被伪造为固定 referent/alias；或任意 delivered reference 被精化 | SavedInput 必须沿用 reference_binding；ResumeInput reference 无无据精化。`49,100–103`。 |
| x 绑定后 yield；恢复后 LOAD_LOCAL 因新槽投影没有被 binding facts 识别而错判无来源 | SavedInput 的同一 canonical Use 解析同时用于 LocalBinding 同 slot 与 BOUND 事实。`100–102`。不能只接 C0/C1。 |
| 未保存的 entry/OperationResult 直接跨 yield 使用；经第二次恢复、merge 或 loop 再使用 | availability roots 包括所有 landing，核验所有 Uses，包括下次保存源；不是只检查第一个 landing。`95–98`。 |
| 把上次 world 保存后送回，或漏掉一个外部状态域 | StateVersion 禁止 saved；handoff 当前全域，各 case 的当前域由 ResumeInput 恰一次绑定。`43–44,47–51,91–93`。实际“当前”运行时对应仍待 driver。 |
| 旧 caller token 保存后在下一 drive Detach；普通分支反选另一个同型 token | caller 禁止 saved；当前 active token 逐普通边精确转发；Detach 消费该 token。`74–79,115–118`。不能替换成来源集合相同。 |
| 同一 Suspend 的两个 case 共用 landing，检查只看到一个 predecessor block | 每个 case 的 landing 唯一且独占该条 temporal incoming。`55–56` 应落实为恰一条 incoming edge，不是 predecessor block 集合大小。 |
| yield-in-finally 被当 Return，pop cleanup，或恢复时重跑 Enter | Suspend 没有旧 ExitPort/INVOKE completion；C1 activation 沿 temporal 真实边保持，pending/context 用 saved Use 转发。`81–89,105–107`。 |
| PendingDefinition 在本次 cleanup 内、yield 之前构造，恢复后合法 Replace 被错拒“不是本次新建” | fresh 使用 logical dominators 和原 cleanup entry，不用 availability roots 重置。`105–107`。 |
| Throw 恢复直接跳出 protected scope/侧入 cleanup，省略真实 unwind/Replace | landing 词法归属相容，C1 原保护区/入口/操作点栈规则继续适用。`105–107`；应先在合法 landing 接入，再沿真实普通控制路由。 |
| Detach 后继续用户计算，其异常继承 caller 而非 body context | Detach 紧邻 Suspend/真终端，卸载后无 body 用户动作。`81–83`。实际 FrameExit/release 不偷套旧同步 gate。 |
| 以普通 call/INVOKE 调 body，忽略其 Suspend | ResumableBody 禁止作普通 callee；完整 body 可以独立声明，但不伪造 Python call→body 来源。`111–113`。 |

普通 INVOKE 可以保持当前 caller token 为边的 forwarding Use，而不是 invoke argument/CompletionResult；这与现 core 的双 completion 模型相容，也符合私有 token 不逃逸要求。
Attach/Detach 只在 context 域推进状态，其他域继续当前版本，与 C1 全域未知回调操作并不冲突：两类 primitive 的已声明效果不同，不能把真实 release/hook 合并进无回调 switch。
继承当前 caller 的可重定位 frame-context 解释沿用主合同 `docs/M1_RESUMPTION_INTERFACES.md:69–118`；body 记录本身不证明真实实现维护该关系。

## 2. 实施时必须一起接通的有限清单

这些是上述字段合同的必要实现位置，不是额外 C2.4 功能。

- **统一实际 Use 解析**：普通 UseID 原样解析；SavedInput 只在该 Suspend 的唯一 saved 元组中索引到 owned Use；ResumeInput 不变成旧值来源。检查 exact variant、索引范围与 owner 后再供各分析使用。
- **core 绑定与精化**：`scar/ir/program/validation.py:208–261,359–369,526–532` 的 owned-input equality、边类型、reference_binding 要同时认识新边。saved actual 在 Suspend 表内只计一次；不能因同槽用于多个互斥 case 而重复计 Use。
- **binding 全链路**：`binding_validation.py:79–89,249–270,508–518` 既有 incoming/facts，也有 use authorization；query 使用的 `derive_binding_facts` 不能保留旧 UseID-only 路径。same-slot 和禁止 fabricated binding 的规则不放宽。
- **C0/C1 全链路**：`control_validation.py:67–80,233–239,254–264` 的 facts、typed-constructor 分派和 pending escape，以及 `cleanup_forward.py:103–110`、`cleanup_validation.py:376–394` 的 copy/context escape 均须接通。不能把新 FRAME/CALLER 结果误归入旧 C1 saved-context constructor 表。
- **双投影分工**：cut availability 负责定义可用性；logical CFG 负责可达性、词法保护、C1 stack/copy/fresh。不能全局换掉旧 dominators 后让 C1/fresh 意外使用 cut roots。旧排序关系的控制依据也应明确沿用其既有语义。
- **attachedness 在操作点处理**：landing/entry 进入时 Detached、没有旧 caller 参数；Attach 在本 block 产当前 token。其他以 Attached 进入的 block 才有唯一 caller formal。Detach 后仍在同 block 的旧参数存在于记录里，不表示它可再次消费/转发。
- **当前状态与私有性**：Suspend handoff 使用 Detach 后的当前 context state；resume 输入是 pre-Attach 当前 state。SavedInput/ResumeInput 都不能成为普通用户 payload、外部 call actual 或协议值伪造通道。
- **版本与查询**：v10 显式识别新 capability，v1–v9 拒绝夹带；exact 新 variants 的 codec/query 与 validator 同步。query 展示 declared source/slot，不能编造实际 driver producer、实例或代次证据。

## 3. 验收与停止界限

人工 IR 至少验证新文档 `126–132` 的正反例，尤其当前 Detach 锚、binding 查询、两个 case 的独立 landing、INVOKE forwarded caller、fresh-before-yield、finally 中 Throw→Replace。
这些验证只证明声明 body 图与新结构合同一致；不证明源 frame 的全部 live values 均已捕获，也不证明 ResumeInput 真来自最新运行状态、一个 generation 只执行一次、委托/cancel/host 映射已实现。
委托已接受但父 body 未恢复的 fast path 和最终 frame release 继续位于 C2.4/生命周期边界；本轮不以不透明 helper 伪称已经闭合。
实施后仍须独立检查实际代码与反例结果；本报告的“字段可冻结”不能替代该步骤，也不改变第一阶段完成后先停的要求。
