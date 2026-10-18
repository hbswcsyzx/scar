# D2.3 SessionUpdate / P propagation preflight

审查基线：`817cc0ba082d7dbc5c2f97bb9049cca1056466f4`。只读；未运行测试或工作负载。

核对了 `M1_DRIVER_LIFECYCLE_CONTRACT.md` §5–6、既有 `session_contract.md`、
`validation.py` 的 INVOKE edge/state 规则及 `cleanup_forward.py` / `driver_flow.py`
的 exact-copy fixed-point 写法。冻结合同足够表达有限 must 分析，不需要新的 P token、
状态表或来源字段。

## 可直接复用的 core 事实

- `Operation.invoke_arguments` 中的 owned `UseID` 是调用输入。UNKNOWN-effects 的
  INVOKE 必须在 NORMAL、RAISE 两条真实 successor 上为 Region 每个 state domain
  产生 `CompletionResult`; 每个产生的 state domain 必须也作为本次 invoke 输入。
  `CompletionResult` 只定义该 completion 的新值，不证明 Reference alias。
- 每条 successor 按位置把 `UseID` / `CompletionResult` 接到目标 `BlockArgument`。
  core 检查 arity/type/slot 完整性；state 的当前版本可按 `LocationID` 从这些
  canonical ports 派生。无需另存 before/after world 或 P support snapshot。
- `SessionUpdate.AFTER_OPERATION` 的 L support 是 READ 域的 `StateAccess.before` 与
  WRITE/RW 域的 `StateAccess.after`。`NORMAL_COMPLETION` 只在同一个 INVOKE 的实际
  NORMAL successor 建立 support，并读取对应 L 的 state formal；RAISE 不沿用旧 P。
- `cleanup_forward._must_forward` 的“先求可达种子、再做 must”是有用的固定点样式；
  `driver_role_copies` 可借鉴 exact owned Use→formal 的读取方式。但 P 是有序
  `(R,B,post,support)` 关系，不能套用单值 set membership，也不能以已有 receiver /
  scheduler copy 代替 P 校验。

## 建议的有限 P transfer

在 terminal equality E 已固定之后，对每个可达点派生事实
`(r, b, status, support)`：`r,b` 是有序当前 Reference carriers；`support` 是每个
`LocationID∈L` 的当前 `StateVersionValue`。P 仅来自通过结构检查的 `SessionUpdate`，
或从已存在 P 经合同明确允许的操作重基；无事实即没有 P。使用有限可达 CFG 做
forward must dataflow，所有 reachable incoming edges 均参加；不能由 cycle 自举。

对每个 Reference `OperationResult` 的定义点先忘掉涉及该结果 ValueID 的旧 P；只删
该 carrier，不删另一仍存 alias 的 pair。对每条真实边一次性做以下转换：

1. 快照边前 E/P 及当前 state。先使目标 block arguments 中同名静态 ValueID 的旧
   incarnation 失效，但保留快照；target formal 是新 incarnation，不能拿 header 的
   静态 ID 与前一轮值直接相等。
2. 从此 successor 自己的有序 arguments 建立映射。只用 owning operation 的独立
   `UseID` 找 `actual ValueID → formal ValueID`；R、B 两边和各 Location state 同时
   替换。普通 `UseID` copy 可搬运旧 carrier；普通 Reference `CompletionResult` 不可
   搬运旧 R/B alias。Completion state result 只作为相应 NORMAL SessionUpdate 的新
   support；RAISE completion 从不 seed 该 update。
3. 对每条边分别用边前 E 扩展可证 alias，再完成两端 rename，最后才把各 incoming 的
   facts 做 must intersection。不能先 union R/B/origin 集合、用 joined target E 反推
   哪些 source 曾配对，或按 R 后 B 的顺序改名而制造交叉配对。若 source Reference
   未转成 block argument但仍以同一 dominating ValueID 可见，它可保持原 carrier；
   被 target formal 重定义的 ID 必须按第1步清旧值。
4. 在可达CFG上解 must 方程：entry 无既有 P 时为空；reachable 非entry先按有限候选
   fact 域取 top，并对每条边用上面 transfer、对所有真实 incoming 取交，向下迭代至
   固定点。这样保留由入口/update seed 支配的 loop-carried 事实，同时 entry 的空边
   会杀掉无种子的自循环；只做从空集合向前扩张会漏掉合法的“preheader已建立、回边
   复制”的事实。无可达 seed 的环不能自行授权 P。实现可用 per-fact seeded
   must-forward 代替显式笛卡尔候选域，结论必须等价。
