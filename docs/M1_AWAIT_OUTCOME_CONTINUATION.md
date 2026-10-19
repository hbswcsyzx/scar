# Await完整结果链：下一段连接的只读审查

2026-10-19；产品基线 `7a776f8adf82a98df1f571e215cc55d14d4260f3`。
继续 [完整单位计划](M1_AWAIT_OUTCOME_PLAN.md)，不是另设替代原A–H的helper门。
原F12–F24/X25–X27十六组、P5、M2原113构造/196字段及M0–M2仍OPEN。
本文件为 **Proposed / 未冻结接口设计**；未实现、未执行新测试、未授变换权限。
已验证的1454项仅见 [上一进度报告](M1_AWAIT_OUTCOME_PROGRESS.md)。

## Observed：三路只读审查的共同结论

A `/root/cleanup_forward_review`、B `/root/value_resource_review` 与C
`/root/reuse_capture` 在上一轮归档后阅读原实现和fixtures，未执行Python、
tests、probe、compile或写入。以下源码事实不是新runtime实验结果。

- `_Await.expansion` 枚举各stage自己的RAISE结果；bool qualification产出的是
  OperationResult，拒绝腿后面的真实异常构造/RAISE没有进入该失败清单。
  原CFG、packet、父Get失败consumer均已存在，缺的是这些部分之间的准确连接。
- `await_connections` 尚未从原BodyReturn及caller Use派生完整最终consumer库存。
  若只遍历现存adapter或它的附件，整份附件删除后义务会消失。
- `consumer_ledger` 支持row=None及显式source/site/source_operation；其中保留任一
  guard可达的候选属于may库存，不能当全case消费证明或变换资格。
- `host_output_copy` 可核异常Reference经原PacketDefinition组件进入whole packet；
  它和 `host_terminals` 不接完整caller/choices参数，不能直接当多incoming的
  完整tuple证明。BodyReturn也不能靠普通跨region copy自动成为caller结果。

## Proposed：仍用原实体和端口

保持Operation / Value / StateLocation / Region / Resource、Program23与Execution8。
在现有await报告内派生临时outcomes/失败路径视图，不造producer、第二数据身份、
可写控制边或新的公共入口。接口字段待下一步有限审查后冻结。

每个outcome先从原source、advance operation、caller/guard/current context和
DriveOutcomeRef建立；可选producer/final adapter与consumer附件不进入原key，
只左连接。advance各N/R和extractor各own N/R必须分别保留，不能ANY覆盖缺腿。
从原OwnedUse/HostTerminal保consumer锚；无足够callee语义或opaque路径仍未证。

四种情况分开：

1. Suspend→中间handoff/后续request。
2. BodyReturn→固定StopIteration转换的own NORMAL→原whole packet→driver原RAISE
   →本advance RAISE→最终提取。只有该链要求最终完成值提取。
3. 转换自身RAISE→构造失败的新packet，不能误当第2条完成链。
4. BodyRaise及lookup/call/资格/其他异常→自身packet的传播或准确已声明适配。

BodyReturn.value→StopIteration.value→提取器own NORMAL是固定规则下的条件语义
投影，不进普通copy/identity闭包；不靠label、数值相等或最终出现RAISE断言完成。

## Proposed：bool拒绝腿的具体连接

沿准确qualification的polarity取原reject ControlEdgeReference，携带此前lookup
NORMAL、call NORMAL及reject条件，从该边沿原CFG枚举真实终端。不在BRANCH上
伪造InvokeLiteralResult；不把其他早期失败终端代表该拒绝。

逐终端选择原whole packet Use，与本次父Get RAISE的准确signature/result slot核
拷贝；state逐location/slot核自己的post，不假设异常构造或cleanup无状态变化。
再连接父Get既有host consumer。当前packet definition只说明组件来源，不证明
异常类是TypeError；异常类别无独立依据就单列gap，不能靠fixture名称认证。

## 可复用实现及限制

- `ProgramIndex.drive_outcomes` / `drive_bindings`：原BodyDrive后继、原body payload
  与landing formal绑定，先于任何adapter lookup建立分母。
- `ProtocolFlow.port(DriveResult)`：准确source-relative结果端口。
- `_result_copy` / CallReturns / 原exit port Uses：准确callee、kind、slot出口。
- `consumer_ledger`：may消费者库存；再按本case/caller/choices作must与correlate。
- `host_output_copy` / 原ExceptionPacketDefinition：Reference异常进入whole packet
  的候选证据，再在同tuple上核，不能把异常对象直接当packet。
- packet continuations的完整后继库存：可复用原C1关系，不因一个前沿就宣布完成。
- Execution的 `call_validation._outputs` / `resumable_flow.output_views`：准确
  actual/formal、successor index、result ordinal及forwarded state，不由slot顺序猜。

准备索引一次建立；所有派生共用一个context/budget，按outcome、转换各端口、
packet candidate、callee/CFG、consumer与binding/correlation计费。不得为每个
consumer重建ProgramIndex或重置4096。consumer_ledger逐source全Use扫描不能
不加缓存地套进每个outcome。

## 下一步自主验收顺序

1. 冻结临时视图字段、原key及完整/截断计数含义，再写公开接口的真实首红。
   不改上一归档及旧fixture；新测试与实现由不同作者承担，root串行执行。
2. 核bool拒绝packet/全部state/host consumer；零cut和两cut核第2链，并核构造
   RAISE/BodyRaise/中间handoff不被强迫最终提取。
3. 删除两条final adapter及receipt，原BodyReturn/extractor key与count不减而为
   missing；删除producer adapter，原BodyReturn保missing conversion。改为旧packet、
   同型entry值、另一个caller或仅剩extract RAISE行，不能填平原准确义务。
4. Execution只从实际CallActivation/DriveExecution/selected transfer投影，不能
   反选静态expected。删extract capture仍保静态分母及missing，不伪造发生。
5. 回到完整A–H的三路source、W/B、mixed/current/crosscaller、删除附件和budget1。
   已知原BodyDrive后继总数与checked/pending分别列出；尚未完成的callee/consumer
   总数必须明确未知与cursor，不能把已查prefix叫原总数。
6. 原16组齐后才组件及一次冻结full，然后P5/M2原清单；每门保真实失败、源码
   指纹、独立复审、版本与远端核对。当前不跑LeWM benchmark或新增backend。
