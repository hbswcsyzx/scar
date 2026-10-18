# D2 body commit / no-body finish 的独立 core 设计复审

2026-10-18；任务基线为已验收 D1 `cc44e14`。只读源码、合同，不改产品/tests/docs 或 D1
封存证据；未启动 pytest/LeWM/GPU、CPU 实验、联网、安装或 git。本报告全部新 API/
算法均为 **Proposed**，不是当前产品能力，也不宣称完整 D2.0 已冻结。

## 1. Observed：当前代码实际提供什么

- `drivers.py:263`–300：BodyDrive 的 instance/S/可选 session 与 state/resume inputs
  只引用现 owned Uses。`:311`–339 的 source、landing 去重已有 typed records。
- `driver_validation.py:301`–309 校验 target 的 exact first frontier 与每个 outcome 的
  私有 incoming；`:325`–383 校验 gate 唯一邻接、角色精确转发、全 D 后态。当前没有
  BodyOutcomeCommit/NoBodyFinish 的完成相位检查，不能把 D1 通过说成已发布生命周期。
- `driver_flow.py:42`–65：结果只取真实 Suspend.exported/handoff 或 Return/Raise.values；
  source 类型派生不是执行/总终止证明。C1 被截留的 ExitPort 不是实际 body completion。
- `validation.py:453`–495 已按操作点检查每个 StateAccess.before 为 current，再由实际
  access.after 更新；`:496`–514 的 reference/selector 检查不能凭普通 owner 引用推导
  精确 alias。INVOKE 当前状态继续从真实 completion formals 定义（`:516`–539）。
- `resumption_validation.py:175`–203、`:251`–289 已要求当前 Detach→Suspend/Return/Raise、
  精确 frame 保存与 private context 不逃逸；driver 不需再 Attach/Detach 或读取这些私有值。
- `frames.py:46`–77 的 FrameRules 固定为条件未证、effects unknown、可能不完成、
  普通 finalizer 异常 unraisable、释放无保证；它没有把这些条件变成通用 runtime 证明。
  `frame_validation.py:62`–66、`:119`–135、`:156`–192 是同步、单 coarse world 的有限
  root-body source profile。它的 FrameExit 需紧邻该 body 实际 Return/Raise（`:217`–237），
  不能直接复用为 resumable driver 的 terminal release validator。
- `cleanup_validation.py:154`–163、`:377`–406：C1 保守 current domains/private context；
  `cleanup_forward.py:122`–139 的 copy/fresh 沿真实逻辑路径，Suspend 不意味着 cleanup
  activation 结束。D2 不可借 commit 弹出 C1 栈或把 saved pending/context 作为普通参数。

## 2. 本轮决定与最小候选字段

```text
DriverLifecycle(region: RegionID)                         # opt-in marker
DriveOutcomeRef(drive: OperationID, source: OperationID)   # 引用现唯一 source edge
BodyOutcomeCommit(operation: OperationID,
                  outcome: DriveOutcomeRef, instance: UseID)

CreatedCloseTest(operation: OperationID, instance: UseID,
                 scheduler_request: UseID, effective_request: UseID,
                 session: UseID | None, result: ValueID)
NoBodyFinish(operation: OperationID,
             precondition: ControlEdgeReference, instance: UseID)
```

这些是普通 Operation 的声明合同，不增加 Value/world/许可或第二份 actual 列表。
规则与生命周期集合 L 只从 owning DriverInterface.rule/lifecycle 取得。BodyOutcomeCommit
**删除 session 字段**：只发布 body continuation，不重复 request/session 更新。
CreatedCloseTest 的组合角色字段仍须与 root D2.0 草稿共同冻结；这里先确定真实非raising
BRANCH 的机制，不因写出字段而宣布所有 family 的实际 guard 已对应。

### 2.1 迁移 marker 必要

