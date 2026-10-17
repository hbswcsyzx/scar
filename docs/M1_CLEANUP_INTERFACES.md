# C1：同步 cleanup、待完成转移及当前异常上下文

2026-10-16 验收，2026-10-17 归档。**静态声明组件已实施并验收：243项组件检查、
3,330项冻结全仓测试通过。**
设计基线 `78c5fda`，集成基线 `588ca84`。
本批补齐模型的控制/状态组合接口，不增加 detector/backend，不修改或运行 LeWM。
source lowering、实际 callable/context/效果对应、with 抑制及 except* 仍分别验收。

## 1. 保留三条独立依赖

- 已求值的 pending token：C0 的 `PendingCompletionDefinition` 与真实 CFG Uses。
- 当前共享/frame 状态：原 `StateAccess` 与各域 StateVersion，不能回滚到进入前。
- 当前 handled-exception context：一个已存在 state 域的用途声明；保存的 context
  不是异常属性、traceback 或整个 world 的快照。

Return pending 不表示没有 ambient exception；Raise pending 进入 cleanup 时安装
其 packet 的 exception 身份。正常清理保留原 token；新的离开转移替换它。无论
哪种情况，用户清理和释放回调已经发生的写都继续沿当前 state 传递。

## 2. 冻结记录及规范归属

新增 `ProtocolValueKind.SAVED_HANDLED_CONTEXT`，沿用 ProtocolValue/OperationResult/
BlockArgument；没有新 producer/actual/state 存储表。引用已有 `ControlEdgeReference`。

```text
HandledContextDomain(region, location)
CleanupInterface(scope, protected, entry, pending_argument, rules=FrameRules())
CleanupEnter(operation, cleanup, pending, saved_context)
CleanupResume(operation, cleanup, pending, context, continuation)
CleanupReplace(operation, cleanup, saved_pending, replacement, context, continuation)
HandledContextRead(operation, exception_result)

CleanupRouteSuccessor(port, block, arguments: tuple[UseID,...])
CleanupRouteTerminator(pending, successors)
```

所有记录 frozen/slots、exact 类型和 immutable tuple；没有 verified/authorized 位。
Interface 的 `rules` 直接复用固定 FrameRules：适用条件 UNKNOWN、可能不完成、
未知回调效果、不保证释放、普通 finalizer 异常 unraisable。它不冻结用户清理动作。

ProgramGraph 新表：`handled_context_domains`、`cleanup_interfaces`、`cleanup_enters`、
`cleanup_resumes`、`cleanup_replacements`、`handled_context_reads`。
domain 每启用 Region 一行，location 必须是入口已有状态域，可为原 coarse world。
每个启用 Region 的 CLEANUP scope 都必须有 interface；未启用的 C0 区域按原合同解释。
scope=CLEANUP，protected=同 Region 的 sibling BLOCK，二者拥有相同 parent；一个
protected 最多一份 cleanup。entry 由 cleanup 直接拥有，pending_argument 是 entry
的真实 pending BlockArgument。source 及完整 state 签名均由既有 core 取。

## 3. 动作合同及默认状态后态

Enter/Resume/Replace 都是普通 Operation，不能带 callee/terminator；有 CONTROL/
READ/WRITE，`effects_complete=False`，每个 Region state 域恰一条 WHOLE、非 overwrite
READ_WRITE access。before 是当前 STATE_CONTENT，after 是本操作规范结果。除了
Enter 的 saved_context，其余结果全部是这些 after；不得只更新 context 而漏外部域。
操作的协议 Uses 与记录一一绑定，不额外藏入其他输入。

- Enter 是 entry 第一项操作，消费真实 pending_argument，产生 saved_context。
  该保存值捕获进入前 ambient context；pending Raise 安装 packet.exception，
  其他 case 保持 ambient，不按 Return 标签清 None。安装效果进入当前 state。
  此同步接口的抽象 token 不规定为扁平异常引用；未来 C2 跨挂起保存还须保留
  body-owned context 与继承当前 caller 的关系，不能快照旧 caller 的可见异常。
- Resume/Replace 直接归属本 cleanup scope，消费本次 Enter 的保存 context。
  Resume 消费 entry 原 token，恢复 context 后继续同一 token。Replace 同时消费
  原 token 与本次 activation 内新构造的 replacement，恢复 context 后继续新 token。
  丢弃旧 payload 的可能回调仍属于全域保守后态。
