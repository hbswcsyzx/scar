# C2 主规格独立自洽性复审

2026-10-17。**只读设计审查；不是产品验收，不宣布 C2.0 关闭。**
审查对象：`docs/M1_RESUMPTION_INTERFACES.md`（本次166行版本）；对照现同步
core/C1、原 composition review，以及 exception/delegate-context 的独立见证。
没有修改 tracked 文件，没有运行测试、capture、LeWM 或 GPU。

## 1. 有界结论

**未发现本轮主规格的明确自相矛盾，也未发现它宣称 C2 已实现。** 下述变化可接受，
原审查 artifact 中与它们不同的建议不是本次规范：

- §2:37–47、§3.1:91–94：ResumeInput 提供 gate 后、Attach 前的共享状态；
  初入/恢复 landing 的 Attach 才唯一产生本次 caller token。不存在两份 token
  producer，也没有必须把协议 token 塞入 Python formal 的理由。
- §2.1:54–62、§3.1:101–106：logical CFG 保留 C1 activation/freshness；
  availability roots 切断未保存值；attachedness 另外描述真实每次 drive 上下文。
  三者是同一规范端点的派生判断，不要求把 C1 逻辑栈当物理 caller 栈。
- §3.1:96–99：无用户回调、completion-preserving 的 context intrinsic，与
  真实 retain/release/lookup 的独立效果边界并不冲突。不能把真实操作自动当 intrinsic。
- §3.2:108–118：accepted 请求可能只驱动 delegate；父 body 不 Attach、不消费其
  suspension generation。这与 drive epoch 单独前进相容。普通 next/send 与直接
  throw/close callback 的 context 区别，与本机四组见证相符。
- §4:122–131：不直接沿用旧 FrameExit 的邻接/释放规则，避免让 Detach 与它同时
  要求紧邻 terminal。最终 release 移入明确 driver 阶段仍须有新 profile；当前没有实现。

状态措辞核对：第3–5行、139–144行、158–166行均明确规格工作/字段待审/无产品实现。
64–66行只报告假想 cut 设计探针；161–162行也没有把观察数当断言测试或完整验收。
**本次没有要求改正文的具体错误行。** 第164行“本批 C2 仍是规格工作”与上述边界一致。

## 2. C2.0 仍 OPEN：代码前必须冻结的连接不变量

以下是主规格已经指出、但尚未精确到 records/graph 检查的内容；不是要求增加另一套图。

1. **Start/current-state 路线**（42–47、139行）：Create 保存引用/environment，
   不能保存 creation-world 作为首次 body state。Start 必须引用本次 driver gate
   后态，接入 body entry；Attach 消费该前态并产生 context 域后态。恢复 landing
   同样逐域使用 ResumeInput，禁止用旧 StateVersion 的 SavedUse 填任何共享域。
   domain 未被 Attach 写入时仍转发本次 current-state，不新造一个“全域后态”。
2. **两种状态机不能相互代替**（54–62、101–106行）：Suspend 后 logical C1 栈仍
   active，physical attachedness 必须 Detached。恢复 landing 首次 Attach 恢复
   body 片段；它不是 CleanupEnter。旧 pending/context/fresh 值只沿实际 SavedUse
   →新 BlockArgument 保持，不能由 ResumeInput/新 pack 冒充。
3. **caller token 的唯一来源与允许 uses**（80、91–105行）：冻结 token 类型、
   Attach 结果位置、Attached-block 对应参数，以及 Detach 消费位置。只允许受控
   forwarding/Detach，不得经 call/容器/一般返回/跨挂起保存逃逸。互斥路径各消费一次
   可以合法，不能用 SSA use 数=1 替代全路径配对。下次 drive 必须得到新 token。
4. **frame context 片段的实际路线**（78–94行）：冻结 initial INHERIT、Detach
   的规范片段结果→Suspend 保存 Use→landing formal→Attach 输入；保留 C1 保存锚
   内的相对继承含义。不保存上次 visible exception 当 owned 片段，不给同一 Value
   两个 producer。正常路径与 injected exception 的 landing/handler 接口都要明确。
5. **driver→body ingress/host outcome**（13–25、110–118、143–150行）：每个实际
   body ingress 必须接唯一允许的 Start/temporal case；拒绝和 delegate-only 分支
   无父 body edge/ResumeInput。delegate 发生当前写后才恢复父体时，ResumeInput 来自
   delegate 当前后态，不是 drive 刚开始的旧 gate-state。epoch/generation 各自引用
   实例当前 lifecycle 状态。body Suspend/Return/Raise 与 host NORMAL/RAISE 的映射
   按方法规则连接，不依赖同名标签；取消 requested/accepted/injected 分开。
6. **terminal/release 分期**（104–106、122–131行）：明确哪些是 body outcome、
   Detach/handoff、driver release/finalizer 与 host adapter 操作。Detach 后 body 只
   规范转发不妨碍 driver 的真实释放/失败，但不能由 phase 标签偷漏 StateAccess 或
   callback 的 normal/raise 部分后态。终止不等于所有异步资源 ready。

相应最小反例：creation 后 caller 写 global；yield 后 NumPy alias 外部写；漏保存
旧局部在第二次 cut 后被 merge 使用；旧 caller token 跨两次 drive；finally 中
pending Return/鲜造 replacement 跨 yield；delegate.throw 返回 item 无父 body 入口；
delegate 写状态后抛回父体；首次非法 send 和取消仅请求无注入。当前都只是验收要求。

## 3. 证据和当前 C1 的关系

现 `cleanup_validation.py:245–281` 从规范边逐点推栈，`:354–394` 做原锚与私有
context 校验；`cleanup_forward.py` 仅认识现同步 Use→formal。C2 要扩 temporal
参数遍历及捕获例外，不能因规格相容就说现 validator 已支持。旧同步 capability
仍须维持旧规则；`frame_validation.py:120–164,227` 的有限同步 profile 也不自动扩大。

`language-exception-context-probe.json` 支持每 drive INHERIT/owned context 的区别；
`language-delegate-context-probe.json` 四组支持所测自定义 Python iterator 的 fast
path 差异。它们未证明全部解释器/版本、C delegate、实际 finalizer、source 到 IR、
实例排他/代次或 C1+C2 产品接线。主规格已保留这些限制；本审查不进一步扩张结论。

结论：可继续精确冻结 C2.0 字段；上述 OPEN 连接关闭前，不能计作接口实现、完整
模型验收、自动建图或任何优化能力。