D1/v11 已允许无 commit 的合法 graph。仅因新 validator 装入便要求每条 D1 outcome 有
commit 会破坏其原合同。建议新增 typed DriverLifecycle(region)，不是 verified bit；
要求该 Region 已有 DriverInterface，且不复制 rule/L。启用后，完整 frontier 每条真实
outcome 都需对应首 commit，所有新增 D2 元数据也必须处于已启用 Region。

新 wire capability 检测 marker/所有 D2 records（下一版本可为 v12），旧 v11 拒绝新能力。
无 marker 的旧图保持 D1 校验与能力边界；仅提升读取器版本不授 D2 结论。仅以“存在一个
commit 自动启用”无法检查完全漏写 commit 的情况；以 schema 版本全局强开又会误伤旧图。

## 3. BodyOutcomeCommit：source、owner、current state 的唯一连接

1. outcome 必解析为现 BodyDriveTerminator 的实际 successor，且 source 属于 D1 已验证
   first frontier。使用 `(drive, source)`，不能只用静态 body Return site；同一 source
   可以被不同 Drive/动态发生使用。每个启用的 source edge 恰一个 commit。
2. commit 必为该 outcome 私有 landing 的第一个 op；前面不可插 callback、release、
   user code 或状态写。不同 source 先各自 commit，之后允许普通合流；不把两条 outcome
   先合流再按 source 集合猜发生了哪条。重复 commit 无法同时占据同一首位置。
3. instance 是 commit 自身 owned REFERENCE Use。其 Value 必为本次 Drive.instance 的
   原 Value，或 landing formal 且其 source-edge actual 为 Drive 独立 owned forwarding
   Use，Value 恰等于 Drive.instance 的 Value。两种连接都必须由 core dominance/实际边
   允许；不能从 BodyDriveResult 产生的同类型 payload 猜 owner，不能用 constructor 集合。
4. 当前 source kind 派生唯一 post：Suspend→SUSPENDED_AT_THIS_SOURCE；Return/Raise→
   CONTINUATION_FINISHED。不存另一份 kind/closed bool/generation number，不从 host
   exhaustion、inspect sensor、异常名称或 native ag_closed 位派生 phase。
5. commit 是小型无 callback、无 retain/drop/lookup 的 ordinary state intrinsic。只做
   该 body 的 publication/phase store；不得在这里完成 request 或丢弃 frame 引用。
   source 的 private frame 已由 Suspend.saved 定义，commit 不重新打包/搬运这些实际值。

### 3.1 本轮明确采用非空 W⊆L，不写全 L

令 W 直接由 commit.Operation.accesses 中实际 WRITE/READ_WRITE 项的 location 派生。
要求 `∅≠W⊆L`；publication 写须 READ_WRITE、非 full_overwrite，并生产自己的现
StateVersion OperationResults。只读 access 可使用 L 内当前域；不得借此触及 L 外新域。

**不强制 W=L。** 细分 body 与 request 域时，commit 可只写 body 域，完全不访问 request
域；没有实际写的域不制造 after，后续边继续按 core 转发 current。一个 coarse world
涵盖两类字段时，单个普通 RW 也不表示把 session 关闭或完成。

validator 核对普通非call/nonterm shape、精确 owner/state owned Uses、实际 accesses、
恰好这些 after results 及最新 before；小 intrinsic 的 complete effect-scope 是条件
合同。它证明的是“该声明把这些真实 state writes 连到此次 body publication”，不是
从新 StateVersion 或 op 标签证明具体 body 字段真的已更新。实际字段/owner/location
对应仍需 source/native 规则和后续 M1 selector/denotation 证据；写全 L 也补不出此证明。

coarse WHOLE access 允许 reference=None；**不强求 access.reference=instance**。
否则未知 targets/selector 的真实 owner 会触发现 core incomplete_alias，或诱使建模者
伪造精确 alias。owner 用独立 canonical Use 连接，state access 继续保守覆盖。将来有
实际精确 selector 时按 core 检查，可声明指向该 owner；相同 LocationID 不证明身份。