- Exit action 紧邻该 block 的最后 JUMP；`continuation` 精确引用该 JUMP 的第0条边。
  其目标是**只含 CleanupRoute 的中转 block，直接归属该 cleanup 的 parent scope**。
  route selector 必须是目标参数，实际边的该位置转发 action 选中的 token。
  这条明确的 post-pop 走廊避免按静态 scope ID 永久跳过 cleanup，允许 loop 下次新进入。
- Replace block 的第一项操作就是 Replace，随后为上述 JUMP；用户求值/pack 在此前
  正常 CFG 中完成。Resume 可以在用户操作之后，但必须紧邻 JUMP。
- HandledContextRead 是**声明的抽象只读 primitive**：仅 READ 当前 context domain，
  行为 CONTROL/READ、effects_complete=True，唯一结果为无 identity/alias 精化的
  ReferenceValue（活动异常或合法 None）。它不执行真实 Python lookup/retain/回调，
  不把源 `sys.exception` 调用自动认定无效果；实际实现对应、保留/释放另证。

新异常的 implicit context/traceback 等真实状态处理必须在 Replace 恢复 ambient
之前完成。packet pack 本身仍只是 C0 纯协议聚合，不承担这些隐藏写操作。

## 4. 操作点栈与全 CFG 路由

从每 Region entry 的空活动 cleanup 栈推导；Enter push，Resume/Replace pop，
每个 block 入口栈必须与词法 cleanup ancestors 相容，entry 本身在 push **之前**。
多个前驱栈不一致、非 entry 侧入、未 pop 离开、重复进入仍活跃的同一 cleanup 均拒绝。
每条真实 CFG 边与区域出口都参与，INVOKE normal/raise 不例外。发散无出口允许，
不因此证明 total。必须先通过该单入口/coverage 门，再作本次 activation 的锚证明。

v9 还区分“已求值的语言目标”与“实际完成站点”：清理可以永不结束，或用新转移
替换原 Return/Raise。经过全部 C1 校验后，只有本 Region 的 interface.pending_argument
完整 case facts 所捕获的函数出口，可以声明而没有 Return/Raise 站点。闲置 pack、
未消费的额外 entry 参数或单独的 CLEANUP 标签均不够；原无 C1 图仍要求每个出口
有实际站点。该出口的 UseSite 查询返回空 tuple，不制造 producer，也不证明 total。

Route 根据 C0 从真实 CFG 推导的 pending port cases 选下一站；case 必须恰好齐全。
不投影 payload，边的相应参数必须精确转发该 selector 的 Value 和当前状态。
按当前 source lexical scope 从内向外扫描，使用该操作点的活动栈及 port 的真实目标：

1. protected P 的目标在 P 之外：下一站为关联 cleanup entry。
2. 活跃 cleanup C 的目标在 C 之外：下一站为 **C 的 Replace block**，不能重入 C entry。
3. 没有未完成义务：下一站为只含原 C0 PendingDispatch 的 block。

物理边也不能绕出仍受保护的 scope：进入下一个 cleanup 是唯一允许的 protected
离开边；post-pop 走廊仍留在 parent，余下义务由其中 Route 重新计算。最终 dispatch
仍受 C0 target_active / nearest-loop 约束，不是所有 cases 都能共享任意块。

外层 finalbody 内 inner cleanup 的 Fallthrough 可回外层 body，外层保存 token 仍活跃；
inner 新 Return 则须先 inner Replace，再 route→outer Replace，再到最终 dispatch。
local break/continue 若目标仍在 outer cleanup 内，不替换 outer pending。

## 5. 相对此次 entry 的 must-forward / must-fresh

不能用 port 集合、constructor 集合或静态 producer 相同证明 token 保持。
activation slice 是从 entry 可达的 cleanup 子树，切断离开和重新进入 entry 的边。
pending 锚是 entry.pending_argument；context 锚是本次 Enter.saved_context。其他
entry 参数为非锚，即使来自上次同一静态 Enter 的结果，也不能冒充本次保存值。

仅沿实际逐边 Use→BlockArgument 转发；INVOKE 的本地 Use 可复制，CompletionResult
不是复制。先算从锚可达的 OR 最小固定点，将其外节点固定 False，再求逐输入 AND
最大固定点至稳定。新 OperationResult（非锚）不是 copy；禁止 Resume 重新 pack。
此顺序同时排除无种子环和“交集后没有重新对 AND 闭合”的错误。

