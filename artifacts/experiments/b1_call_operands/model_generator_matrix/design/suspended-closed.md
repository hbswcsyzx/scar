# 同步 generator Suspended / Closed 分母与 close 连接审查

基线由root指定 `b88670b`。**SOURCE_OPEN；本报告没有运行Python、pytest、native观察或probe。**
本阶段仅设计源审，不宣称完整P2/C2/D3或M0–M2完成；随后获授权的close新fixture/tests另存focused证据。
Observed指本工作树源码/规范；Proposed指本门最小修正。native行为以版本合同/另一owner原始观察为前提。

## 1. 现图足够表达，不应另造phase/producer

原raw pack有有序owned Uses；RequestProcessing自己的结果及N/R后态、ContractResult、PacketDefinition、
FinalBodyGate准确delivery、BodyResume的准确Suspend successor/ResumeSlot、first-body-outcome、DriveResult、
原adapter CALL/INVOKE及HostTerminal都已有。私有gate NORMAL仍只能进入唯一Drive，不插计算。
`resumption_program` packet landing首Attach，Detach紧邻真Return/Raise；修改body必须在Attached窗口。
状态只复用原StateAccess/CompletionResult→formal，不保存旧共享state；current handled-context跟本drive切换。
retry用第二个真实Suspend/landing/BodyResume或下次调用输入，不把host RuntimeError写作body终结。

具体可复用：

- `program_protocol_graphs.generator_protocol_program(target='value'|'packet')` 的真实processing→gate；
  `_adapt_return` 的constructor NORMAL Ref→原PacketDefinition→host RAISE与constructor RAISE原packet。
- `program_driver_graphs.driver_program(body_graph=...,target='packet')` 已按准确first-outcome生成每条Drive出口；
  此builder默认generic host路线须改成Python该请求的真实adapter，不能直接当Python正例。
- `program_publication_graphs.with_publications` 每出口首commit，来源是实际Suspend/Return/Raise；Suspend不种F。
- `program_resumption_graphs.resumption_two_cuts_program` 现成两cut保存/重附着机制；扩packet successor用于close retry。
- `resumption_cleanup_invoke_program` 现成finally中Suspend、恢复后helper N/R、Resume/新Raise Replace、原state链；
  它目前pending原Return且只有SENT ingress，不能改名便声称GeneratorExit finally；须新增实际packet ingress/pendingRaise。
- `no_body_program` 的CreatedCloseTest真/假分支是Created-close已有接口；不可拿来证明Suspended-close无入口。

## 2. 完整Suspended四请求子分母与精确路径

| 请求 | 原图必须相连 | 正例子路径 | 不能删掉的反例 |
| --- | --- | --- | --- |
| NEXT | 原NEXT→CHECK_NEXT自身None结果/准确None来源→gate→SENT_VALUE | 继续YIELD；bodyReturn→StopIteration；普通body异常 | 非None已知literal；换旧same-typed sent；跳过处理而复用旧state |
| SEND | 原SEND ordinal0→处理器独立owned Use→自身准确结果→gate→SENT_VALUE | None与非None；返回/yield/异常 | 错ordinal、跨op复用Use、处理器本轮result换loop上一轮carrier |
| THROW | 原1–3 ordered operands→source-relative normalize N/R→整体packet或原pack→THROWN_PACKET | body捕获后YIELD/Return；未捕获packet；constructor回调异常按真实源CFG处理 | Q packet错接；tb ordinal2错；不能把normalizer所有RAISE一律当终结 |
| CLOSE | 原CLOSE→GeneratorExit构造/packet→THROWN_PACKET | bodyReturn(v)；未处理GE消解None；其他异常传播；再次YIELD报错；失败后retry | 把sent当close、wrongpacket、忽略YIELD后种F、重试使用旧Suspend/旧context/旧world |

NEXT/None和异常类含义：已知原literal/type/port矛盾可拒；opaque helper语义与引用identity仍条件，
不能凭CHECK_NEXT/NORMALIZE_GENERATOR_EXIT名字、同类型结果或FactRef就证明Python None/异常类别。
body内部主动StopIteration逃逸必须到RuntimeError adapter；它和启动前throw(StopIteration)原样host传播不同。
普通非StopIteration body Raise仍按准确packet传播；handler捕获后Yield/Return不再算escaped Raise。

## 3. close闭合输入/输出合同（Proposed，原schema大体足够）

| 情况 | 固定source/input | 实际own输出/host要求 | F与retry |
| --- | --- | --- | --- |
| bodyReturn(v) | 本DriveResult index0，source真RETURN，原adapter input Use copy v | close直接host RETURN v时exactcopy；若有helper必须核其实际N/R结果，不凭存在一行adapter豁免 | 真Return commit种F；非close正常send/next仍需StopIteration |
| 未处理GeneratorExit | 本次THROWN_PACKET对应body真RAISE packet，保真实类别判断/源适用条件 | 真实消解adapter产生自己的None Ref结果→host RETURN；其真实RAISE分支packet→host RAISE | body确已Raise，commit可种F；不是NoEntry新seed |
| 其他异常 | 本次body RAISE的准确whole packet | host RAISE exact packet；若外层helper真失败则其own RAISE另接 | body terminal F；不能把所有packet都吞为None |
| 忽略GE再次YIELD | 本DriveResult index0，source真Suspend(YIELD)，是本次export | 原错误构造helper NORMAL exceptionRef→原PacketDefinition→host RAISE RuntimeError；helper RAISE原packet→host RAISE | source仍Suspend，commit不F；不得因host报错或关方法返回而release/终结 |
| retry | 下一次真实request→最新gate states→该Suspend准确resume case | NEXT/SEND继续；CLOSE再次注入；每次自己的first outcome/adapter | 不得回退前一个Suspend、重新Enter旧cleanup、或复用旧caller token |

