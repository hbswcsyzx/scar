# C1 同步 cleanup：下一批实施合同

状态：**Proposed**。依赖 C0 formal gate 354 PASS（root 已报告），不替代该门证据。
本次仅只读设计；不运行测试、不改 tracked 文件，不实现 lowering/trace/backend。
第一阶段 M1/M2 尚未完成；C1 通过也只关闭下述声明接口及组合校验子集。

## 1. 事实基础与不能偷换的三个量

读取既有 `../language/results.json` 的唯一运行：CPython 3.14.7，19 PASS/0 FAIL，
`scar_imported=false`，时间 `2026-10-16T05:16:43.111361+00:00`。
语言证据 SHA256：`0e8c3eb1bc9bc849ae339df8de34db1ea9f5cf003bd867bfcb22474aee71ec00`。
19组不是 SCAR 图验证，也未穷尽 local jumps、traceback mutation、显式 cause、finalizer。
依据另有 `docs/model/PYTHON_CONTROL_PROTOCOLS.md` §4–5；本轮不重跑探针。

必须分别保留：(a) 已求值 pending token，(b) 当前共享/frame state，(c) ambient handled
exception context。pending Return 不表示没有活动异常：既有 ambient-handler 探针
明确 bare raise 可重抛 ambient exception；无活动异常时才产生 RuntimeError。
pending Raise 进入 finalbody 时成为活动异常；局部 handler 暂时替换它并在退出后恢复。
正常 cleanup 既不能把旧 world 恢复回去，也不能重新执行 return 表达式。

## 2. 复用 C0，新增最小 canonical 接口

保留 ProtocolValue/PENDING_COMPLETION/EXCEPTION_PACKET、两张唯一构造表、UseRole.PROTOCOL、
既有 ControlScope/Port、Successor/BlockArgument/StateAccess；不再存 kind/payload/world 副本。
新增 `ProtocolValueKind.SAVED_HANDLED_CONTEXT`；仍用现 ProtocolValue(id,region,origin)。
它是 Enter 从当前状态捕获的内部 context 保存值，不是 Python None、旧 world 或异常属性快照。
只能由下述 Enter 产生，并沿普通 CFG 复制；禁止 literal、region入口、call实参和region出口。
它可以随 INVOKE 完成边留在 caller，沿用 C0 已修正的逐 Use 边界检查。

```text
HandledContextDomain(region:RegionID, location:LocationID)
CleanupInterface(scope:ControlScopeID, protected:ControlScopeID,
                 entry:BlockID, pending_argument:ValueID)
CleanupEnter(operation:OperationID, cleanup:ControlScopeID,
             pending:UseID, saved_context:ValueID)
CleanupResume(operation:OperationID, cleanup:ControlScopeID,
              pending:UseID, context:UseID, continuation:ControlEdgeReference)
CleanupReplace(operation:OperationID, cleanup:ControlScopeID,
               saved_pending:UseID, replacement:UseID, context:UseID,
               continuation:ControlEdgeReference)
HandledContextRead(operation:OperationID, exception_result:ValueID)
```

`HandledContextDomain` 给既有 state 域声明用途，每个启用 Region 恰一行；可以指原 coarse
world，不能偷偷新造不相交 context world。所有嵌套 cleanup/read 解析同一行。
接口 scope 是 CLEANUP，protected 是同 Region 的 BLOCK，二者同 lexical parent、互不包含；
保护范围由 protected 子树给出。entry 属 cleanup，pending_argument 是该 entry 的 pending
BlockArgument；不重复 entry/state 签名。source 由既有 scope.source 取。
`ControlEdgeReference(operation, successor_index)` 复用已有精确边索引概念，不另存目标边。
Enter 是 entry 第一项协议操作，其 saved_context 必须精确为自身的 canonical result。
Resume/Replace 的 operation 是 ordinary state transition，紧接唯一 continuation 的
terminator；中间不得再运行用户操作。continuation 是实际 CFG 边，必须传递选定 token。
一条 operation 恰一个 action；IDs/enum/tuple/exact int 严格校验，没有 writable verified 位。

## 3. 状态动作的精确合同

Enter/Resume/Replace 必须具有 context_domain 上当前版本的 READ_WRITE StateAccess，
full_overwrite=False、effects_complete=False。before/after 只读该 access 的 Use/result。
保留原 frame 规则的未证 NO_FRAME_INTERPOSITION、可能不完成、不保证释放和未知副作用；
这些约束适用于内部保存/解绑动作，不能被拿来宣称 finalbody 用户调用不会抛异常。
其他声明域照常沿所有真实边传递；若当前只有 coarse world 就只使用这一既有域。

- Enter：pending Use 精确消费 entry pending；捕获进入前 ambient context 为 saved_context。
  若 pending 的实际 case 是 Raise，活动 exception 指向其 packet.exception；其他 case
  保持 ambient context。混合 case 是规则分支，不得将 Return 路径一律安装 None。