Replace freshness 使用同一 slice/entry reset：当前 entry 支配且位于 slice 内的
PendingCompletionDefinition 为新来源种子；所有 entry 参数和外部来源为 False。
AND 要求每条到达路径都是本 activation 的新 pending，且所有 case 目标都离开 C。
新 token 可以同 port/同 payload，但旧锚不能通过反向 phi 或旧 visit 混入。

此为保守全 CFG 判定，不使用未证明的分支相关性裁边；不能证明时拒绝该 primitive
接线，原 source/opaque 边界仍可表示。派生 facts 不另存一套输入或 producer。

## 6. 验收及版本

| Gate | 必需证据 |
| --- | --- |
| C1.0 | 独立设计审查、strict records、复用 FrameRules 和现 ControlEdgeReference。 |
| C1.1 | 全域后态、context producer/Use/私有边界、单入口及操作点 LIFO、全 CFG 出口覆盖。 |
| C1.2 | Resume copy 与 Replace freshness：同 port 异 payload、repack、反向 phi、loop 新 visit、嵌套及局部控制。 |
| C1.3 | INVOKE 部分写、ambient context read、正确 route→outer Replace、多 Return/Raise 路径与非 total。 |
| C1.4 | v9 codec、原 v1–v8 合同、query/公开 CLI 的 source/runtime/context/transform权限始终未证明。 |
| C1.5 | 独立反例审查、组件验收、冻结源与 fixture 哈希后单次全仓回归、报告/版本归档。 |

v9 承载上述六表、SAVED_HANDLED_CONTEXT 与 CleanupRouteTerminator。旧 v1–v8
禁止夹带这些新能力，既有无新能力 wire 保持。手工通用图只验类型/组合，不能计自动
源码恢复、真实 cleanup 执行或全程序优化。第一阶段完整性矩阵仍须逐项关闭；完成后
先停下来向用户讲解。初期设计参考及修订依据保留在 `model_cleanup_interfaces/review/`。

v9 的 CleanupRouteTerminator wire 额外带显式 `kind="CLEANUP_ROUTE"` 判别字段，
不进入 dataclass 构造参数。其余字段与 C0 PendingDispatch 同形，不能按结构或
是否声明 context domain 猜类型；旧 dispatch 编码不变。通用 record codec 只接受
本次调用显式传入的 exact-type tag 映射，不使用全局注册或运行授权。

公开查询为 `handled_context_domain(region)`、`cleanup_interface(scope)`、
`cleanup_action(operation)`、`cleanup_stack(block)`、`cleanup_pending_copies(scope)`、
`cleanup_context_copies(scope)` 及 `cleanup_route_steps(operation)`。入口栈与 copy
从规范 CFG 派生；未声明协议时 stack 为 None，不当空栈证明。route step 只说明
声明图中下一站 Enter/Replace/FINAL_DISPATCH，不授源码、运行或优化权限。

## 7. 本批实际证据与边界

组件门 `gates/m1_cleanup_interfaces.json` 的六项 criteria 全部通过，共243项检查。
手工通用图覆盖多状态 Return/Raise、嵌套清理、局部 Break/Continue、INVOKE 的
正常/异常后态以及无实际完成出口的发散清理。独立审查发现并修复了两个组合问题：
潜在语言目标被旧实际出口要求错拒，以及新 Route 子类遗漏显式 wire 判别字段。
修前证据、修后定向结果和组件报告保留在
`artifacts/experiments/b1_call_operands/model_cleanup_interfaces/`。

组件测试只验证所声明 IR 的类型、依赖和组合；没有运行相应 Python source、
恢复完整 source graph 或验证真实异常上下文。这不关闭完整 M1/M2，也不产生
LeWM 化简或加速比。

冻结实现 `0ea05e6` 的单次全仓回归为3,330 PASS、零失败/错误/跳过、三项原有
warning；428.510s，峰值RSS 1,028,484KiB。运行前后HEAD、clean状态、391个源文件
及22份fixture哈希相同；专属basetemp已移除。该结果是回归验收成本，不是workload
性能。组件与完整receipt、独立反例审查见
[证据目录](../artifacts/experiments/b1_call_operands/model_cleanup_interfaces/README.md)。
