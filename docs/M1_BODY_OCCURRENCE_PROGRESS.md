# P3 持续执行关联实施记录

2026-10-18，基线`a740661`。按[计划](M1_BODY_OCCURRENCE_PLAN.md)的O01–O16推进。
状态：**166定向及517组件通过，但首次冻结全仓5,816通过/6失败；P3未验收**。
不因局部green、测试数量或手工IR而声明P3、D3或完整M0–M2通过。

## 1. 已落实的模型连接

- 原operation/Value/Use/State/CFG保持canonical；新增两自然键关联表，不添加
  association ID或第二SSA。Execution8条件能力，独立旧v7 golden来自旧提交。
- 一持续activation两次驱动、精确旧Suspend发生、新segment、当前/saved输入、
  本次首出口和selected Drive source、输出/forward分别解析。
- Create NORMAL handle/captures、跨次owner、每个binding及相关中间copy边核
  scoped身份声明。不同Data版本不能直接推数值不等，缺身份/断采保精确gap。
- entry/completion两host桥独立；缺路径support不伪装完整捕获。原CALL/body/
  local链的有限端点压缩后核真实occurrence因果环，不对activation强制DAG。
- fresh外部快照重放、detached公开query、共享预算/cursor与typed wire只读CLI。
  `validation_gaps`显式保fresh整体限制，不由局部DECLARED隐藏缺artifact。

## 2. 有界检查点与原失败

证据根：`artifacts/experiments/b1_call_operands/model_body_occurrence/`。
以下测试有重叠，不累加为覆盖率；局部共享开发指纹变化见原receipt。

| 检查 | 实际结果及范围 |
| --- | --- |
| records/codec | 54通过；严格nested类型、两tuple、v8迁移和独立v7 oracle。不是运行关联验收。 |
| links | 33通过；真实原图的多次驱动、原输入/输出、线程/实例/状态及缺采反例。最后定向期间其它owned文件有变化，不能充当全源冻结证据。 |
| host-order | 26通过=11新+15旧CALL，不与先前11重复相加；含core-valid混合因果环。 |
| prefix | 4通过；完整A/B、已走A但terminal漏采仍拒断开B，真正缺transfer且B合法时保gap。 |
| values | 最终4通过；真实Data saved输入、同/不同版本与fresh catalog修改。前两次3失败/1通过是fixture错误：source误用Unresolved、consumer错误放在Detach之后；修原记录/位置，未放宽产品guard。 |
| port-review | 原中间copy反例1失败/2通过，暴露产品真实漏检；修复相关ancestor边后4通过，再补当前/持续owner、去ObjectID的Create来源和query support，11通过包含4个values；另两自然键反例2通过。 |
| CLI | 最终24通过；原21通过/3失败暴露外部缺口未进CLI报告，保留失败后接fresh validation_gaps。显式wire与输入字节保护均实际检查。 |
| 首次统一本批 | 137通过/13.13s，全注册源码指纹稳定；之后补了自然键及Create失败路线的明确原验收项，需要再统一冻结验证。 |

原host fixture的复用owned Use和错误私有landing分别被既有core guard拒绝；
改正原实际端口后才构造合法混合cycle。不是放宽产品去容忍坏图。

## 3. 独立审查与真实修复

审查先发现缺activation会遮住已知endpoint kind，以及缺Drive的body activation
未进入origin分母。实现分别检查已知端点，并枚举所有捕获的resumable activation。

另一个真实阻断是H(A)→formal X(B)→owner Y(A)：两端相同不代表中间传递合法。
新增实际CALL/CFG反例先复现1失败，再基于原predecessor索引，只对已声明body
关系所用端点的ancestor closure逐边核scoped identity，并保原support。独立复审
确认阻断已关闭，未运行额外测试，不授native/source或整门通过。

Create来源、当前state和不同线程之间均不能靠同code/同类型/同ValueID猜实例。
所有source/runtime/value_identity/transformation标记仍False。

## 4. 收口顺序

收口审计另补两自然键与O08实际Create RAISE/非Create/缺transfer/缺handle原图
反例，随后统一本批 **143通过/14.01s**、源码指纹稳定。版本兼容搜索又发现
content/work/order三处旧测试仍把8当未来版本，定向实际 **3失败/8通过**；
保原失败后按显式新能力规则验证8可roundtrip，并新增9拒绝，保原case身份。
这些是版本边界断言迁移，不是放宽未知version/tag或改变旧fixture；需要在最终
指纹下复验定向与组件，不能拿此前143的指纹替代。

随后的161定向通过。组件首轮 **512通过/4失败**，四个旧call变体同一断言
`SCHEMA_VERSION == emitted_version == 7`已不适用于新增最高8的情形；实际emit仍7。
修为分别核最高版本支持7与实际旧wire准确7；新v8测试另核最高版本准确8。
保留组件首败，窄验证四变体后，165定向、516组件/18标准通过。

随后来源复审发现真实缺口：已捕获的Create NORMAL handle若没有origin关联，
就不在known-create索引里；实际owner来自它、却声明另一个Create时，只报gap。
新增去全部ObjectID声明的反例，原core独立合法，窄测实际1失败。修复为从全部
已捕获Create的真实NORMAL transfer/原CompletionResult/落点建立一次索引，
不依赖origin关联；失败/缺transfer/缺handle不造值。窄验证1通过，原首败保留。
同一最终668源指纹下166定向通过/14.80s；组件第三轮517通过/18标准。
源码指纹为`43549a160f4e11005af314efa492659832b7e14f060c72b7caa9e8ab9a308ea9`，
两轮均确认测试期间未变化。随后干净`61db593`的首次完整pytest实际5,816通过/
6失败，562.467s，668源前后稳定。production旧future8及两个Program codec的
Execution最高版本7断言漏迁移；三个文件共89case未进原组件。原full保留，
按[修复门](M1_BODY_OCCURRENCE_REPAIR.md)先审计、迁移准确wire/能力断言，
再定向→组件→干净修复提交→独立`repair/full`；不自动重试。

逐条核O01–O16的实际证据，完成最后Create RAISE原图反例 → 统一本批定向 →
18标准组件 → 干净提交 → 一次冻结全仓（所有作者停写、无并行测试/工作负载）
→ 只读case/fixture/source/保护目录/manifest核验 → commit/push。若全仓失败，
保失败重新审计，不自动重试。

本批没有新backend/detector、LeWM业务规则或重型profiling。P4/P5、原113构造/
196字段及完整第一阶段仍未完成；没有新的LeWM变换或clean A/B加速比。
