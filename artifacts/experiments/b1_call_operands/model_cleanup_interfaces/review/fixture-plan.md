# C1 synchronous cleanup fixture plan

**Status: Proposed; API 尚未冻结。** 只说明通用手工 IR 验收形状，不表示产品或
语言规则已实现。以 `NEXT_CLEANUP_IMPLEMENTATION.md` 与 `UNCERTAINTY_ADDENDUM.md`
为准；复用原 C0 graph/Uses/StateVersion，不另造状态图。

## 共用搭建规则

- 所有 fixture 以 `shared_pending_graph()` 为骨架：Entry 分支构造真实 pending，cleanup
  有 pending BlockArgument，最终 C0 `PendingDispatch` 才投影 payload/落到 exit shim。
  内部 `CleanupRoute` 按 port 选下一站、不投影 payload；scope/actions/interfaces 只声明
  关系，不让 block 名或 operation label 提供语义。
- 每个测试 Region 至少有两个已有 StateLocation；加入 context、共享对象内容和一个外部
  域（如 file/RNG）。每个 Enter/Resume/Replace 都消费所有当前版本、逐域 `READ_WRITE`
  产出新版本、后继传全向量；`effects_complete=False` 仍保留可能回调写/未知域边界。
  不以不同 LocationID 宣称互不别名；能力不足时保留 coarse world 或拒绝精确多域图。
- Return payload 始终是同一 ReferenceValue/原 token；对内容的写通过该引用对应位置的
  `StateAccess` 推进内容域，不把 pending identity 等同旧内容 snapshot。RAISE 使用
  packet 引用 exception/traceback；HandledContext 是另一条当前状态协议。

## 最少四种 fixture

| Fixture | 核心构造与正例 | 由同一 graph 派生的关键负例 |
| --- | --- | --- |
| `cleanup_resume_multistate_graph()` | 同一 protected 区中预构造两个同 RETURN port、不同 payload 的 token p/q 与一个 Raise token；分支各自选 token 到 cleanup entry。Enter 保存当前 handled-context并推进每域；cleanup 通过 Return ref 写对象内容，随后 Resume 原 entry token，当前多域后态到 shared PendingDispatch。 | Resume 用另一同 port/different payload token；以相同 payload 重新 pack；两条分支的 `p/q` resume phi 交叉对调；任何一域仍传 old world。分别应因相对 entry-anchor must-forward 或完整后态失败，不能只比 port/constructor 集合。 |
| `cleanup_replace_invoke_graph()` | Enter 保存原 Return。finalbody 的不确定 `INVOKE` 有 distinct normal/raise completion；raise completion 显式给出部分写后的每域 state，随后构造新 ExceptionPacket/Raise token 并 Replace。normal path Resume 原 token。Enter、两种 action均按向量推进全部域。 | RAISE completion 接 INVOKE 输入 old state、Replace 仍发旧 Return，或先恢复 context 再建 implicit exception context；应拒错 payload、状态版本或操作顺序。 |
| `nested_cleanup_graph()` | outer Return 进入 outer cleanup；其内部普通 inner try/finally 以 Fallthrough token 进入 inner cleanup，inner Resume 回 outer cleanup body，outer Resume 原 token。另一支在 outer finalbody 的 inner finally 中产生新 Return：先 inner Replace，再路由到**同一 outer activation 的 Replace**，最后进 final dispatch。 | inner Resume 越过 outer cleanup；new Return 直接打到函数 exit；Replace 路由回 outer entry/重复运行 outer finalbody；用 outer saved-context 填 inner action。scope 树、must-forward anchor、活动 cleanup 栈分别提供拒绝点。 |
| `local_loop_cleanup_graph()` | outer Return token已保存，outer finalbody内部有真实 LOOP；loop 内 Break/Continue 到本 loop after/header，局部完成后普通 fallthrough 接 outer Resume。Break/Continue 不替换外层 token，全部 route/current states仍到 Resume。 | Break 被送作 outer Replace，Continue 落到外层 loop/错误 cleanup，或局部正常退出丢弃 outer token。另造最近 LOOP 错目标负例。 |

这些是四个通用结构，不按 LeWM 函数/业务名分类。可由共享 builder 产生不同 state
向量与 typed ports，避免每个反例复制整套图；正例仍需是 core-valid、可被 strict codec
往返的完整图。每次 graph mutation 只改一条真实边/Use/StateAccess，使失败发生在
cleanup validator，而非 dataclass 构造器或早期 core CFG gate。

## 覆盖对应与验收顺序

1. **Core + codec**：每个 pending/context/result 有唯一 typed producer；普通 StateAccess
   before/after 与 INVOKE completion current state 精确；shared dispatch case 集从 CFG 推导；
   错 Use、旧 world、缺 exit 在进入 C1 checker 前即拒绝。
2. **锚保持**：相对每次 Cleanup entry 参数，逐边 `must_copy` pending/context；真实 CFG
   branch/backedge 的 incoming→formal 顺序逐一核，不以无序 producer 集合或 port 集合代替。
   新 token 只准作为当前 abrupt 离开路径的 replacement；禁止重入污染同一个锚。
3. **全路径路由**：保护块所有出口及 cleanup 所有 Resume/Replace/发散路径都参与
   coverage/LIFO；inner→outer 恢复/替换与最近 LOOP transfer分别检验；`PendingDispatch`
   只作最后 shim，不取代内部 `CleanupRoute`。
4. **多域/ambient**：Enter/Resume/Replace 每域都有当前态到新态；Raise pending 安装活动
   exception，Return pending 不强清 ambient；裸 raise 从当前 HandledContextRead 取值。
   Invoke 失败可能已有写入，异常边不得回滚；引用相同不得冻结被写对象的内容版本。
5. **权限边界**：结构和 query 只证明静态 interface/action/CFG 关系；保留
   `NO_FRAME_INTERPOSITION`、来源/runtime/callback/finalizer、异常属性及未建模域为条件/缺口。
   不设输入可写 `cleanup_verified`，不把手工 fixture 说成 source lowering 或执行证据。

建议先共享 C1 收尾/多域 builder，四个 fixture 函数逐一交 core validator 和 C1 checker；
反例最少各保留 token、edge、state 三类。Python 3.14 control probes 限定语言预期，
现有 C0 只提供 static pending/packet/CFG 固定点。M1/M2 仍需逐语法 protocol/replay，
实际 source↔graph 和 runtime effects 留后续阶段，不能由这些手工图关闭整门。