## 4. NoBodyFinish：真实 Created-close 条件不能变造异常

我最初考虑 NoBodyFinish 本身为 guard+mark INVOKE，以 NORMAL 为唯一 witness；
**本轮撤回其通用形式。** 实际非Created close 可能继续合法 body 路径；为了方便验证而
给条件 false 人造 RAISE，会改变真实 CFG/可观察行为。只有真实存在会raise helper 的
具体分解才能使用它自己的异常边，不能把这种形状作为通用要求。

### 4.1 替代：typed read/bool → 真实 BRANCH → 真边首 mark

- CreatedCloseTest 为封闭 profile 的无 callback ordinary READ：读取当前 lifecycle
  state 和真实 owner/request 端口，产生唯一真实 DataValue(bool) OperationResult；
  result 必为该 producer 的 bool，不接受 Literal(True)、未知 helper NORMAL 或任意
  同类型值充当已验证条件。只有本条 typed predicate 的条件语义才支持 finish。
- 普通 BRANCH.condition 的 owned Use 必直接引用 result；test→BRANCH 之间无其他 op。
  两条 successor 都是真实 CFG；false 可去 final gate、其他 no-body reply 或真实失败。
- NoBodyFinish.precondition 指该 BRANCH 的实际 true edge（规范 true case），其 landing
  为该边私有目标且首 op 恰为本 finish；不引用“某个 normal helper”或任意 branch 名称。
  test 到 mark 无 callback/state write，避免 created 检查被推进 body 的回调过期。
- NoBodyFinish.instance 从 test 的原 instance Value 或 true-edge 的精确普通 forward
  formal 复制；不从新的 result 猜身份。自身写域同样为实际 StateAccess 的非空 W⊆L，
  发布 CONTINUATION_FINISHED_BEFORE_ENTRY；不 mark RUNNING，也不虚造 body outcome。
- 普通 BODY 路线 effective_request 必与固定 S 是真实 copy；ASYNC_REQUEST 中 S 是本次
  scheduler/send 输入，effective_request 通常是当前 R 内容中的 latent CLOSE。两者
  独立端口，不能因同 RAW 类型替换。session 为当前 R；读取关联可独立或位于 typed
  helper 内，不强制独立 AssociationRead。原型的最终 exact role 转发规则仍需共同复核。
- predicate 的语义包含当前 created、有效 close 路线、当前关联/phase 的必要条件。
  BODY 可在外部 RAW 边界上检查 CLOSE，不强迫 local pack；ASYNC 按 R 当前 latent 与
  S 的真实 step 规则检查，不错误要求 scheduler S 本身 kind=CLOSE。实际实现可能在
  方法入口/上游路径已固定部分条件；这些对应由版本路径证明，不增添物理 guard。

它是有具体 inputs、bool、true/false 边和 state mark 的条件接口，避免任意 NORMAL helper
冒领 finish；但 predicate annotation 不是已恢复源实现或已证明其 heap 判断正确。
其他 no-body 情形（已closed回复、delegate-only、request-only）不自动用 CREATED_CLOSE；
需要其他规则时另核实际条件，不能因 host StopAsyncIteration/StopIteration 就制造终结。

## 5. 相位、合法合流与共享 release

以上两个 source 局部 corridor 可机械确定此次 commit/mark 的来源与初始 post；不需要
U/A 历史位、跨 CFG permit 或 caller 提供 before/after world。失败/发散不造成功锚；
body 完全发散则 frontier 空，启用 marker 也不强迫有 commit 或 no-body finish。

在 commit 后可有真实 branch、session/helper/release，再合流；两个 FINISHED 来源
或 body terminal 与合法 NoBodyFinish 来源共享一个 release 是合法建模目标。不能要求
release 有唯一静态 commit ref、同 constructor 或无普通合流；也不能仅比较锚集合。

