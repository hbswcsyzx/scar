# 原完整 await 单位：来源、持续主体与真实终点

2026-10-19；基线 `35b399d0d49b39b78530f571c448987170aa62a3`，首次读取工作树干净。
上一目标轮为 progress：1572 focused、原1551 identities 守恒、证据归档、提交和
远端 SHA 已核。完整原 A–H / F12–F24、X25–X27 / P5 / M2 113构造196字段仍开放。
本轮继续原分母，不为容易通过的单 helper 另立完成标准。

## 1. 先落实模型与时序

五类实体与 Program23 / Execution8 规范记录不变。Operation 的原参数、结果和
StateLocation 当前版本组成完整调用接口；Region 允许递归展开；Value 的来源
与物理对象身份分开。原 CFG / 端口是唯一规范关系，查询只给有证据的连接。

本轮必须把来源到消费者放在同一个 ProgramGraph 和 ExecutionModel 中：

| 来源 | 获取之前 | 获取产物 | 主体与持续性 |
| --- | --- | --- | --- |
| self | 实际 Create B | 原 self acquisition 得同 B | 原 direct/await 对照保留；本轮补最终 child 的两 cut 实际链。 |
| general | 独立入口 A | 真 lookup→bound call→创建 B→qualification→I | Get 在第0次 advance 前；B 的实际 origin 是 helper 内准确 Create，不能让新 B 从旧 B 的切点继续。 |
| native wrapper | 原 Create coroutine B | 原 constructor W，W≠B | 每次 W getter 独立投影到所持 B，经准确 wrapper→driver 调用；一次 B activation / 多 segments，W→B 不作普通 copy。 |

普通 generator 作为 general 的返回候选与 generator-coroutine/self 的适用性
必须分开；native COROUTINE_BODY 不能沿用 GENCORO 的 body scope 或 Return
转换规则。底层 native/provider 适用性未证条件保留，不以 fixture 标签授证明。

零 cut 首次驱动直接终止，不造 Resume/Suspend；两 cut 是真实先前 Suspend、
当前 entry slots 和最新 world/context。每次同步 driver 都有独立 CallActivation。
same-code 两实例、外部 decoy Create 和独立 A 不能互相补来源或 current-state。

## 2. 终点区分，不伪造统一提取

BodyReturn、BodyRaise 均由 B 实际 RETURN/RAISE terminal 定义，不由 pending
种类、constructor 自己失败、F 自己失败或名字判定。

```text
真实 BodyReturn
  → 原完成适配器的 own N/R
  → StopIteration packet / constructor failure
  → 原 advance RAISE
  → 仅有适用原合同的 E/G/F 提取或真实异常消费者

真实 BodyRaise
  → 原 whole packet delivery
  → 本次 advance RAISE
  → 原 handler / host RAISE
```

不得把任意 BodyRaise 视为 StopIteration。只有实际 exception-match 类别/guard
能支持相应处理；没有这种原条件时，BodyRaise 的 requires_final_extraction=False，
不挂 AWAIT_STOPITER_TO_EXPRESSION。旧完整 E/G/F own结果、full slot/state、
terminal OR / required AND、input support 和实际 witnesses 继续复用。

C1 Resume 保旧 Return、C1 Replace 改成新 Raise 分别接以上两支。Enter/Replace
本身不是终点；callback/effect未知不等于原 successor 不存在。pending 与 saved
handled context 在两个 cut 中分别保存，禁止把旧状态当本次 post。

## 3. 当前源码发现的连接缺口（Inferred，待独立用例）

1. `await_outcome_flow.terminal_inventory` 在 C1 Route/Dispatch/Suspend 停止。
   原 `protocol_packet_routes` 已有带预算的 active-token / possible-port /
   replacement / continuation 逻辑，应复用其关系，不另写扫所有 RETURN 的图。
   原 packet / Reference 角色必须保留；未知调用与下一 Drive 边界不可抹掉。
2. `execution.resumable_flow.prepare_value_copies` 当前仅处理有原 Use 的普通
   CFG/SavedInput 复制；`PendingPayload` 没有直接 Use，尚未回接实际 payload。
   `composition_routes` 只保 pending selector / port。不得把 token 与 payload
   当同值；应由本次实际 transfer、selector 的原 token ancestry、唯一相符的
   PendingCompletionDefinition 和该 constructor 的实际 payload Use 派生 witness。
   不按期望值或同 ObjectID 选 constructor。缺失/多候选/错 port 保明确缺口或
   已知冲突；精确实例、saved state 与条件不能丢。

深关联使用同一 shared ValidityBudget；只准备原索引，不免费预求全图投影。
静态可表达、实际发生、native适用性、value identity 和变换授权分别报告。

## 4. 作者与实际执行

- A：独占新增 C1/BodyReturn/BodyRaise 的 program/execution fixture 与 tests。
- B：独占新增 general 来源到真最终 child 的 program/execution fixture 与 tests。
- C：独占新增 native wrapper 零/多 cut 到最终 child 的对应新文件。
- root：产品连接、文档、串行运行、失败定位、完整相关回归、归档与版本管理。

只 import / 复用既有构造器，不修改旧 tests/fixtures/合同/codec。作者先交实际
完整正例与必要反例，执行前冻结；subagents 不运行 Python/pytest/probe/compile。
不复制三份并列旧图假装一条程序；每条来源有同一规范图的完整端口和调用关系。

验收包括：三路来源→零/两 cut→真实 body terminal→正确适配/异常传播→当前
caller→E/G/F own N/R（仅适用的 Return 分支）→最终消费者；两个同 code 实例，
错 source / current-state / port、缺 association / Use / completion、整附件删除、
shared budget 与 public detach。已有早失败/资格测试守恒，不以新成功路径覆盖
未执行的失败组合。报告精确未闭格，不能用总测试数关闭原 A–H/16/P5/M2。

先首红→修公共连接→独立有限审查→作者冻结→原1572 identities守恒的相关回归→
源码/失败/保护仓库核验→commit/push。全部原16真齐后才组件/full、P5和M2总核。
不加 detector/backend、LeWM 特例、profiling 或加速结论。M0–M2 真完成后按用户
要求汇报讲解，再停下。
