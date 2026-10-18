# D2：SessionUpdate / terminal reference-drop 最小合同审查

2026-10-18；依根代理通知，D1 基线已验收推送 `cc44e14`。**本报告为 Proposed，
不是 D2 产品实现或验收。**只读 scar/docs 和既有 ignored 证据；本轮只在本目录
增加报告及一个3组 stdlib 见证，未改跟踪文件/旧证据，未跑 pytest/LeWM/GPU/安装/git。

## 1. 当前模型能直接复用什么

- `validation.py:454–495` 已逐操作维护 current state，并拒同一操作同域重复 access；
  因而不用另存 access index、before/after world 或第二份 lifecycle 版本。
- `validation.py:518–539` 的 INVOKE 使用 owned invoke_arguments；未知 effects 的
  NORMAL/RAISE 均须产生各域真实后态。RAISE 后可能已有写，不能回退旧态。
- D1 每个 Drive source 已是私有 landing；从原 source Uses 派生 public 签名。
  `driver_validation.py:301–309` 已验证 frontier 完整及独占 incoming。
- C2B `resumption_validation.py:96–132,251–269` 的 Attach/Detach 是窄 intrinsic，
  仅切换当前 context；Detach 必须紧邻 body handoff/终端，不能塞进真实 drop/callback。
- C1 `cleanup_validation.py:154–162` 的动作保留所有已声明域的未知 callback 写；
  C1 activation/saved context 与 C2B private frame/caller 不得借 D2 普通 helper escape。
- `FrameRules` 是独立固定条件合同，可以复用；旧 FrameModel 的同步 root/ENTER/
  单 world/EXIT 邻接 profile（frame_validation.py:177–190,218–237）不能照搬为 D2。

所审文档 SHA256：
`M1_DRIVER_CONTRACT_V2.md=4a943058b1accf60e8be708c1770a958d914e77ef772a82f37065b296ca57f0a`；
`M1_DRIVER_INTERFACES.md=4ce49de650d58d77dc78a5d98184b57739b28a1f721d68b31eb54c6da4b32a79`。

## 2. SessionUpdate 的准确含义及最小字段

建议只把它作为**对该操作自身后态的有类型合同**，不要用它存请求的全局历史。

```text
SessionUpdate(operation: OperationID, request: UseID, body: UseID,
              post: SessionPost)
SessionPost = HOLD | COMPLETE | ABANDON
```

实际规则版本从唯一 owning DriverInterface.rule 取得；若后续需要每 helper 的原生
细分规则证据，可定位现有 ProviderFactReference，不能按函数名套模板或自动授证明。
request/body 是该 op 的独立 owned Reference Uses，允许 same Value alias，不能
用 LocationID、相同 code、两个 producer 集合替代实际逐路径引用关系。

### 2.1 后置条件绑定何处

**路径 A：无 callback metadata + 真实 drop 分开。**SessionUpdate 普通 Operation
用 StateAccess 完成必要域 READ_WRITE、WHOLE、非 full_overwrite；每域恰一条，
域由 interface.lifecycle 派生。post 绑定这些 access.after 的**准确版本组合**。
它不掉旧引用、不调用用户代码；真实 retain/drop/callback 留在后续普通操作/helper。
后者若可能写这些域，原 post 不自动继续适用于新的当前版本。

**路径 B：原生 helper 不拆开。**SessionUpdate 指向真实 INVOKE，request/body
必须在 invoke_arguments。NORMAL post 绑定 NORMAL completion 中按 LocationID 派生
的真实 BlockArgument；RAISE 保留 partial current states，**不承诺 post 成立，亦不
承诺 post 尚未发生**。若 helper 有 callback，只有其版本合同确在 callback 后
重建/复核该后置，才可在 NORMAL 声称 post；一条 NORMAL 边本身不够。
无法给出此保证则保留普通 typed opaque INVOKE，不附加虚假的 SessionUpdate 后置。

两种路径均可表达，不强制拆 native，不把 UNRAISABLE 当无 callback。路径 A 窄
metadata 的效果闭合与路径 B unknown effects 是不同合同，不共用 effects_complete。

post 的精确抽象建议：HOLD 表 R↔B 的活动 session 继续，不授下一次 body admission；
COMPLETE 表本 request 协议不可再成功驱动且不再持有活动占用，**不表示 request
不再强引用 body**；ABANDON 仅表本活动占用已撤回，不额外断言 request 已 terminal、
body 已终结或资源已释放。各 family 的对应仍须封闭版本表，不能从枚举名猜实现字段。

