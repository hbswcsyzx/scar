# root driver v2：有限 lifecycle 合同复审

2026-10-18。所审快照：`docs/M1_DRIVER_CONTRACT_V2.md`，SHA256
`14ac0691fdf418b4bac54b11e3bf1cc291eac7011082460d6016a23abfe038c8`。
下列行号只指该快照。只读产品/文档与既有报告，无新实验/测试/联网、git或产品编辑。
范围为 §3.4、§4 及其必须联动字段；不是完整 C2D/M1 签核。

## 1. 结论及阶段边界

§3.4 的 `(drive,source)`、first frontier、source 派生签名、LocationID 对应、
saved 排除和空 frontier 与已验收 C2B/frontier 一致。**D1 可以先冻结这些连接字段，
并加入下述 outcome landing 局部条件。§4 当前仍是 D2 候选，不足以冻结完整生命周期
validator；不能把 D1 设计通过记为整个 D0/C2D 关闭。**

表中 AWAIT/HOLD 与 ASYNC_YIELD/请求完成的区分、close 再 Suspend 不得 Finish、
Created-close 无 body、traceback 保活、native flag 不等于续体终结均与既有证据相容。
没有新 Observed；八组只证明已归档 CPython3.14.7 有界 case，不补全所有 family 方法。

## 2. 需要改的具体点

### R1：SessionUpdate 来源排除了真实失败边（L189–191）

`DriveOutcomeRef | NormalEdgeRef` 无法表示 Gate/normalize/delegate helper 的 RAISE
之后 ABANDON/COMPLETE 请求并交出 partial states。失败后清理是正常模型需求，
不能为适配类型把失败冒成 NORMAL 或 body Raise。

最小修正：`source: DriveOutcomeRef | ControlEdgeReference`。后一项明确允许实际
NORMAL/RAISE edge，必须匹配本路径当前边/owner/request；source RAISE 不授 body
终结。SessionUpdate 自己若为 INVOKE，**其 NORMAL** 才承诺 post，**其 RAISE** 仅
交真实 partial states；区分 source 的异常与 update 自己的异常。
无 body outcome 的失败更新不需要 NoBodyFinish。

### R2：窄 reference-drop 与可传播异常 wrapper 仍混合（L192–200）

“有 callback/raise 的 release、session helper 使用真实 INVOKE”应分开说明：

- callback 本身不意味着向外 RAISE。窄 frame reference-drop 可以复用普通 Operation
  与 `FrameRules`：NO_FRAME_INTERPOSITION=UNKNOWN，若适用且完成保留 pending，
  finalizer_errors=UNRAISABLE、effects=UNKNOWN、MAY_NOT_COMPLETE、NOT_GUARANTEED。
  未细分 callback effects 时覆盖 Region 已声明全域、effects_complete=False。
- explicit close/lookup/分配/host adapter 的 wrapper 若能真正向外 raise，采用普通
  INVOKE 两完成及真实后态；不能把 wrapper 的 RAISE 吞成 unraisable，也不能把
  `__del__` 的普通 unraisable 错误当 host RAISE。

`TerminalFrameRelease` 当前没有 rules/窄动作合同。D2 冻结时至少选择：显式
`rules: FrameRules` 固定合同，或在唯一 owning DriverRule 给出同样精确窄动作语义，
不可只说“保留 channel”。旧 FrameExit 有限 profile 不因这一新记录被自动放宽。
释放后不保证目标死亡；保存 pending 只保留其引用/控制含义，不冻结 exception attrs。

### R3：D1 的 outcome 私有 landing 要变成机械规则（L163–175）

§4 L196 要求 commit 位于私有 landing 首操作，但 §3.4 尚未定义“私有”：
建议 D1 就要求每个 BodyDriveSuccessor.block 恰有该 Drive 此 source 的一条 incoming，
不同 source 使用不同 landing；块参数逐槽来自本边实际投影/forward。
同一个 source 可以由不同 Drive 分别引用，各自 landing 独立。

