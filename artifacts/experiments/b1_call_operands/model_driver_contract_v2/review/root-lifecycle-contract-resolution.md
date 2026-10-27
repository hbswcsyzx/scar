# root driver v2：限定修正复核

2026-10-18。复核 `docs/M1_DRIVER_CONTRACT_V2.md` 当前快照 SHA256：
`f657b6e2cb32e884a389df10386e95e0486393ea16746e24b5cab97d544e0e92`。
行号仅对应该快照。旧审查及其问题保留，不覆盖原报告。
本轮只读文档并写本 ignored artifact，无新实验、测试、采集、git或产品编辑。

## 修正结论

1. **原 R3，D1 outcome 私有边界已明确。** §3.4 L179–183 要求 frontier 源完整且
   不重复，各 landing 彼此不同且各有唯一对应 incoming；签名从该源实际 Uses 派生。
   这排除了先合流再借另一源/另一 visit 猜 commit。L190–192 保留空 frontier、发散、
   不跨 Suspend 以及同源可由不同 Drive 引用。就本次审查范围，D1 可按此实施。
2. **原 R1，失败后的 session 清理可表达。** §4 L212–214 允许
   `DriveOutcomeRef | ControlEdgeReference`；L222、225–226 明确包含 NORMAL/RAISE，
   source 失败边可触发 request 清理，update 自身 NORMAL 才承诺 post，RAISE 保留
   partial states。未把 helper 失败反称 body Raise/Finish，限定问题已消除。
3. **原 R2，窄 drop 与真异常 wrapper 已分开。** L228–231 明确普通 finalizer 的
   unraisable、条件适用且完成时保留 pending，不因 callback 捏造可传播 RAISE；
   真 lookup/close/分配/adapter 可独立或整体 INVOKE，不能套窄规则吞错。该修正与
   现 `FrameRules` 一致；L231 未声称 TerminalFrameRelease 已有完整规则字段/覆盖域。

## D2 仍 OPEN 的准确边界

§4 L196–198 已明确“候选、未冻结”，列出 typed no-body 成功合同、逐边完成锚、
phase/current-owner 转发、重复终态引用放弃；L223–224 也未将占位类型称作已发布 API。
这足以避免将 D1 连接字段的可实施性误报为整个 D0/C2D 关闭。

后续仍需在 D2 冻结：

- NormalEdgeRef(operation) 解析到该 INVOKE 唯一真实 NORMAL；CommitRef 定位唯一
  canonical commit overlay，并验证**本路径当前**相位，不只是 operation 存在/支配。
- NoBodyFinishRule 的封闭 TERMINATE_BEFORE_ENTRY 语义、实际 still-created/current
  guard、witness 后到 commit 间无失效 callback，以及 no-body 成功端口的准确关联。
- 各 lifecycle StateAccess 的形状与覆盖、callback effects 全域、同一 frame bundle
  的重复放弃检查、SessionUpdate/host adapters 的 family 方法表。

仅一个机械拼写提醒，不构成 D1 阻塞：§4 L206 的既有
`ControlEdgeReference(operation, successor)` 若抄入代码，应复用现
`structured.py` 的真实字段 `successor_index`，不要另造同名类型。D2 仍为示意字段，
本轮不将它当已冻结 API 或要求现在实现。

## 最终限定结论

**所审三项修正已覆盖原具体问题；D1 可开始实施与独立验收。D2 lifecycle 仍 OPEN。**
此结论仅为当前文档的有限设计复核；没有签核 D1 产品实现、完整 D0/C2D、M1、
自动 source/runtime 对应或第一阶段整体完成，也没有任何优化/性能新结论。
