# D0：outcome → commit → reference drop → host adapter

2026-10-18；只读产品基线 `499d708`。**Proposed，字段待根代理冻结；不是产品验收。**
本轮只写本 ignored artifact；未改产品/docs/tests，未运行 git、测试、采集、Torch、
LeWM/GPU或新语言探针。依据现 core/C1/C2B/frontier 和既有 CPython3.14.7 八组见证。

## 1. 收敛选择与必须区分的状态

采用根代理已选择的结构：普通 **Gate INVOKE → 私有 NORMAL landing 中唯一 BodyDrive**；
所有 admission 后态由 NORMAL CompletionResult 产生；identity 沿独立 owned Use →
formal → Drive actual 精确转发。拒绝走 Gate RAISE，无 body 边；不引入 permit Value。
Gate 之外的 lookup/normalize/delegate 仍可回调和嵌套驱动，不能限制为一次外部调用
只有一次 ingress。具体 gate 配对见同目录 `permit-session-proposal.md`。

至少保留四项独立事实，均不是新的通用节点类型：

1. **body 续体**：本次执行中 / 已保存可恢复续体 / 已终结。Suspend 不等于终结。
2. **native 协议标记**：例如 asyncgen 的 `ag_running`、`ag_closed`；不可用一个
   `CLOSED` 枚举代替全部语义。close 失败且 body 再 yield 时，协议 closed 标记
   与仍存在的暂停续体可以不同；具体顺序必须按版本路径描述。
3. **request/session**：某请求 HOLD、COMPLETE、ABANDON，与 body 续体状态分开。
   asyncgen AWAIT 后原请求仍占用，ASYNC_YIELD 后 item 请求完成但 body 仍暂停。
4. **拥有引用及最终化**：终结 body、放弃/转移 frame 引用、对象最终化、资源 ready
   都不同。异常 traceback 可以保留已经终结的 frame/locals。

`DriverInterface.lifecycle: tuple[LocationID,...]` 统一声明请求/body 的必要生命周期域；
每动作不再重复保存 domains/before/after。允许同一 coarse world 覆盖多个 owner；
相同 LocationID 不证明 owner/request 同一或独占。精确 owner/selector 仍需后续接口。

## 2. BodyDrive 必须提供的唯一源连接

现 `ProgramIndex.body_outcomes(body,start)` 和 `resumption_flow.py` 是唯一 frontier
派生源，止于第一次 Suspend/Return/Raise，不跨 temporal successors。
新 BodyDrive 的**每条真实 outcome successor** 最少需有 `source: OperationID`：

```text
BodyDrive successor: source = 一个真实 frontier OperationID
                    block  = 独占 outcome landing
                    arguments = 既有 actual / completion 投影
```

source 必须属于指定 Start/Resume root 的 frontier，且每个结构可达 source 恰有一个
对应边；空 frontier 允许 Drive 不返回，不伪造 completion。边的 payload/state types
由该 source 的规范 Uses 派生，不能再存第二份 outcome/type/producer 表。
每条边的 body 状态由该实际 outcome handoff/terminal Uses产生；driver 额外域用
该边独立 Use 转发当前值，不能伪装成 body producer。按 LocationID 匹配，不能 zip。

这是一项 D1 必需连接：只有 `ControlEdgeReference(drive,index)` 而无源 Operation，
就无法可靠派生 Suspend/Return/Raise 或排除把后续 generation 的 Return 冒充本次结果。

## 3. 最小附加 records：只索引既有端口

以下是可实施候选字段；`rule` 复用既有 `ProviderFactReference`，指版本化主源规则，
由 owning interface 另声明其实际 callable/receiver/实现对应。fact 存在不证明真实适用。
所有 ID/enum/tuple/int 严格 exact，index 非负且拒 bool；没有 verified/authorization 位。