- 保存值只保留旧 handled-context 身份/栈链接；不冻结旧异常的 traceback/cause/context
  属性。恢复 old context 后，其对象仍具有当下状态中的属性，不回滚引用目标内容。
- Resume：消费当前保存的 pending 和本次 Enter 的 context，恢复 ambient context；
  continuation 必须转发同一 pending 来源与 action 后的当前 state，action 不产新 pending。
- Replace：同时消费 saved_pending、new pending 和本次 context，恢复 ambient context；
  continuation 只将 new pending 作为退出转移。old payload 解除保持/可能析构的效果
  仍在 action 的 state 依赖里，不是删除 old pending 数据边即可等价完成。
- finalbody 中已发生的写，包括 INVOKE 的异常后态，必须到达 Resume/Replace；
  不允许沿异常路径回到 invoke 输入 state，也不允许把 context 保存值当全部世界快照。
- HandledContextRead 对 context_domain 有当前 READ access；exception_result 是该操作的
  ReferenceValue 结果，表示活动异常对象或真实 None。不能从 pending.kind 推导其值，
  不能从 packet 的原 traceback 引用推导当前 handled context。

当前 C0 pack 仍只做无状态逻辑聚合；这些有状态动作不是 pack，不能放松
`ExceptionPacketDefinition`/`PendingCompletionDefinition` 的唯一 producer 约束。
control validator 对 action 的 pending Uses 新增**精确 typed 绑定**，其余逃逸仍拒绝。

## 4. token 保持必须是逐路径 must-forward，不是集合相等

最小反例：p=Return(port,x)，cleanup 中造 q=Return(port,y)，Resume(q)。
C0 `ports(p)==ports(q)`，但输出对象错误。即使 q=Return(port,x)，也不能以重新 pack
冒充“原 token 恢复”；这会掩盖重求值/retention 路由，且未来协议载荷可能有更多关联。
更强反例：分支保存 p/q，退出 phi 反着选择 q/p；两边 constructor 集合仍完全相同。
循环中同一个静态 constructor 可执行多次；静态 producer ID 相同不证明同次保存值。

推荐 checker 以本次 cleanup entry argument 为锚，在 activation 内证明 `must_copy(v, anchor)`：
直接锚为真；只能经真实 incoming actual→formal 传递；每条可行前驱都必须保持同一锚。
每个 branch/dispatch 的逐边对应保留；不能把两边来源先做无序集合再相等比较。
构造新 pending、外来参数、重进 cleanup 的新 visit 均不是此前锚的 copy。
循环使用 must 数据流（有限候选、交集收敛），允许 entry-anchor/self-backedge 这种合法 phi；
不能用简单递归“遇到环即真”，也不能因自环无种子而空证明成立。
仅在本 entry 支配、无跨 entry 重入的 activation 子图上证明；离开后重入视为新锚绑定。
保存 context 用同样规则锚定到 Enter result。分析结果只作派生事实，不持久化第二套 producer。
Resume 精确证明 pending/context 各自锚；Replace 的 saved/context 也需同证，new pending
则须来自当前离开 cleanup 的 abrupt 路径，不能取旧保存 token 伪装新异常/新返回。

## 5. 必需的 unwind 路由；保留 C0 最终 dispatch 合同

C0 PendingDispatchTerminator 强制 landing 为最终 port.block/exit shim，不能偷偷改成
可随意指向下一层 cleanup。因此新增独立的内部路由 terminator：

```text
CleanupRouteTerminator(pending:UseID, successors:tuple[CleanupRouteSuccessor,...])
CleanupRouteSuccessor(port:ControlPortID, block:BlockID, arguments:tuple[UseID,...])
```

它按原 pending port case 选择**下一站**，不投影 payload、不增加新完成类别、不调用用户代码。
case 集合仍复用 C0 真实 CFG 固定点，所选 token 沿边传递并按 case 收窄；端口标识不改。
validator 根据源 block 的 lexical scope、目标 port、保护范围与已匹配 action 重算：
有待运行 cleanup 时只能去最近一层 entry；没有时只能去普通最终 dispatch block。
该最终 block 只含 C0 dispatch，selector 必须 must-copy 路由所传 token，state 是当前值；
它的最终落点仍按 C0 规则核验。route 不允许任意 block 或跳过一层 cleanup。
允许把所有最终 case 共用一个 dispatch block；逐边 token/case 关系不能按 block 名去重。