### 2.2 canonical edge 与 current state

- helper 自己的成功/失败由其实际 CompletionSuccessor 决定；normal projection 不
  捏造 Reference 或 State producer，复用 D1 normal_result/current SSA。
- prep/Gate/delegate 的 RAISE 也能作为 request 清理的真实入口，不能只收 NORMAL
  cause。应区分“触发清理的 source edge”与“清理 helper 自己 NORMAL/RAISE”。
- 不用所有普通 request 写都携带一个旧 body outcome；entry/prep 的实际 StateAccess
  也合法。只有需要依据 body/no-body completion 的语义规则才要求相应来源关系。
- post 沿 canonical edge Use→formal 的准确版本复制可保留；穿过未知 write/callback
  的新 StateVersion 就失效，除非另有明确保持/重建合同。不能以“helper NORMAL”或
  “仍然同一个 request Object”补回。合流要求所有实际 incoming 均满足同一谓词及
  当前 request/body 对应，不能只比较 origins 集合。

## 3. TerminalFrameRelease：操作、引用与完成的连接

推荐最少字段：

```text
TerminalFrameRelease(operation: OperationID, owner: UseID, rules: FrameRules)
```

真实完成锚从 canonical CFG 派生（§4）；不再重复一份可写 completion/source 列表。
若根代理保留显式 completion 字段，它只能是待核对声明，不能自动授 release 资格。

- owner 为实际当前 body Reference Use；完整操作消费当前全部必要状态，输出真实
  after versions。coarse world 下未知 finalizer/unraisablehook effects 按 Region 全部
  已声明域保守 READ_WRITE，WHOLE、非 overwrite、effects_complete=False。
- 必须有本路径当前 BodyOutcomeCommit(Return/Raise) 或 typed NoBodyFinish 成功
  锚，同一 owner 经准确 Use→formal 关系传递。Suspend、request COMPLETE、host
  RAISE、任意 helper NORMAL 都不能替代 body 终结。
- 在所测 CPython3.14.7 terminal 路径，body Detach/终结标记先于可重入的 frame
  clear；Created-close 无 body ingress 也有终结与绑定引用 drop。元数据 commit
  不隐含 callback/drop；drop 不替代 commit。真实调用已 opaque 包含它们时不再执行。
- 此记录的最窄可实施粒度是**owner 的终态 frame 持有关系的聚合放弃/转移**，不是
  “把所有 frame locals 对象 free”。traceback/frame object 可能接过这些引用；本记录
  不保证对象死亡、资源 ready、callback 已全部发生或操作一定完成。
- native closed 标记、frame/保存引用仍存在、request 占用、实际 body 指令是否在执行
  必须分别建模；不能用一个 body-phase enum 或一次 inspect sensor 读数覆盖全部。
- body rebind/DEL、不同 slot/bundle 的独立 drop、traceback 后来放弃最后引用都
  继续用其真实位置的普通操作；不能因 owner/frame 相同就一律判“重复 terminal drop”。
  递归展开聚合 frame clear 内部的 slot drops 是同一操作的内部表示，不重复计 effects。

### 3.1 窄 FrameRules 与 raising wrapper

复用固定 FrameRules：NO_FRAME_INTERPOSITION=UNKNOWN；若条件适用且操作完成，
保留 pending completion；finalizer_errors=UNRAISABLE，effects=UNKNOWN，
MAY_NOT_COMPLETE、release=NOT_GUARANTEED。它保留返回/异常引用的控制含义，
不冻结异常 attrs、可变返回对象内容、RNG、外部状态或 callback 的写。

窄 drop 可以是普通非 terminator Operation；普通 `__del__` 异常与 unraisablehook
是内部实际 effects，不凭 callback 人造向外 RAISE。若 wrapper 包含真正可能抛出的
lookup/close/分配/adapter：可拆为真实 helper + 窄 drop，或整体保持普通 INVOKE。
后者不用窄 rules 吞掉真实异常，NORMAL/RAISE 都保留全部当前后态；其失败也不撤回
已经执行的 body commit 或已经掉的部分引用。不得全局把 release 设成纯/no-raise。

payload/pending 若跨普通 drop 仍由现 SSA 引用活着；若跨 INVOKE 则用独立本地 edge
Use→formal 精确保持，不能把私有 context/pending 当任意未知 helper 的普通参数。