```text
BodyOutcomeCommit(operation: OperationID, owner: UseID,
                  outcome: ControlEdgeReference, accesses: tuple[int,...])
NoBodyFinish(operation: OperationID, owner: UseID,
             accepted: ControlEdgeReference, accesses: tuple[int,...], rule: Fact)
SessionUpdate(operation: OperationID, request: UseID, body: UseID,
              source: ControlEdgeReference, post: HOLD|COMPLETE|ABANDON, rule: Fact)
TerminalReferenceDrop(operation: OperationID, owner: UseID,
                      committed: OperationID, rules: FrameRules)
HostOutcomeAdapter(operation: OperationID, source: ControlEdgeReference,
                   payload: UseID|None, rule: Fact)
```

没有新增实际参数表。Use 字段必须属于该动作 Operation；普通 helper 的参数引用
`call_arguments`，INVOKE 引用 `invoke_arguments`，其输入、结果和状态仍由 core 定义。
不同端口必须独立 UseID；same Value alias 合法，不能复用同一 UseID 充当两个端口。
不为 owner/packet/return value 另建 producer，不把 raw THROW 强制变成 packet。

### 3.1 BodyOutcomeCommit

- owning op 为 callback-free 的窄 bookkeeping 动作，位于 Drive 每个私有 outcome
  landing 的第一操作。只有该实际 source 决定后置：Suspend 发布本次已保存续体；
  Return/Raise 将续体标记终结。后者先于可重入的 terminal frame reference drop。
- `accesses` 是该 op 既有 StateAccess 的索引，按 owning interface.lifecycle 逐域
  覆盖，READ_WRITE、非 full_overwrite；coarse 域保持内容依赖，不猜精确对象 footprint。
  before 是当前态 Use，after 是该 op 的真实 StateVersion result；不新增 snapshot。
  这是保守域覆盖，不声称每个域的实际字节均改变，也不凭该 op 完成 request。
- native 标记/引用交换若可能 decref/callback，不能藏在此 callback-free 合同：
  保留真实 helper；将可回调引用处理独立。无法合法切开 native 调用时维持 opaque。
- owner 必须是该 Drive 实际 owner 的 must-forward 引用；仅 type/code/Location 相同
  不足。Suspend 不自动清除跨 AWAIT 的 request 所有权或协议 running 标记。

### 3.2 NoBodyFinish

- `accepted` 只可指向**明确声明 TERMINATE_BEFORE_ENTRY 规则的 helper 成功边**，
  例如实际 still-created close；同路 private landing 第一操作，后态索引同上。
  它为无 body 的终结提供锚，不伪造 Attach/Detach/Return/Raise。
- closed/exhausted、rejected、delegate-only 不默认获得此角色；普通 helper NORMAL
  也不够。Created-throw 只能按版本及当前分支另述，归一化回调可能已推进同 owner。
- 不需要 no-body preserve-current 的空 commit：不入 body 的路径继续其真实当前态。
  “本步未消费续体”不代表恢复外部调用前的状态或抹掉 prep/delegate callback。

### 3.3 SessionUpdate

- request/body 分别为实际当前引用，域从唯一 owning interface 派生；不以同一个
  world 或 body code 证明关联。当前关联仍由普通读取及最终 Gate 重新检查。
- `source` 是本路径真实 body outcome 或版本化 no-body/prep helper 的实际边。
  NORMAL 才承诺本次声明的 HOLD/COMPLETE/ABANDON；RAISE 仅交出真实 partial current
  states，不承诺更新已完成。ABANDON 不意味着 body 已终结或已无其他拥有者。
- 纯内存标记可用普通 StateAccess op；设置/移除关联若会释放引用而回调或失败，
  用普通 helper INVOKE，其 NORMAL/RAISE 均保存所有必要当前状态。不要为方便把它
  固定为纯 metadata；session 更新和 terminal drop 的相对顺序按具体 native CFG，
  不能一律规定 SessionUpdate 先于/后于全部释放。

### 3.4 TerminalReferenceDrop