5. 合流要求相同 ordered carrier pair、同一逻辑 status，且每个 Location 的支持值
   在目标点是同一个 current state formal/value。缺任何一个 predecessor 的事实就丢；
   相同的状态域集合/producer集合不够。正常普通 SSA phi 可以合并不同 predecessor
   ValueID，因为每条边都逐槽改名到了同一 target formal。

状态更新规则：普通 READ 保持 P；普通写、unknown callback/helper、BodyDrive/gate、
或其他 effects-incomplete 边界先杀旧 P。`AFTER_OPERATION` 更新杀掉所有旧 P 后，
只为该行精确 `(R,B)` pair 和新 L support seed 一个 post。`NORMAL_COMPLETION` 也先杀
旧 P，随后只在该 INVOKE 的 NORMAL edge 以精确 row pair、新 L formals seed；RAISE
edge 没有 post 承诺。`BodyOutcomeCommit` / `NoBodyFinish` 仅把仍存在的 P 从旧 L 版本
重基到它们本身的真实 after/current 组合，不生成 P；如果此前 BodyDrive/body 已杀掉
P，marker 不能复活它。`CreatedCloseTest` 只读，可保持 P。

## 必须保持的区分

| 情形 | 处理 | 防止的错误 |
| --- | --- | --- |
| 同一 Value 同时作 R、B | 允许独立角色 Uses；pair 是 `(v,v)`。边上若复制到多个 formals，可按边前 alias 与 exact copies 展开。 | 不因两个角色 alias 拒合法图；也不合并两个 Use occurrence。 |
| 两个不同 R、同一个 B | 分别维护 `(r1,b)`、`(r2,b)`。各自状态/support 独立，不能跨 request 拼接。 | 不因共同 B 把来源集合做笛卡尔积。 |
| R/B 交换 | 边映射对两个角色同时作用；`(r,b)` 变为按实际槽位映射的有序 pair。 | 不用无序集合或 sequential rename 把 `(b,r)` 当 `(r,b)`。 |
| loop header / 回边 | 允许 exact actual→formal 把当前一轮 pair/support 搬到下轮；按 reachable must 方程求固定点。 | 不因 static BlockArgument/OperationResult ID 重用把旧 incarnation 自己当 seed。 |
| 入边 post 不同 | COMPLETE 与 ABANDON 用下述蕴含闭包；其他不兼容状态丢 P。 | 不要求来源 OperationID 相同，也不把不同状态随意择一。 |

## COMPLETE 与 ABANDON

合同把 ABANDON 定义为“当前 R/B active occupancy 已撤回”，并明确它**不保证** R
协议终结；COMPLETE 明确同时保证协议终结与不再持有该 active occupancy。因此
`COMPLETE ⇒ ABANDON` 是谓词蕴含，不是“曾经调用过 abandon”的历史事件。应在同一
P 关系上作蕴含闭包：COMPLETE 可满足查询 ABANDON；must 合流 COMPLETE + ABANDON
保留较弱的 ABANDON；COMPLETE + HOLD、HOLD + ABANDON 无共同 occupancy post，丢弃
该 P。无需新增字段或事件 token。若实现只认 enum exact equality，结果虽保守但会
丢失合同定义已蕴含的 ABANDON must fact；建议显式按此两层谓词实现。

## 静态边界

这个分析验证的是typed 声明、actual Uses、completion landing 和 core 当前 state，
不是 native guard/回调真实建立了状态，也不是 Reference 的物理身份、互斥、或
transform 许可。`SessionUpdate.NORMAL_COMPLETION` 若 tag 声称 helper 在 callback
之后重建 P，静态 edge 只负责把该条件声明接到该 helper 的 NORMAL L state formals；
不能从普通 INVOKE 的 NORMAL 结果自动推出 post。RAISE 的 partial state 不得 rollback，
也不得推断“post 肯定没发生”。

输入文档 SHA256：`M1_DRIVER_LIFECYCLE_CONTRACT.md` `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`；
`session_contract.md` `27505cc15f9d2bcdb8e3f3fc112dea688484226b8d700ef99331b051dc26060c`。
