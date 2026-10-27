# C1 must-forward 独立审查

日期：2026-10-16。范围：声明类型、canonical CFG/SSA/state 组合；未编辑产品、未运行测试、
全仓、采集或 LeWM。依据 `docs/M1_CONTROL_INTERFACES.md`、
`scar/ir/program/{model,validation,control_validation}.py` 与旧 C1 Proposed 合同。

## 判断

以 entry pending 与本次 Enter.result 分别为锚、按真实 actual→formal 做 AND，方向正确。
它能拒绝同 port 换 payload、同 payload 重 pack、分支 phi 反选及旧 visit 保存值。
在 core-valid、entry 支配 activation、全路径 routing/LIFO 先成立的前提下，
未找到会把不同动态 token 当成本次锚的可实现反例；不需要新增持久 graph/store。
但建议修改“GFP 与 OR-LFP 最后直接相交”的算法表述，并显式检查 fresh seed 的支配性。

## 1. GFP∩LFP 的闭合缺口

抽象复制依赖有反例：`w = AND(w)`，`v = AND(anchor, w)`。
AND-GFP 给 w/v 都 True；seed-reach OR-LFP 给 w=False、v=True。
最后相交仍给 v=True，虽然它的一条 incoming 是无种子 w；交集不保持 AND 闭合。
这不是已证实的 canonical core-valid 产品反例：真实 entry 可达、domination 与完整
incoming 参数通常迫使任何可执行 SSA 环有入口 seed/boundary，后者 False 会传播。
因此不应将这项抽象反例误报为已运行的产品漏洞，也不应单靠相交声称一般性排除污染环。

稳妥次序（pending/context 与 fresh 均适用）：
1. R：以真 seed 为根，沿 actual→formal 依赖求 OR 的最小固定点。
2. R 外固定 False；R 内候选初始化 True；真 seed 固定 True。
3. 按每条 incoming 的 AND 降序求最大固定点；零 incoming 非 seed 固定 False。
等价修正是相交后再运行 AND 到稳定。`AND(anchor,self)` 仍合法，孤立/污染环不合法。
保留 core-first 的先决条件；不要用此推导替代普通 dominance 或定义顺序检查。

## 2. fresh 不能只检查 producer 的静态块属于 slice

若允许 cleanup 非 entry 侧入口，存在 core domination 仍能通过的形状：
`region-start → C.P(pack q) → outside X → C.entry → Replace(q)`；
另有 `C.entry → C.P` 分支，故 P 属 entry-reachable slice。
q 的 producer 全局支配 Replace，但该次 entry→Replace 没有执行 pack，q 来自 entry 前。
仅以“producer 在 slice”置 seed=True 会误认 current-activation fresh。
必须先拒绝侧入口/跨边界回入，并确认 entry 支配 producer；或至少对每个 seed 单独核验
entry dominance 与 Enter-before-producer。entry 第一条 operation 精确为 Enter 可给同块顺序。
若完整 routing gate 已保证唯一入口，此反例已被 gate 排除；请写成前置不变量。

类似地，must-copy 本身不证明 action 执行时 activation 仍活动：离开 C 后再侧入其
Resume，静态 Enter.result 仍可能 dominate；必须由所有边的 coverage/LIFO gate 拒绝。

## 3. 实现必须保留的逐点和逐边信息

- slice 仅沿真实 successor 留在 C 子树内扩展；到 entry 的边切断，不能切断整个 entry。
  entry.pending 固定为锚；entry 的其他参数固定 False；context 锚仅本次 Enter.result。
  重入 entry 是新 visit，不能从 incoming 猜测新的 saved-context 与旧 token 相同。
- 逐 `(terminator operation, successor index, formal index)` 收集 incoming；不能按
  predecessor block、目标 block、port 或 actual ValueID 去重而丢失参数位置对应。
  同一 BRANCH 可两边落同一 block，但两套 actual 次序不同，仍须分别 AND。