- 仅描述窄的“放弃/转移该 body owner 的终结 frame 引用”动作；`committed` 必须
  是本路径、本次 BodyOutcomeCommit(Return/Raise) 或 NoBodyFinish，owner 精确同路。
  Suspend commit、request COMPLETE、host RAISE 都不能授权终结 body frame 的释放。
- 复用 `FrameRules` 的固定条件合同：NO_FRAME_INTERPOSITION 仍 UNKNOWN，
  若适用且完成则保留 pending completion，finalizer 错误为 UNRAISABLE；允许不完成，
  effects UNKNOWN、物理释放 NOT_GUARANTEED。不直接放松旧 `FrameExit` 的邻接规则。
- 此窄动作复用现 frame transition 的普通 Operation + 保守 READ_WRITE 当前域，
  不另造异常 continuation：普通 `__del__` 错误及 unraisablehook effects 在其中。
  若包住 lookup/显式 close/分配等可能真的向外 raise 的 wrapper，须拆出上述窄动作，
  或把整个 wrapper 维持普通 INVOKE 的 NORMAL/RAISE；不能套此 rules 吞掉真实异常。
- 未细分未知 callback 域时覆盖本 Region 全部已声明状态域（不只 lifecycle）；
  effects_complete=False。结果是最新状态，不证明 callback 一定返回、对象死亡、
  Python allocation 消失或 GPU ready。后续路径不能退回 commit 前 world。
- body rebind/DEL、求值栈丢弃、traceback 最后引用消失仍在真实位置作为普通操作；
  不需要终结锚，不前移/后移，也不再做一次 BodyOutcomeCommit。

### 3.5 HostOutcomeAdapter

- 不是新 core control primitive：仍为普通 helper/INVOKE；附加 record 仅定位协议角色。
  `source` 为同路径原 body/no-body/失败边，payload 为该 helper 的准确 owned Use。
  真实 payload 经边 → formal → helper actual 连接；转换后的异常/值由 helper 真实
  results/completion 产生，不能在注解里捏造 StopIteration/StopAsyncIteration。
- helper NORMAL/RAISE 到 driver host exits 都交出最新状态；转换可能分配、触发
  callback 或失败。宿主 RAISE 不反推 body Raise，不撤回先前 commit/session 更新。
- 需要继续保持具体 API 边界：async request 原始 `.send` 的 StopIteration(item)
  和外围 `await` 接收到 item 是两个 adapter；不能把它们合并为一个 NORMAL 返回。

## 4. 后置条件矩阵（类型完整，具体方法规则仍须版本化）

表中“终结”只指 body 续体；方法可在入 body 前/后产生独立 native 标记写。
`R` 表宿主 RAISE，`N` 表宿主 NORMAL，不把异常通道当 body 完成证据。