否则 Return 与 Suspend 在同一 landing/普通 backedge 合入，可使未来一条静态 commit
看似有 `(drive,source)` 却不对应当前路径。D1 **不必实现** commit，但应保留可组合
的准确边界。空 frontier 合法，无 landing/完成；不得为方便补假出口。

## 3. 未定义别名的最小精确定义

这些属于 D2 候选定义，D1 不必先新增一批空记录。

```text
NormalEdgeRef = ControlEdgeReference
CommitRef = OperationID
NoBodyFinishRule(evidence: ProviderFactReference)
  固定合同语义：TERMINATE_BEFORE_ENTRY（不添加可写 verified/status）
```

- NormalEdgeRef 构造仍 exact ControlEdgeReference；graph validator 验证 operation
  是同 driver 的真实 INVOKE、index 命中 NORMAL CompletionSuccessor。不是“某个
  dominating NORMAL 的文本 label”，不靠 bool 字段宣告 normal。
- `TerminalFrameRelease.completion: OperationID` 足够：该 ID 必须准确索引唯一
  BodyOutcomeCommit 或 NoBodyFinish overlay。前者 source 必须 Return/Raise；
  同 Region、同当前 owner、同路径当前 commit 相位，不接受仅 dominance。
  如保留 BodyOutcomeCommitRef/NoBodyFinishRef 两 wrapper，它们仅各含一个
  `operation: OperationID` 并做同样解析；不要增第二张 ID→producer 表。
- NoBodyFinishRule 的 Fact 是声明版本条件/guard 的主源定位，不是真实适用证明。
  该语义要求 witness helper 的成功路径检查当前 owner **仍处于可无 body 终结的
  状态**，并停在无用户回调的终结提交边界；normalization callback 推进过 owner 后
  不能继续借旧 CREATED 判断。NoBodyFinish 位于该边独占 landing 首操作。
  具体 native 哪个 guard 满足这一点仍由 owning DriverRule/来源验收，不能仅凭
  Fact locator 或任意 helper NORMAL 自动证明。已 opaque 包含引用释放的调用不能
  再加一个真实 terminal release。

以上三项是最少可编码定义；主源适用、版本条件并非构造器能够自动证明的内容。

## 4. 可机械验与必须补的具体关系

**D1 可机械验：**target 对应 frontier 完整/唯一；source 签名按真实 Uses 派生；
私有落点与 BlockArgument 类型/槽；body 状态按 LocationID、额外 driver 域逐边
current forward；私有 saved 排除；所有 Use ownership 与独立端口；gate corridor。
L171 effect-scope 只可报告声明，不得升级成 body 完全不写额外域的事实。

**D2 必须另补（不是笼统“待证明”）：**

1. 所有真实 incoming 的 outcome→commit 当前相位；Return/Suspend 合流不能借另一
   source；loop 回访必须重新 gate/outcome，静态同 ID 不复用旧终结锚。
2. commit 状态 access 的精确形状：各域从 interface 派生，索引或按 LocationID 查
   唯一 StateAccess；非 full_overwrite、current before→真实 after。若会掉引用/回调，
   不能放进 callback-free commit。
3. terminal drop 必须在本路本次 finished commit 后；Suspend/request COMPLETE/host
   RAISE 不足；本 bundle 不重复放弃。traceback 后续 decref 是另一普通操作。
4. session 对 source 和自身 NORMAL/RAISE 的两层关系、当前 request/body 引用匹配，
   不回滚 partial state；请求完成与 continuation FINISHED 分开。
5. 按 method/family 的 host 适配表：尤其 raw async request `.send` 的
   StopIteration(item) 与外围 await 得 item 两层，不从 body kind 直接造宿主结果。

无新语言事实需求。只要 D2 以上关系仍列 OPEN，D1 的字段/连接可以独立推进；
本文不签核完整 lifecycle 或声明实际 source/runtime 适配已实现。
