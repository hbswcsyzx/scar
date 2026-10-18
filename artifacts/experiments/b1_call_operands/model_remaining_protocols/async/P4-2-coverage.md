# P4-2 async/request/cancel：部分实施检查点

2026-10-18。状态 **WIP / PARTIAL，完整 P4 与本组家族验收均 OPEN**。
本报告只约束下面三个自有文件。原 F16、F17、F18、F19、F24、X26 六组分母全部保留；
39 个本文件参数化用例通过不是六组完成率，也不是完整 16 组 P4 通过。

## 1. Observed：本次实际交付与证据

源码：`scar/ir/program/protocol_async.py`；规范事实仍是原 Operation/Use/结果、state SSA、
CFG、driver、body、publication/session/release 记录。本模块只解析原端口并列条件/缺口。

公开接入函数：`async_connections(ctx)`、`async_errors(ctx)`、
`request_state_errors(ctx,row)`、`request_state_view(ctx,row)`。
只接受 root 的原 `ConnectionContext`，共用其 index、must-copy/caller recipe、current
检查和一个 `ValidityBudget`。不执行 provider，不添加 actual/producer/phase/SSA 图。

主要结果字段：`inventory, associations, deliveries, session_outcomes, cancellation,
obligations, gaps, cursor, issues`。inventory 在分析前保存原 scope 对应的 drives、
association markers、session updates 与 bindings；预算耗尽保 NOT_CHECKED/cursor。
源码 preparation 的原行库存是额外成本，不伪装成预算内 native/capture 证明。

定向命令（所有 attempt 各自保 command、stdout/stderr、JUnit、前后源码指纹）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_remaining_protocols/run_focus.py \
  async/attempt012 tests/unit/test_program_async_connections.py