## 4. 合流来源：显式候选 tuple 与从 CFG 派生的比较

合法例：Return 和 Raise 各在 D1 私有 landing commit，再合流到同一 release/helper。
单一 `completion:OperationID` 或 `source:DriveOutcomeRef` 不够；不能因此拒绝通用合流。

| 方案 | 必须验证什么 | 判断 |
| --- | --- | --- |
| `sources/completions:tuple[...]` | 每个实际 incoming 的 current anchor、owner copy、状态与清单逐路相符；NONE 路径不得漏。tuple 不是许可，不能只比集合。 | 可行，但与 CFG 可派生事实重复，仍需同一分析。若保留只作 expected-source 声明。 |
| 不存 tuple，从规范 CFG 派生 last-commit alternatives | 在 operation 点保留每个真实 anchor 与其对应 owner/当前 incoming 的相关关系；合流逐个候选检查。 | **推荐。**共享完成点自然表示，不新造 source/producer 图或 request 历史机。 |

建议有限、按锚的局部算法：

1. core/C1/C2B/D1 验证后，使用规范 ordinary/INVOKE/BodyDrive CFG。终态 commit
   是新的局部种子；NONE 表某路径没有合法锚。BodyDrive actual outcome 边已唯一，
   NoBodyFinish 只从其 typed helper 的真实成功边种子，不猜一般 NORMAL。
2. 每个 commit 在其操作点种下其真实 owner Use.value。沿后续实际 edge 的 Use→formal
   copy 传播，在新 commit/新的 body admission 边界切断旧 visit；其他 Reference
   producer 不是 copy。可复用已有有种子 OR-LFP→AND-GFP 的 must-copy 机制，但输入
   必须限制到**当前 anchor 的路径切片**，而不是把所有来源 union 后比较。
3. 合流保留 `(anchor, 对该路径的 owner-copy relation)` alternatives。对 release
   的每个实际 incoming 均需：有 terminal/no-body 锚，owner 是该锚本路径的 copy，
   当前状态来自本路径最新 versions。Return/Suspend 混合不能借 Return 锚给整块授权。
   所有这类结果都是可重算的 validator/query facts，不写回对象/current state。
4. 完成来源是本次控制执行的历史因果，**不等于当前 session post**。后者按精确
   state-version provenance 单独检验；未知写后默认失效，直到 typed 操作重建。
5. 对明确“聚合 owner-frame relinquish” primitive，可在切掉新 commit/admission
   的操作点 CFG 中检查：同一次 aggregate drop 后不得再到另一个同 aggregate drop。
   这是一项局部可达性/切片检查，不是通用 request phase/许可历史状态机。不同 owner、
   不同 selector/bundle、traceback 后续持有关系不能由这个规则误合并。

若要对**任意部分 frame bundle**自动判重复，现 Location+Footprint（WHOLE/INTERVAL/
UNKNOWN）不足以给出对象内精确 selector/ownership 身份。本门不得假定同 owner 就
同 bundle：应将该细化列 OPEN，或只把上述明确聚合 primitive 纳入一次性检查，
其他真实 drop 留普通操作；不能宣称已经覆盖任意 bundle 的等价/重复证明。

## 5. 本门至少需保留的正反例

1. AWAIT→HOLD 与 ASYNC_YIELD→COMPLETE，body 都 Suspend；反例把 request 完成当
   body Finished/drop。COMPLETE 后 request 仍强持 body 的例子也必须合法。
2. metadata COMPLETE→drop callback 改 R→helper NORMAL；不得给最终新版本继续盖
   COMPLETE。另一个 helper 在 callback 后重建 COMPLETE 则可声明其 NORMAL post。
3. update 写 COMPLETE 后抛错：RAISE 后该写保留，不能宣告“没有完成写”或退旧 world。
4. helper source RAISE→request cleanup→update NORMAL/RAISE，两层边不互相混淆。
5. Return/Raise 各 commit 后同一 release 合流合法；Return/Suspend 混合却 release
   必拒；phi 交换 B1/B2 actual、仅集合相同也拒；无种子 loop 不造锚。
6. 同次 aggregate drop 无新 commit 回边再 drop 拒；另一个 slot/bundle/traceback
   放弃不因“同 frame”误拒；新的真实 terminal commit visit 可另开局部锚。