- slice 外 incoming 固定 False；slice 外值与非锚 operation result 不能成为 must-copy seed。
  边 actual 的 UseID 应经该 terminator 自己的 uses 解析，不能将 UseID 当 ValueID。
- INVOKE 的 UseID 转发是 caller 本地 copy，NORMAL/RAISE 分别处理；CompletionResult
  是新 completion 产物，必须 False。不得因 terminator 是 INVOKE 而拒绝所有转发。
- core 已检查定义支配 use、同块先定义后使用、每条真实边的参数类型及全部 state 当前态。
  只有先通过这些检查，静态 producer/block 信息才足以表达该次合法执行的值可用性。
- action 的 pending/context 必须分别证明，不能由一个证明推出另一个；所有 action 必须
  在本 scope 的 slice 且匹配当前活动顶层 cleanup，不能拿 outer context 完成 inner action。
- 若 action pop 后其 continuation 仍留在 C 的词法子树，单纯 lexical slice 不等于 activation；
  应由 routing gate 禁止这种布局，或把已匹配 pop continuation 也作为 activation 截断边。

## 4. must-fresh 的含义和 nested 情况

fresh seed 仅为当前 activation 内、满足上述 dominance 的 PendingCompletionDefinition
OperationResult。entry 所有参数（含 saved pending）及外部值为 False；phi 用全部边 AND。
在 C 内循环重复执行同一 pack 仍 fresh：这里证明“本次 activation 内产生”，不证明
“本次 loop iteration 产生”。若需要后者，必须另加语义，不能复用本谓词的名字暗示。
新 pack 即使 port/payload 相同也不能 Resume，但可作为 Replace 的 new_pending。
old saved token 即使 port 与 fresh token 相同仍不得 Replace；constructor 集合相等无帮助。

fresh 还须与派生 cases 的完整性联合检查：至少一个 case、无未知边界，且每个 case 的
真实最终目标都离开 C 子树（region exit 也算离开）；看最终 port 目标而非下一站 route。
local break/continue 的目标仍在 C 内，应完成局部转移，不能 Replace 外层 pending。
fresh 只证明分配来源，不证明该 pack 对应源程序确实发生的新 return/raise/break。

对 outer C，inner cleanup 子树仍在 outer slice；inner 本次产生并正确转发的新 token
可供 outer Replace。对 inner，以 outer 的旧 pack/outer saved-context 为来源必须拒绝。
inner Resume 的临时 Fallthrough token 不等于 outer saved pending；两套锚分别保存并校验。
outer 不能经重新执行 outer entry 处理 inner Replace，应在同一次 outer activation 上 Replace。

## 5. 预期接受、拒绝与精度边界

- 接受：`phi(anchor,self)`、两分支都逐边传 anchor、INVOKE 两边 UseID 传 anchor、
  nested cleanup 后原 outer token/context 回传、当前 activation 新 pack 后 Replace。
- 拒绝：`phi(anchor,new_pack)` 后 Resume、相同 port 的 p/q 反选、entry 额外参数携旧
  context、CompletionResult 冒充 copy、无种子/受无种子污染的 copy、旧 pending 作 replacement。
- 单 ValueID 的 AND 会保守拒绝这种图：phi 在一条前驱取 anchor、另一条取 q，随后通过
  同一条件/已知 pending-case 只在 anchor 那条动态路径使用 Resume。全 CFG AND 看不到
  此相关性。若合同是所有声明 CFG 路径，拒绝合理；若要接受这种图，需要逐程序点/edge
  的受限路径事实（或拆分 CFG），不能用 constructor/port 集合比较填补。

## 6. 仍未证明的事实

上述结果仅为显式接口、SSA 拷贝、局部新鲜性和路由结构的派生事实。全域 READ_WRITE
与 current state 防止静态回滚；不证明真实 runtime 的 Enter/context 安装恢复、异常链、
callback/finalizer 效果、Python payload 求值时点、source↔graph 或 finally 必执行。
未知 effects/未建模域仍需原条件或保守后态；不得将此报告提升为优化/backend 授权。