下一步可实施的检查框架是：沿 canonical ordinary CFG 从 entry 做操作点 MAY LFP，
传播**相关 tuple** `(实际 completion 锚, 当前 owner carrier, 当前 phase, 当前 state路径)`；
每条真实 edge actual→formal 同时重命名 owner/state，不能分别 union 后交叉配对。
branch 保留每个 tuple；release 要求所有 incoming tuple 的实际 owner 与其 owned Use
匹配、来源确为 FINISHED 且当前状态为该路径最新。Suspend tuple 不授终态 release。

但以下细节本轮仍未闭合，因此不宣称完整 D2 相位算法已可发布：

1. shared release 的字段是候选锚 tuple 还是全由 CFG 派生、如何表示允许多条静态来源，
   以及 owner 多 aliases/多个 phi 同时转发的精确相关域；origin set 不足。
2. 普通 callback/未知写后，历史 completion 仍发生过，不能简单抹去；它也不自动证明
   当前 frame 内容/占用未变。需要区分历史因果锚与 current publication/可drop对象关系，
   并绑定实际 helper/guard，不能再犯历史 A 被失败清除或历史 A 当当前资格的错误。
3. 重复/reentrant terminal drop 的 profile：什么是真实幂等放弃、什么是重复销毁，以及
   pending 保持、可能不返回、wrapper 真 raise/部分后态的组合。不能仅凭 use/site 数
   宣布只运行一次，不能把 unraisable finalizer 错造成必传播 RAISE。
4. 对具体 publication 的 per-field location、instance/frame occurrence、guard 原子性
   与外部 interposition 的对应仍是证据门，不是静态 tuple 或新 state 能证明的事实。

## 6. 合法路径 / 最小反例

| 声明路径 | 结论/规则 |
| --- | --- |
| Return 与 Raise 各自私有首commit，随后 merge→同一 release | 应保留；release 按每路锚+owner+最新state相关检查，不强迫单锚。 |
| Suspend(AWAIT) commit 只写 body 域；request session 继续 HOLD | 合法；W⊊L，不因 host 返回把 request COMPLETE。 |
| body Suspend 后 host 报 RuntimeError/StopAsyncIteration，或 native closed 位为真 | 仍不能变为 FINISHED 或授权 frame-drop；以实际 source/typed no-body 条件为准。 |
| d1 的 source 与 d2 的 owner 在两支反选，但锚/owner集合相同 | 拒绝精确 source/owner 或相关 tuple 对应，不能靠两个集合相等通过。 |
| CreatedCloseTest true→finish；false→gate→BodyDrive | 合法真实非raising分解；不捏造 false exception。 |
| 任意 normal lookup 后贴 NoBodyFinish、bool literal true 替代 typed test | 拒绝：无实际 typed predicate/true edge/current owner corridor。 |
| test→callback(next(B))→branch true→finish | 拒绝短corridor；需要用回调后状态重新真实测试。 |
| Created-close mark后放弃已绑定 refs，finalizer重入 | 必须先有 FINISHED mark，再用真实 drop/current effects；不执行 body Attach 或C1。 |
| C1 finally Suspend 保存 pending/context→driver commit | 只发布暂停；不 pop cleanup，不公开 saved，不代替真正 terminal。 |
| 把同步 FrameModel 全profile直接套给driver | 拒绝范围混淆；其单world/同步root/每ordinaryop映射约束不是通用D2。 |
| 旧 v11无commit graph读取新版 | 继续D1合法；没有DriverLifecycle marker不自授D2也不被偷偷收紧。 |

## 7. 交付边界

Observed 仅为本报告读取的现 D1/C1/C2B/frame 源码事实；没有新运行结果或语言传感器
实测。Proposed 为上述 marker、source局部commit、真实Created-close分支与验证规则。
source/runtime 未证项包括实际callable/version、字段/owner-selector、实际创建/代次、
回调/引用放弃顺序、全部async request与family协议。D2.0字段及共享锚算法还需共同
闭合；本报告支持继续独立实作准备，不关闭完整D2或整程序建模分母。