```

终态：**39 passed in 2.64s**；runner wall 3.378759217s，Python 3.14.7。
开发期联合指纹在测试期间改变：仅 `tests/fixtures/program_continuation_cleanup_graphs.py`
由 C 更新。三个自有文件稳定。因此是有效自有定向结果，**不是冻结 component/full**。
没有运行 component/full、GPU、LeWM workload、native probe，也没有 commit/push。

## 2. 固定六组台账

| 分母 | 已接的原关系与正例 | 必要拒例/缺失例已验 | 尚缺的验收，不能删项 |
| --- | --- | --- | --- |
| F16 | 四种原 L pack → 本次 AsyncRequestCreate NORMAL R → caller actual/formal → association READ 的 B/L；R 与 S 独立。真实 R-state READ → own bool → BRANCH。首步 NEXT 实际 None、SEND ordinal0；首步 THROW/CLOSE 真实 L normalizer N/R →准确 packet；后续 NEXT/SEND 用本次 S。 | B/L 两 NORMAL 端口互换、外部同型 B 代 association B、CLOSE normalizer 误读 S、bool 错来源、删除附件保原库存。Create failure 与规范化 failure 都有真实 packet+逐域 post-state。 | request 重用、竞争的完整多次调用/状态图；多 request / 分支两个 Create 的整组 caller/CFG 反例；后续 S 的 THROW/CLOSE；首步 SEND 与 **B Created** 条件的完整 CHECK_INITIAL_ASEND 组合。R 首步不等于 B Created。外部 R 保 origin gap，不选同 region 唯一 Create。 |
| F17 | 原 ASYNC_YIELD outcome → 本次 R COMPLETE、B 仍 suspended；原 AWAIT → HOLD；item adapter 的真实 N/R constructor 与 host packet 路线保留。 | AWAIT/COMPLETE 与 ASYNC_YIELD/HOLD 错配拒；R 完成后试图 release suspended B 拒；删 source binding 保 outcome/update 分母。 | 同一个 R 经多次 AWAIT 再 ASYNC_YIELD 的完整执行组合；共享 update 多 incoming 的覆盖正反例；所有 item/result consumer 的完整 ledger 仍依 root shared 检查，不能拿本文件路径代替。 |
| F18 | async body Return 用原 None payload；Return/Raise 精确 source 对应本 drive publication/session。已知非 None 原 literal Return 拒。 | 错 source 的 session relation 拒；非 None payload 拒。自然 Return 与 active Raise 都保原出口类型及原 packet，不猜异常类别。 | 源级 nonempty-return 的编译非法判定不是本模块实现；主动 StopAsyncIteration/StopIteration 转换及错误 adapter 的完整正反例仍缺。当前 `async_return_source_classification_unproved` / `async_terminal_exception_classification_unproved` 是精确缺口，不是 native 通过。 |
| F19 | athrow/aclose 的请求 L 类别保持 THROW/CLOSE，不伪装相互替换；close 的 normalizer 允许既有 GeneratorExit 规则。aclose-yield-error marker 不盲推普通 item COMPLETE。 | 规范化 NORMAL/RAISE state 分开、错误 L/S role 拒。历史 first-step branch 可解释为何选 L，但 helper callback 改 state 后保持最终 gate 重检 gap。 | closed athrow/aclose 的版本条件、ignored-GeneratorExit 后续体、request/native closed bit/frame occupancy 区分的同图消费者与状态组合尚缺。此组 **OPEN**，不能由已有 enum 或 source FactRef 标为实现。 |
| F24 | 原 Task create 的实际 body Use 与成功 Task result → 独立 cancel Task receiver → 独立 injected packet → exact THROWN_PACKET；handler 真 context RW/after-state →真实 continuation；或原 body packet RAISE → host RAISE。实际 Task status READ/own bool/consumer 与 cancel bool、body结果分开。 | Failed Task Create 不能供 target；完整 CancelDeliveryRef 换 packet 拒；另 Task/另 bool 拒；第二 delivery 不能借第一 handler 消掉分母。CURRENT_AWAITED 真实 Task read 的 Future 结果没 forwarding，保 specific gap，不认作 parent body；OWN_CONTINUATION 错 source 拒。删除 delivery/handler 仍保 clause 分母。 | 取消被抑制后再次 AWAIT 的真实组合；C1 finally/新包 Replace；远端 Future/Task request→callback→continuation 的真实原链；同 caller 多 delivery 的 guard/context 细矩阵；完整 Task native state transition 不是本模块证明。 |
| X26 | 普通 metadata post 与真实 INVOKE NORMAL SessionUpdate；RAISE 原 packet+全部 partial states；NORMAL 后窄 terminal frame release；Suspend 不授 F。 | session post 错源、错 post、Suspend release 拒；helper 只有 NORMAL post，RAISE 不能借正常结果。 | ContractResult helper 源的完整 R/B/current/selected-edge 语义尚未闭合：当前只解析原 port 并列 `async_session_helper_semantics_unproved`。多锚合流/回调后重建/terminal eligibility 的全组合仍缺，不拿已有 D2 core 回归冒作本门新覆盖。 |

## 3. Inferred：目前允许的条件结论

- R→B/L 是固定 request 接口的**条件语义投影**，不加入 ordinary-copy closure。
  原 R-origin 的 caller recipe 独立于 actual B；L 的原 recipe 通过 root
  `extend_context` 对齐调用前缀并核 source anchor 当前性，再与本次输入联合。
  不按同型、名字、唯一 Create 或同 ValueID 猜 request/instance。
- 首步/续步由原 RequestStateCondition 的准确 BRANCH 路线决定。helper/callback 后
  `read_snapshot_current=False` 不删除历史 bool/分流，但保
  `async_initial_selection_snapshot_changed`、当前 gate 重检与 native 未证条件。
  它不保活旧 P、request phase 或跨 callback 许可。
- TaskCreatedTarget/TaskTargetRead 是独立 expected 接口锚，actual delivery receiver
  另从原 BodyDrive 或 delegate throw Use 派生。Task status 是自己的原 READ/结果，
  不从 request bool 或异常 class 推 cancelled。
- CURRENT_AWAITED 的未知中间桥/current support 不能变成 True。packet 的最终传播
  复用原 body 输入 recipe、实际 RAISE source 与 host packet copy；不虚构 handler。
- 所有 source/runtime/value-identity/transformation flags 继续 False。source/site
  inventory 未穷尽是独立缺口。没有声称自动运行恢复、自动调度、same-runtime-body 身份、
  native applicability、全 M0–M2 或任何优化权限。

## 4. 实施补充决定（不改冻结 v1 字节）

root 于本轮明确同意 `ASYNC_REQUEST_DELIVERY` 允许既有
`NORMALIZE_GENERATOR_EXIT`。真实 aclose latent 仍是 CLOSE，不伪装 THROW。
root 改固定 rule table，A 同步 Program19 capability gate；本文件只用该批准规则。

## 5. 全部原始尝试（不覆盖）

| attempt | 原结果 | 归因/处置 |
| --- | --- | --- |
| 001 | 20F | A records `_model_classes` 三返回值误解包四；A 修，原 traceback 保留。 |
| 002 | 9P11F | 自有 session R 比较过度限定 Drive landing；自有 caught-body/driver result 类型未联动。 |
| 003 | 14P6F | 自有 caught Return 后保留无终端 Raise exit；修 fixture，不放松 core。 |
| 004 | 14P6F | 上次 fixture 修正漏 import ExitKind；保原输出。 |
| 005 | 2P | 只复跑 caught/uncaught cancel 两正例，不能加成独立最终用例。 |
| 006 | harness exit1 | runner 不接 `-k`，在 collect 前拒；保存精确命令/trace。 |
| 007 | 6F | fixture 用错 `raw_driver_requests` 表名；request view 错要求 BRANCH 虚有 state Use。 |
| 008 | 6P | 修原表名；source READ inputs 与 gate 当前支持分开，不增 branch 假输入。 |
| 009 | 28P2F | 真实 normalizer 后 state 变化；错误抹掉历史 first-step 分流。root 明确批准保历史选择但保 gate 重检 gap。 |
| 010 | 32P | 上述来源/后态、CURRENT_AWAITED 缺桥和 terminal propagation 检查通过。 |
| 011 | 36P1F | 新测试错误用字符串而非 StaticGapReason；严格 constructor 正确拒。 |
| 012 | 39P | 本检查点最终自有文件，见 §1 的并发非冻结范围说明。 |

## 6. 自有源锁定与后续

三个自有文件 SHA256：

```text
77ac67b0ff46e3b8d8c8e90b8b1e88a1c715b05f9de50cbc9c2d6a4d7c3ca900  scar/ir/program/protocol_async.py
f75ed1fe40bc816da6451ff230797a0099efb4dde20f9221507e27c7935b1b5e  tests/fixtures/program_async_connections.py
121a3f67c42cfba5392180bce78568d5191325d16fcee9553a26ba8df30bbb69  tests/unit/test_program_async_connections.py
```

本报告后遵 root 中间归档指令暂停源码/测试写入与执行；后续按本台账 OPEN 条目继续，
不把本部分检查点当整组或整个 P4 关闭。