维护从现 CFG 推导的有限活动 cleanup 栈：Enter push，匹配 Resume/Replace pop。
静态 scope 给义务顺序，action 给实际进入/退出；两者必须一致，不能用 dominance 猜词法。
保护区所有离开路径、cleanup所有离开路径、region出口及异常边都须参与覆盖检查；
只要启用该 Region 的 C1 合同，就不能仅检查“有 action 的几个边”。
未知 body 操作的 INVOKE 两边均保留；异常在当前 protected 范围被局部处理时不提前 unwind。
若 finalbody 发散，无完成边是合法的；有限返回路径必须完整配对，但不声称 total。

## 6. local loop、嵌套和恢复/覆盖的判定

- 新 abrupt 的最终目标仍位于当前 cleanup 子树内：只完成该内部控制转移，不 Replace
  外层保存 token。例如 `try:return x; finally: for a in xs: break`，循环后的正常完成
  仍 Resume(x)。continue 同理；此项19组证据未穷尽，需新的模型正反例而非声称已实测。
- 新目标离开当前 cleanup：先 Replace 当前保存 token，再逆序退出必须离开的外层
  cleanup；同一个 finalbody 不得再次进入。break/continue 仍采用最近活动 LOOP。
- 嵌套 `try/finally` 先内后外。内层正常 Resume 的 token 到外层 entry 原样再保存；
  内层 Replace 的新 token 成为外层 pending，不能复活更早的 token。
- 外层 finalbody 内的内层 try 正常 Fallthrough 只结束内层 try；外层 pending 仍活着。
  不可把任意 inner Resume 视为外层 Resume，不可拿 outer saved-context 结 inner action。
- finalbody 内暂时 handler 安装/恢复 context 必须精确嵌套。C1 可检验显式声明的
  context 保存/恢复接口；自动选择 handler、匹配异常和 except* 路由属于 C2，不能省略后
  直接将整段 handler body 标为已解释。未声明的 context 变更不可获得恢复精度。

## 7. 异常 packet、bare raise 与 traceback 的边界

pending Raise 安装的是活动异常身份；pending Return 路径的 bare raise 必须读 ambient。
该读经 HandledContextRead 接当前 world，随后正规化/重抛操作也读取当前异常属性状态；
无活动异常时的 RuntimeError 路径是新的 Raise，不能 Resume 旧 Return。
C1 的 packet 仍由 C0 两个 canonical Uses 构造；获取/更新 exception 和 traceback 的
实际操作在 pack 之前，有必要的 StateAccess/INVOKE，不得让 pack 自己偷偷做动态 lookup。
新异常的 implicit context 链维护必须发生在恢复 ambient context 之前，使用当时活动异常；
随后 Replace 再恢复保存的 context。不能给所有新异常固定 `__context__=old_pending`：
pending Return 也可能有 ambient 异常，自引用/显式 cause/suppression 也有各自协议。
正常恢复保留原 pending/packet 的传播引用；不据此断言 exception.__traceback__ 未变。
19组没有证明 traceback 内容/修改、显式 cause、异常环、所有 finalizer 时序；实施须保持
这些状态依赖和未证明边界，不能把对象 identity 相同写成 traceback/context 等价。
C1 不靠 `cleanup_verified=true` 推出任意用户/native/trace interposition 可忽略。

## 8. 分步实施与有限验收门

1. **Records/codec：**在现 control records 上增接口/action/context协议kind/route，
   strict字段和owned Uses/results；新能力用 ProgramGraph下一版本（预计v7），保留v1–v6。
   单独新 cleanup validator，不改旧 SourceProgram/profile/inventory 默认能力。
2. **Provenance：**先完成 pending/context 的相对锚 must-copy；正例覆盖分支/loop/已知callee
   INVOKE仅本地转发；负例覆盖同port异payload、新pack、反向phi、前次loop/context。
3. **组合校验：**context当前域、Enter/Resume/Replace与route、全出口coverage/LIFO；
   正例覆盖五种incoming completion、内外cleanup、局部loop不覆盖、nested else owner。
4. **公开验证：**对手工小core夹具做structural验收，queries派生锚/路由及明确条件；
   公共解码必须拒绝篡改，固定 source/runtime/extraction/transformation 权限仍为未证明。
   不用这些夹具冒充自动源码图；19组仅独立语言oracle，M3才接原始源码自动规则。

必须拒绝：换同port token/packet；旧state；保存context来自另一Enter/旧visit；
Return路径强清ambient；新Raise先恢复context再构链；少一个exceptional unwind；
跳外层cleanup；重复执行已退出cleanup；local break错误Replace；完整输出前漏Resume。
必须允许：mutate返回对象但保持引用；有副作用的正常清理；失败调用的部分后态；
finalbody无限循环无出口；多个互斥出口分别消费同一静态保存token；后续循环重新进入。
既有19组中的返回/覆盖/嵌套/ambient/context恢复/异常部分写应各有对应图反例；
不能只测试固定flags或计数。未覆盖的语言细节保持界限，不以本合同关闭整个 M1/M2。