`CLOSE_RETURN_VALUE`目前名字/源码混含直接copy特判，至少须规范细分上述return-copy与GE-suppression。
可沿现OutcomeAdapter+原helper own-result表达None，不需要另造producer；若一个rule不能唯一固定这两种端口角色，
增加一个封闭的GE-suppression rule是有限合同修正，不能用通用relation/phase字段替代。
异常类别判词应连真实原predicate/branch/currentstate或保source applicability gap，未解析时不能自授native类证明。

## 4. 源审确定的实施阻断（未执行反例）

### C1：close规则没有固定payload/result角色

`protocol_validation.py`的body_rules与_EXCEPTION_ADAPTER_RULES均未含close规则。
最小metadata增量：取`publication_program(target='start')`，增加GENERATOR_BODY scope，
给原publication.0贴CLOSE_ROUTE/CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR，input选本DriveResult index1世界state，
input_use选publication.before.0，output选publication.0的State OperationResult。
core未改变，copy与own_result可成立，却没有close专门的index0/YIELD/result-role拒绝。
必须拒这类**已知原端口角色矛盾**，它不是native来源未知。

### C2：close own-result的实际消费者链尚未闭合

`adapter_host_output`对CLOSE_RETURN_VALUE+HostTerminal直接核inputcopy，足够bodyReturn(v)原样返回；
但GE packet→正常None不能直接copy，应由真实helper产生自己的None再消费。
当前close own-result不进入connection_errors的_EXCEPTION_ADAPTER_RULES后续host核验，
可能贴一行正确input/own result后让host消费另一个同型旧值。close必须逐规则核准确own N/R→host，
错误构造的NORMAL Ref应接原packet、RAISE packet整体传播；不能只核adapter row存在。

### C3：仅local close scope缺consumer检查

SUSPENDED_CLOSE_V1主体为OperationSiteSubject；connection_errors目前跳过所有非DriverSubject。
因此localprofile单独存在时，不会运行processing→Drive consumer检查；query的_derived又按整个region列Drive，
不能视为从该site到其准确Drive的证明。最小实施选择：完整close fixture必有GENERATOR_BODY driver scope，
localprofile补义务；或从原anchor CFG精确派生所服务driver/入口并复用同consumer规则。
不可让两个close sites共享region便互借另一site结果/Drive。

### C4：escaped StopIteration与Closed阶段仍欠源相对义务

现只有已声明adapter行才核bodyRaise→RuntimeError sourcekind；没有异常类别原判词时不能机械判定哪个RAISE必须转换。
应以原body异常分类分支/封闭source协议为锚，逐分支核转换或propagate；unknown保持准确缺口，不能所有RAISE统一转换。
Closed四请求现fixture有本次helper N/R→host、wrong-old-payload反例，但raw外部且没有当前Closed判词来源，
所以它只是条件结构正例，不能拿它冒充Running拒绝或全Closed语义已实测。

## 5. Closed四请求与守恒义务

NEXT/SEND：本次Closed helper自己的StopIteration packet→host RAISE，不能重放上次return值；
THROW：本次raw异常规范化/构造的实际packet→host RAISE，不进body；
CLOSE：真实None结果→host RETURN，不进body。
每项均含真实helper N/R后态、current owner/raw、准确terminal；缺raw/phase来源为gap，不造BodyDrive/INITIAL seed。
删除processing/adapter/scope不能令义务消失：fixed clauses及global site-inventory gap继续保留。
Host RuntimeError、方法close完成、当前sensor标签不能种bodyF；F来自真实Return/Raise commit或可信既有NoBody来源。

## 6. 有限验收顺序与边界

先新close contracts：①STATE冒payload/result metadata-only反例，先验原core图；②bodyReturn(v)真实close返回；
③illegalYIELD错误构造own NORMAL/RAISE到host，Suspend不F；④same-typed old结果替换；⑤错误release/旧frame终结假设；
再与NEXT/SEND/THROW、closed本次结果、GE suppress/propagate、第二request retry逐项组合。
每项至少一个真实port/edge/state负例，不以枚举全16名字或旧测试总数作完成依据。
预算继续共享ValidityBudget，缺inventory/处理中断保固定分母与cursor；准备/FK成本另列，不造新execution图。
本轮不需要新前端、native采集器、backend或LeWM规则；原Python native见证另owner完成，不能把它自动连成IR身份。

## 7. 阅读范围与实际源SHA

本报告读过合同§6/控制协议§7、protocol records/rules/flow/validation/query、
resumption_flow、resumption_program/two_cuts/cleanup_invoke、driver/publication/no_body fixtures，
protocol path_safety及resumption_cleanup tests。没有运行或声称这些测试在本基线已通过。
完整SHA清单另存同目录`suspended-closed.sources.sha256`；HEAD基线来自root，不执行git。