| 实际路径/本步源 | body commit | request/session 与引用处理 | 宿主适配 |
| --- | --- | --- | --- |
| generator YIELD/DELEGATION Suspend | 发布可恢复续体 | 无 terminal drop；可能保留 delegate | next/send/throw 常为 N(item)，具体 method 由 rule |
| coroutine AWAIT Suspend | 发布可恢复续体 | 非 terminal；不能认为外围任务完成 | 原始 drive N(scheduler payload)，外围 await 继续 |
| asyncgen AWAIT Suspend | 发布可恢复续体 | 当前 request HOLD，竞争 request 可被 gate 拒绝；无 terminal drop | 当前 request 原始 drive N(scheduler payload) |
| asyncgen ASYNC_YIELD Suspend | 发布可恢复续体 | item request COMPLETE；body 仍暂停 | request 原始 `.send` R(StopIteration(item))；外围 await 得 item |
| body Return | 终结，先标记再 terminal drop | session 按当前 method 完成；frame 引用可能转移/被保活 | generator next/send 通常 R(StopIteration(value))；3.14 close 返回规则另列；coroutine 原始 send 类似 exhaustion |
| body Raise | 终结，先标记再 terminal drop | 保留真实 packet/traceback/current state；session 按 rule | 传播/PEP479/GeneratorExit-close 分支分别建 helper，不能只 allclose exception |
| asyncgen 正常 Return/结束 | 终结，先标记再 terminal drop | request 完成 | item request 通常 R(StopAsyncIteration)；aclose raw request 的完成另按 rule，不同于 item 请求 |
| close 注入后 body 又 Suspend | 发布可恢复续体 | 不授权 terminal drop；request/native closed 标记按方法真实路径 | 可 R(RuntimeError)；不能因为 host R 就 FinishBody |
| still-created close，成功且无 body | NoBodyFinish | 放弃已绑定 frame 引用，零 body ingress | 同步 close N(None)；async request 层另按 rule |
| still-created throw 的版本分支 | 只在明确 TERMINATE_BEFORE_ENTRY 边 NoBodyFinish | 先保留 normalize 的真实 callback/后态；不是本轮八组已测事实 | 按真实异常/版本 rule，不统一提前归一化 |
| 已关闭/exhausted 的方法，无 body | 不新造 body commit | 不重放上次 return/release；保留当前 prep 效果 | next/send/throw/close 各有结果，不由“closed”统一定型 |
| Gate 拒绝/running/首 send 不合法 | 无 BodyDrive/commit | 不消费该步续体；其他 callback 已有写保留 | gate R 当前 partial state；不能作为 body Raise |
| delegate-only 产 item | 无父 body ingress/commit | 本步不消费父续体；delegate 可自行更新/嵌套驱动 | 用 helper 实际结果及最新态；不是恢复旧父 world |
| prep/normalization/delegate helper 失败 | 无直接 body commit | partial state 保留；如有嵌套驱动，其结果已在当前态 | helper R，不凭它终结外层 body |
| terminal finalizer 的普通异常 | 原 commit 保留 | unraisablehook 可写/分配/再入；可能不完成 | 若窄 FrameRules 适用且完成，保留 pending；不直接改成 host R |
| release wrapper 或 host adapter 真正抛错 | 不 rollback commit | 保留其真实最新 partial states | 独立 R；不能用旧 snapshot 交出 |
| traceback 后来才放弃最后引用 | 已终结，不新 commit | 在当时真实上下文做普通 release；终结时不保证已 finalize | 不再次执行原 host adapter |

上述矩阵不是声明每个 family×method×状态的现成实现；例如异步 close/throw 的每个
拒绝/忽略 GeneratorExit/adapter 错误仍须下一门独立枚举和主源对应。

## 5. 静态 validator 关系与最小反例

1. **输入**：复用 paired final Gate、core current-state SSA、C2B context/cut 与
   frontier。新源/参数不绕开既有 Use ownership 或 producer，私有 FRAME_CONTEXT/
   caller token 不作为普通 driver/host payload。driver 不读取 Suspend.saved 私有槽。
2. **outcome 私有锚**：每个 Drive successor 指准确 source，landing 唯一 incoming，
   首操作 commit；owner/canonical payload/当前状态按该实际边匹配。Return 与 Suspend
   先合流后借一个 Return edge 一律 Finish/drop 必须拒绝。
3. **派生相位而非新 token**：沿真实 CFG 跟踪当前 `OUTCOME(edge,owner)` →
   `COMMITTED(edge,owner,available|finished)`；或 typed no-body 边 → finished。
   callback/分支可在 commit 以后，但每个后续动作须对所有 incoming 相位成立。
   独立 loop visit 重新 gate/outcome，不凭 static OperationID dominance 续用旧授权。
4. **释放**：TerminalReferenceDrop 只消费当前路 finished 锚，完成后标记该次 frame
   bundle 已 relinquished，回边不能重新使用同锚再放弃同一 bundle；可发散路径不要求
   造出完成。对象后续普通 decref 不受此专用 bundle 一次性约束。状态 SSA 持续独立。
5. **session**：Update 的 source 与当前实际相位匹配；NORMAL 才派生 post，失败状态
   不套成功断言。不要求通用早期 RequestGate/U-A 历史；实际 helper/state/source 路径
   义务保留，最终 gate 按当前 request/body/原始 scheduler 请求与关联/占用重新检查。
