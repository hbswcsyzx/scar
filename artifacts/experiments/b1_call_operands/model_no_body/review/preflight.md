# D2.2 no-body 与固定角色：只读 preflight

2026-10-18；任务基线 `e86563a`。结论：**entry seed 疑虑已由现 core 明确排除；下面的最小算法可实施，未发现需要另加许可/RequestGate/AssociationRead 的阻断。**
这是实施前设计与既有 core 的有限核对，不是尚未交付的 D2.2 validator 验收。
没有修改 tracked 文件或旧 archive，没有运行任何脚本、pytest、full、LeWM 模型、GPU、git、安装或网络。
root 在消息中明确已确认 entry 禁止回边，因此没有为报告另跑一个已被代码直接排除的 probe。

## 1. 所读源码快照

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/program/driver_validation.py` | `05883c4c05e1f39f00299b70451a4df7683774d23286cd20f69eb163ad60b521` |
| `scar/ir/program/driver_flow.py` | `57fb2c403878f751d69d43b7e94a07125a0c647ddc77fdb179b75d8bdaf0ef26` |
| `scar/ir/program/validation.py` | `12c05a4abd25f99b6506a10941c3f0d6a94c637d508d37c61ed6490b189c745a` |
| `scar/ir/program/cleanup_forward.py` | `ff99ec4320a1e65079c0988d483faec604838f0e84a260962d85a3a1955629a2` |
| `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` | `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699` |

`driver_flow.py` 此快照尚无拟提取的 `driver_role_copies`；下节描述其应实现的等价接口，非已读到的产品能力。

## 2. entry seed 为什么不会被内部回边替换

`validation.py:357–358` 对每个 Region 无条件检查 `predecessors[region.entry]` 为空，
发现任何普通/特殊 CFG 入边即 `entry_predecessor`。该阶段出现 issues 后早返，不会继续到 D1/no-body。
跨 Region CFG 边本来也不合法。callee/caller actual 不是本 Region 的内部 CFG predecessor。
因此固定 receiver/S 是**本次 invocation entry 的实际 formal**；递归/多次调用不替换同一次 invocation 的 seed。

`driver_validation.py:230–240` 又要求两角色真为该 entry 参数、种类匹配，然后 `_must_forward` 才以它们为锚。
seed 免去其自身 incoming 检查在这些前置条件下 sound。不能把此 helper 抽成接受未经 core/interface 检查的证明 API。
没有必要改 core 以支持 entry 回边，也不应把 entry seed 改成可由别的 block 反向重证的普通 phi。

## 3. `driver_role_copies(graph, interface)` 的最小实现

调用前 core 通过，并已检查 interface.region 存在、receiver/S 是合法 entry 参数。
仅遍历该 Region 的 blocks、各 block 的真实末尾 terminator，以及它的全部 successors：

1. 为本 Region 每个 block formal 建 incoming 列表，保留每条真实 edge 的实际绑定，不按 predecessor block 去重。
2. 对 `zip(edge.arguments, target.arguments)` 只经统一 `saved_actual_use(operation, actual)` 解析。
   有 canonical owned Use 就取其 `.value`；CompletionResult/BodyDriveResult/ResumeInput 等新结果写 `None`。
   非锚普通 OperationResult、别的 entry 参数、literal 不会因同类型或同 constructor 得到 copy 资格。
3. 分别以 `{interface.receiver}`、`{interface.scheduler_request}` 调 `_must_forward`，返回两份 frozenset。
   复用现 OR-LFP 限定后再 AND-GFP 的实现；不能只 union origins 或最终独立交集。
4. D1 与 CreatedCloseTest 消费同一接口；不要再建第二份全图 copy 图，不加入 call actual 或推测 association。

这与原 `driver_validation.py:210–240` 在 core 合法图上等价：Region 之间无 CFG 绑定，局部提取不丢真实 incoming。
同 predecessor 的两条分支把不同 actual 送到同 formal，仍必须都参加 AND；loop 外污染会传播失效。
无种子 cycle 不会自造 copy；锚经真转发进入 loop 的 phi 可保留；交换到另一个 entry 参数会失去资格。
这些是从现 helper 的固定点合同和 core 前置条件得到的推论，本轮没有额外执行算法测试。

## 4. predicate-only 合法；Finish 才需要真实 true-edge 首 mark

合同 `§4:75–100` 可一致解释为：CreatedCloseTest 是 READ predicate，紧邻同 block 末尾 BRANCH；
**不反向要求每个 Test 都有 Finish**。程序可只观察分支、返回别的值或执行其他逻辑，未写 Finish 就不授 no-body 完成事实。
建议在正文明确这句单向义务，避免 `test→branch→mark` 的句式被实施成 Test 的覆盖检查。
这是最小解释澄清，不需增加字段，也不是已复现产品错误。

每个已声明 NoBodyFinish 才按下面顺序严格检查：

1. `precondition` 引真实 BRANCH 的 edge0；在同 block 紧邻它之前找到已声明 CreatedCloseTest。
   branch.condition 的 owned Use 必须直接读 Test 自己的 bool result；不能用“任意 helper 的 NORMAL/True”替代。
2. Test 是无 callback 的 ordinary CONTROL/READ complete intrinsic：独立角色 Uses 与每个 L 域当前 READ；
   仅产生自己那个 `builtins.bool` DataValue。core 负责真实 producer、current state 与 Use 唯一归属。
3. edge0 直达私有 landing，实际 incoming 总数为一，首操作恰是本 Finish；不是“某个可达后继”或 source 名单。
   Test→BRANCH 及 true landing→mark 之间不能插纯计算、写入、callback、lookup 或另一个 gate。
4. Finish.instance 的 owned Reference Use 必须等于本 Test.instance 的原 Value，或由这条 edge 的独立
   owned Use→formal 精确 copy；同类型 payload、相同 constructor/port 集合、另一条分支上的 owner 都不够。
5. mark 复用 publication 的 ordinary body-only shape：真实 WHOLE READ/RW StateAccess，非空 W⊆L；
   未写域仍是 core current，W 不必等于 L；没有假 body Return、Attach/Detach 或新造 RAISE。

edge0 的语义来自 core BRANCH 的固定 true 顺序。若 true/false 都指向同 landing，真实 incoming 数为二，
不能借“目标 block 相同”把 false 也纳入完成声明。predicate-only 则没有私有 mark landing 义务。
bool 测试本身和 false 边不 seed finish；亦不把某个本地 RAW 非 CLOSE 的常量类型冲突造为 Python 异常。

## 5. S / effective / ASYNC 当前关联

- BODY：Test.instance 属于 receiver must-copy，S 属于 scheduler must-copy，effective 是 S 的**独立 Use**，
  session=None；角色端口 UseID 不能复用，但两个 Uses 可读相同 Value。
- ASYNC_REQUEST：session 属于 receiver must-copy，S 仍是原 scheduler；B 是当前 Reference，effective E 是 RAW。
  不强制 B/E 是 S，不要求 E 与 S 不同 Value，更不能把 S 自动当 latent request。
- ASYNC 的 true predicate 合同同时检查当前 R/B/E association 与当前 step 适用；真实当前 StateAccess 支撑它，
  不是早先 AssociationRead 的历史结果自动证明当前关联。该 read 存在时可用，但并非强制的程序形状。
  不添加独立 RequestGate/U-A 历史机；不因接口没独立 lookup 就拒绝合并 checks 的实现。

这里的 guard 意义是 typed primitive 的声明语义，错关联/非 CLOSE/非 CREATED 可以真实走 false。
static ValueID、coarse StateLocation、provider 名字或一个新版本号不证明实际对象关联/字段。
这些声明/source 边界已由现合同明确，不能为了 preflight 发散成全 D3/native guard 验收前提。

## 6. 后续独立复审的具体界限

待 root D2.2 代码定稿后，应检查共享 helper 的前置门、保留每条 incoming、仅 Finish 的覆盖义务、
predicate-only 正例、false-edge/非 private/owner 对调/插 callback 的反例、两种 receiver 与 S/E 不互换。
当前结论仅为 preflight 算法收敛与合同一致；本轮无新增实验，无“probe PASS”或产品验收数量。