7. terminal drop callback 看到 closed/caller，nested drive 与 callback 写保留；
   反例先 callback 后 closed，或 host adapter 交出 drop 前态。
8. Created-close 无 body而有绑定引用drop；body内部DEL在Attached触发；traceback
   保活到handler后才drop。这三种不能统一到相同位置/完成锚。
9. ordinary finalizer 抛错进入 unraisable、外层 pending 保持；显式 close/adapter
   真 RAISE 不能吞。callback 发散允许，不以缺 host completion 造假结果。

## 6. 真实语言反证及证据范围

**本轮首次且仅一次 stdlib probe：3 PASS、0 FAIL、exit0**，CPython3.14.7，
torch_imported=0、scar_imported=0。准确命令/版本、原事件在同目录
`session_release_probe.py/.json/.log`，没有保存对象/frame/exception/traceback。

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/review/session_release_probe.py
```

Observed：①`COMPLETE写→decref callback重关联HOLD→helper NORMAL`，最终 HOLD；
②`COMPLETE写→helper RAISE`，最终 COMPLETE、world=1；③finalizer写后抛错→
unraisablehook，外层 NORMAL 返回 KEPT、world=1。前两例是合法普通 Python helper
反证，**不是声称 CPython 内置 asend 的 native phase 可任意写或已实现其 adapter**。
它们反驳通用“helper正常返回就保留先写post”及“异常就没写”的规则。

旧八组 CPython3.14.7 的真实 body/close/coroutine/asyncgen 见证本轮未重跑：
`model_driver_interfaces/review/lifecycle-witness.json` hash
`a363bdf0904b7108ece75b02a7d317262033cbddb4f9782e07686cbda3d07f85`。
它们已观察 terminal finalizer closed/caller、Attached DEL、traceback 保活、
Created-close、request/body 生命周期不同，以及重入/分配/unraisable 后外层结果保持。
只主张原有有界断言，不补充为全 family/runtime 证明。

另只读核对了本轮另一 agent 的原始 `lifecycle_probe.json`（hash
`39f010353a01c8b0ed1b048e8ee26114ef28b4406528da4c18fba079bb2e2cb2`）：
asyncgen 在 finally 再 yield 后首次 aclose 抛 RuntimeError，第二次 aclose 抛
StopAsyncIteration，最终 inspect 仍报告 AGEN_SUSPENDED，body_log 仅 finally-enter。
**不能误写成第二次已 CLOSED，host exhaustion 不证明续体已消失。**该 inspect
传感器本身也不是完整 machine state；此为另一 agent 的原始观察，不计入本轮3组。

主源依据复用归档：
[CPython3.14.7 clear_gen_frame](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L1835)、
[frame 所有权转移](https://github.com/python/cpython/blob/v3.14.7/Python/frame.c#L99)、
[Created-close](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L358)、
[asyncgen request](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L1637)。
本轮没有新联网复核，不将不同 Python 实现的具体回收时序视为相同。

## 7. 冻结前明确 OPEN / 阻断

- **B1：**HOLD/COMPLETE/ABANDON 对具体 request family 的封闭后置规则及 callback 后
  保障条件；不能仅靠 enum/NORMAL 边。字段可表达，真实 native 适用仍须独立来源门。
- **B2：**多锚合流/current-owner 逐路派生算法与 first/no-body 种子合同；只比 tuple
  集合或静态支配不够。推荐派生方案，但须实际实现与共享 release 正反 fixture。
- **B3：**TerminalFrameRelease 聚合 primitive 的精确范围、FrameRules 固定条件及
  unknown 全域效果；任意 bundle selector/ownership 细化尚未解决，不能乱判重复。
- **B4：**后置按 StateVersion 绑定/未知写失效/显式重建的验证接口，以及 host adapter
  最新 partial state 和 unraisable/真raise 分路；不能让历史 completion 锚授当前资格。

这四项未冻结前不应发布“D2通过”。本报告未新增 detector/backend、未更改 D1、
未给 runtime/source/transform 权限；generic建图与性能不在本轮成果内。

新证据 SHA256：

```text
3210653be341d4a373758858e0cc72acfd3568c5633282ddf9404b17179f9e6f  session_release_probe.py
23cf7fa00002d00eedff33234692e501ec58464ad1d0bee396c5ed00a419818f  session_release_probe.json
23cf7fa00002d00eedff33234692e501ec58464ad1d0bee396c5ed00a419818f  session_release_probe.log
```