6. **宿主出口**：有直接 body outcome 的路径必须先 commit；无 body 路径按其 typed
   helper 规则。每个 host 出口只用当前域，frame terminal drop 若尚未完成，不造“已
   释放”结论；若版本要求该释放早于 host handoff，则该声明路径缺失应拒绝。

最少应作为下一门正/反 fixture：

- AWAIT→HOLD→下次相同请求重新 Gate→ASYNC_YIELD→COMPLETE，body 始终不 terminal drop。
  反例将两个 Suspend 都 COMPLETE/FinishBody，或用 R1 关联驱动同 code 的 B2。
- Return commit→callback drop：callback 读取 closed、嵌套 drive 得 exhaustion、写 world；
  后续 adapter 使用 drop 后态。反例先 callback 后标 closed，或 adapter 交旧 world。
- Created-close 无 body：NoBodyFinish→bound-reference drop→N。反例伪造 Return，或用
  任意 delegate NORMAL/host R 授予 NoBodyFinish/terminal drop。
- Return、Suspend 两实际边分别 commit 后合法合流；反例借另一条边的 source/owner。
- body DEL 在 Attached/RUNNING 触发回调；traceback 保活到外层 handler 结束后再回调。
  反例把所有 release 统一后移或断言 terminal drop 后引用必死。
- helper R 的 partial state 保留；unraisable 与 adapter R 分开；反例统一吞掉真正 close
  异常，或统一把 finalizer 错误当 host R。跨回边复用旧终结锚重复 frame drop 也拒绝。

## 6. 复用与证据权限

普通 Operation/Region/INVOKE 足以表达 normalize、association lookup、session 写、
retain/drop callback、异常/返回适配；需要新增的是上述**规范端口之间的阶段/来源
关系**，不是给每种协议重做计算节点或状态解释器。FrameRules 条件仍未知，source
匹配、动态 owner/activation/generation、gate 原子语义、真实 native phase 顺序仍须
独立证据。静态结构通过不能授 runtime 等价、物理 free/ready 或 transform 权限。

一个 opaque native INVOKE 的 completion 已含其内层 release/callback effects。
采用内部图时它们是**同一调用的分层表示**，不得额外再运行 drop，不得重复计状态写，
也不能将 outer inclusive 时间与 inner 时间相加。未能完整映射的区域保留 opaque，
不因本提案拆出回调而声称 collector 已观测到它。

**Observed（既有，本轮未重跑）**：`lifecycle-witness` 八组首跑8PASS/0FAIL，
CPython3.14.7；terminal finalizer 在 caller/GEN_CLOSED、body DEL 在 body/RUNNING、
traceback 保活、Created-close、coroutine 和 asyncgen request/body 分层。
JSON `a363bdf0904b7108ece75b02a7d317262033cbddb4f9782e07686cbda3d07f85`。
另一 agent 的三组 raw throw/delegate/nested drive 是独立归档，不能计入本轮八组。
具体 timing 是该版本有界见证，未覆盖循环GC/复活/线程/信号/trace hook/OOM/全部方法。

主源边界复用原报告：CPython v3.14.7
[clear_gen_frame](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L1835)、
[RETURN_VALUE](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1101)、
[STORE_FAST](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L326)、
[frame 所有权转移](https://github.com/python/cpython/blob/v3.14.7/Python/frame.c#L99)、
[Created-close](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L358)、
[asyncgen request](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L1637)。
本轮未新增联网验证；官方URL与版本对应来自既有已归档审查。

**Inferred**：以上事实要求终结提交与实际放弃引用分开、session 与 body 分开。
**Proposed**：本报告 records/验证相位/矩阵；尚未冻结、实现或验证完整 D0/C2D/M1。
现有 C2B/frontier 的已验收状态保持；没有优化、加速比或自动 LeWM 建图新结论。
